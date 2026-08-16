import logging
import os
import socket
import time
from typing import Callable

from app.repositories import jobs, shots
from app.services.generation import (
    GenerationNotConfigured,
    get_magnific_image,
    submit_magnific_image,
    validate_generated_image,
)
from app.services.video_model_selector import select_video_model
from app.services.video_persistence import persist_remote_video
from app.services.video_provider import (
    VideoGenerationRequest,
    VideoGenerationResult,
    VideoProviderNotConfigured,
    get_video_provider,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = float(os.getenv("MEDIA_WORKER_POLL_INTERVAL", "3"))
TASK_TIMEOUT_SECONDS = float(os.getenv("MEDIA_WORKER_TASK_TIMEOUT", "600"))
KLING_POLL_INTERVAL = float(os.getenv("KLING_WORKER_POLL_INTERVAL", "15"))
SEEDANCE_POLL_INTERVAL = float(os.getenv("SEEDANCE_WORKER_POLL_INTERVAL", "8"))
# Local generation has no per-request billing/rate-limit concern the way an
# external API does, so this defaults much shorter than the external
# providers' cadences above — faster feedback on a draft is the whole point.
COMFYUI_POLL_INTERVAL = float(os.getenv("COMFYUI_WORKER_POLL_INTERVAL", "2"))
IDLE_SLEEP_SECONDS = float(os.getenv("MEDIA_WORKER_IDLE_SLEEP", "2"))

# Providers whose submit()/check_task() pair is safe to resume: the task id
# is persisted to media_jobs.provider_task_id before any polling starts, so a
# crash or retryable failure mid-poll resumes the same provider task instead
# of submitting a new (separately billed) one. Each entry maps the provider's
# `.name` to its poll cadence.
_RESUMABLE_PROVIDER_POLL_INTERVALS = {
    "kling": KLING_POLL_INTERVAL,
    "seedance": SEEDANCE_POLL_INTERVAL,
    "local_comfyui": COMFYUI_POLL_INTERVAL,
}


def _worker_id() -> str:
    return os.getenv("MEDIA_WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"


def _wait_for_image_task(
    fetch_task: Callable[[], dict],
    *,
    provider_label: str,
    timeout_seconds: float = TASK_TIMEOUT_SECONDS,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Poll an image task to completion. Works for any submit()/poll() image
    provider using the same status vocabulary Magnific does ("IN_PROGRESS"/
    "COMPLETED"/"FAILED"/"CANCELLED"/"ERROR") — both Magnific (external,
    default) and LocalComfyUIImageProvider (local, draft_mode) use it
    unchanged; only ``fetch_task`` (a zero-arg closure over whichever
    provider/task_id is active) differs per caller.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        task = fetch_task()
        status = task.get("status", "UNKNOWN")
        if status == "COMPLETED":
            return task
        if status in {"FAILED", "CANCELLED", "ERROR"}:
            raise RuntimeError(f"{provider_label} task ended with status {status}.")
        sleep(poll_interval)
    raise TimeoutError(f"{provider_label} task polling timed out.")


class ProviderTaskFailed(RuntimeError):
    """A resumable provider (Kling, Seedance) reported a failed task.

    ``reason`` is whatever ``check_task()`` returned for this provider — for
    Seedance that is always a stable ``SeedanceErrorCategory`` value, never
    provider-authored text, so this is safe to persist into
    ``media_jobs.last_error`` and show in the UI.
    """

    def __init__(self, provider_name: str, reason: str, *, retryable: bool = True):
        self.retryable = retryable
        super().__init__(f"{provider_name} video generation failed: {reason}" if reason else f"{provider_name} video generation failed")


# Reasons a resumable provider can report that will never succeed on a plain
# retry of the same request — matches Seedance's non-retryable categories so
# the worker doesn't burn attempts resubmitting a request that fails the same
# way every time. Kling's sanitized reasons don't use this vocabulary today,
# so they fall through to the retryable default, unchanged from prior behavior.
_NON_RETRYABLE_TASK_REASONS = frozenset({
    "authentication_failed",
    "invalid_input",
    "source_image_unreachable",
    "insufficient_credits",
    "moderation_rejected",
    "invalid_provider_response",
})


def _wait_for_provider_task(
    provider,
    task_id: str,
    *,
    timeout_seconds: float | None = None,
    poll_interval: float | None = None,
    sleep: Callable[[float], None] | None = None,
) -> str:
    """Poll provider.check_task() until the task succeeds or fails.

    Works for any provider implementing the non-blocking submit()/
    check_task() contract (Kling, Seedance). The submission itself has
    already been persisted (provider_task_id) before this runs, so a timeout
    here is retryable and resumes the *same* task rather than submitting a
    new one.

    Args:
        provider: a provider instance with a check_task(task_id) method.
        task_id: opaque task id returned by provider.submit().
        timeout_seconds: total seconds before TimeoutError.
        poll_interval: seconds between polls.
        sleep: injectable for testing.

    Returns:
        The completed video URL.
    """
    # Resolved at call time (not as bound defaults) so the poll cadence and
    # the injectable clock can be overridden — including by tests — after the
    # module's constants are set.
    timeout_seconds = TASK_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    poll_interval = (
        _RESUMABLE_PROVIDER_POLL_INTERVALS.get(getattr(provider, "name", ""), KLING_POLL_INTERVAL)
        if poll_interval is None
        else poll_interval
    )
    sleep = time.sleep if sleep is None else sleep
    provider_name = getattr(provider, "name", "Provider")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        sleep(poll_interval)
        status = provider.check_task(task_id)
        if status["status"] == "succeed":
            return status["url"]
        if status["status"] == "failed":
            reason = status.get("reason", "")
            retryable = reason not in _NON_RETRYABLE_TASK_REASONS
            raise ProviderTaskFailed(provider_name, reason, retryable=retryable)
    raise TimeoutError(f"{provider_name} did not complete within {timeout_seconds:.0f}s.")


class SyncAudioRejection:
    """Stable, sanitized reasons Sync audio was refused. Never carries values."""

    NO_AUDIO_REFERENCE = "no_audio_reference"
    INVALID_AUDIO_REFERENCE = "invalid_audio_reference"
    AUDIO_NOT_RESOLVED = "audio_not_resolved"
    AUDIO_URL_EMPTY = "audio_url_empty"


def _resolve_approved_audio_url(job: dict, payload: dict) -> tuple[str | None, str]:
    """Resolve the approved, project-owned audio URL for a video job.

    The client-supplied ``payload["audio_url"]`` is never read. Only
    ``payload["audio_media_result_id"]`` is honoured, and it is resolved
    through a shot- and project-constrained repository query.

    Returns:
        (url, reason). ``url`` is None whenever Sync must not run; ``reason``
        is a stable category safe to log — it never contains the identifier,
        the resolved URL, or any client payload.
    """
    raw = payload.get("audio_media_result_id")
    if raw is None or isinstance(raw, bool):
        return None, SyncAudioRejection.NO_AUDIO_REFERENCE
    try:
        media_result_id = int(raw)
    except (TypeError, ValueError):
        return None, SyncAudioRejection.INVALID_AUDIO_REFERENCE
    if media_result_id < 1:
        return None, SyncAudioRejection.INVALID_AUDIO_REFERENCE

    from app.repositories import media_results

    # A single constrained query proves existence, shot ownership, project
    # ownership, media type and approval together. Missing, cross-shot,
    # cross-project, wrong-type and unapproved records are indistinguishable
    # here by design, so a rejection reason cannot be used to probe for the
    # existence of records in other projects.
    record = media_results.get_approved_audio_for_shot(
        media_result_id,
        job.get("shot_id"),
        job.get("project_id"),
    )
    if not record:
        return None, SyncAudioRejection.AUDIO_NOT_RESOLVED

    url = record.get("url")
    if not isinstance(url, str) or not url.strip():
        return None, SyncAudioRejection.AUDIO_URL_EMPTY
    return url.strip(), ""


def _maybe_apply_sync(
    video_url: str,
    payload: dict,
    *,
    job: dict,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Apply Sync.so lip-sync when approved dialogue audio is available.

    Conditions for Sync to run:
      - audio_mode == "dialogue"
      - payload["audio_media_result_id"] resolves to an approved audio
        media record owned by this job's shot and project
      - SYNC_API_KEY is configured

    ``payload["audio_url"]`` is deliberately ignored: a caller must not be
    able to point Sync at arbitrary media. ``job`` is keyword-only and
    required so no call site can skip project scoping.

    A Sync failure is logged as a warning but never cancels the Kling video:
    the original video_url is returned unchanged.

    Returns:
        Lip-synced video URL, or original video_url if Sync is skipped/fails.
    """
    if payload.get("audio_mode") != "dialogue":
        return video_url

    audio_url, rejection = _resolve_approved_audio_url(job, payload)
    if audio_url is None:
        if rejection != SyncAudioRejection.NO_AUDIO_REFERENCE:
            logger.warning(
                "Sync.so skipped — approved audio not resolved (reason=%s)", rejection
            )
        return video_url

    from app.core.config import settings
    if not settings.sync_api_key:
        return video_url

    from app.services.sync_provider import (
        SyncErrorCategory,
        apply_lip_sync,
    )

    try:
        return apply_lip_sync(video_url, audio_url, sleep=sleep)
    except Exception as exc:
        # Log only a stable sanitized category. str(exc) and exc_info are
        # never used here: provider bodies, signed URLs and the video/audio
        # URLs under processing must not reach the log stream.
        category = getattr(exc, "category", None)
        if not isinstance(category, str) or not category:
            category = (
                SyncErrorCategory.TIMEOUT
                if isinstance(exc, TimeoutError)
                else SyncErrorCategory.UNEXPECTED_ERROR
            )
        logger.warning(
            "Sync.so lip-sync failed — keeping Kling video (category=%s)", category
        )
        return video_url


def _process_image_job(job: dict) -> dict:
    shot = shots.get_shot(job["shot_id"])
    if not shot:
        raise ValueError("השוט של משימת המדיה לא נמצא.")

    payload = job.get("payload") or {}
    draft_mode = bool(payload.get("draft_mode"))

    if draft_mode:
        from app.services.providers import comfyui_client
        from app.services.providers.local_comfyui_image_provider import LocalComfyUIImageProvider

        if not comfyui_client.is_configured():
            raise GenerationNotConfigured(
                "COMFYUI_ENDPOINT is not configured — draft mode requires a local "
                "ComfyUI instance. See SETUP_NOTES.md for how to install and run one."
            )
        image_provider = LocalComfyUIImageProvider()
        submitted = image_provider.submit(
            shot,
            instructions=str(payload.get("instructions", "")),
            model=str(payload.get("local_model") or "sdxl"),
        )
        task_id = submitted["task_id"]
        task = _wait_for_image_task(
            lambda: image_provider.check_task(task_id, shot_id=job["shot_id"]),
            provider_label="local_comfyui_image",
        )
        skip_validation = True  # already validated as a real image on write, see validate_and_store_upload
    else:
        submitted = submit_magnific_image(
            shot,
            instructions=str(payload.get("instructions", "")),
            aspect_ratio=str(payload.get("aspect_ratio", "16:9")),
        )
        task_id = submitted["task_id"]
        task = _wait_for_image_task(lambda: get_magnific_image(task_id), provider_label="Magnific")
        skip_validation = False

    if any(task.get("has_nsfw", [])):
        raise ValueError("Magnific חסם את התוצאה בבדיקת התוכן.")
    generated = task.get("generated") or []
    if not generated:
        raise RuntimeError(f"{submitted.get('provider', 'Provider')} completed without an image result.")

    image_url = generated[0]
    if not skip_validation:
        validate_generated_image(image_url)
    media = shots.create_media_result(job["shot_id"], {
        "media_type": "image",
        "url": image_url,
        "provider": submitted.get("provider", "Magnific"),
        "model": submitted.get("model", "Nano Banana Pro"),
        "prompt_version_id": payload.get("prompt_version_id"),
        "status": "טיוטה",
        "metadata": {
            "magnific_task_id": task_id,
            "media_job_id": job["id"],
            "idempotency_key": job["idempotency_key"],
        },
    })
    shots.update_shot(job["shot_id"], {"status": "תמונת טיוטה"})
    return {
        "media_result_id": media["id"],
        "url": media["url"],
        "provider_task_id": task_id,
    }


def _approved_image_url(shot_id: int) -> str:
    approved = [
        media for media in shots.list_media_results(shot_id)
        if media.get("media_type") == "image" and media.get("status") == "מאושר"
    ]
    if not approved:
        raise ValueError("יש לאשר תמונת שוט לפני יצירת וידאו.")
    return approved[0]["url"]


def _submit_or_resume_task(provider, request: VideoGenerationRequest, job: dict) -> str:
    """Return the provider task id for this job, submitting at most once.

    Works for any provider that implements the non-blocking submit()/
    check_task() contract (Kling, Seedance). If the job already carries a
    persisted ``provider_task_id`` (a prior attempt submitted before the
    worker was interrupted), that task is resumed and no new submission is
    made — this is what keeps a retry or a worker restart from creating a
    second, separately billed provider job. A fresh submission is persisted
    immediately, before any polling, so the task id survives a crash in the
    very next instant.
    """
    existing_task_id = str(job.get("provider_task_id") or "").strip()
    if existing_task_id:
        return existing_task_id
    task_id = provider.submit(request)
    jobs.record_provider_task_id(job["id"], task_id)
    return task_id


def _resolve_model_and_cost(provider, request: VideoGenerationRequest) -> tuple[str, float]:
    """Resolve the model id and estimated cost for a resumable provider.

    Providers that expose ``model_for``/``cost_for`` (Seedance) are asked
    directly. Kling predates that convention and resolves its model/cost via
    module-level helpers instead of instance methods.
    """
    if hasattr(provider, "model_for") and hasattr(provider, "cost_for"):
        return provider.model_for(request), provider.cost_for(request)
    from app.services.kling_provider import _model_for, _estimate_cost

    model = _model_for(request.model_profile)
    return model, _estimate_cost(request.duration_seconds, model)


def _process_video_job(job: dict) -> dict:
    shot = shots.get_shot(job["shot_id"])
    if not shot:
        raise ValueError("השוט של משימת הווידאו לא נמצא.")
    payload = job.get("payload") or {}
    selection = select_video_model(shot, payload)
    request = VideoGenerationRequest(
        image_url=_approved_image_url(job["shot_id"]),
        prompt=str(payload.get("prompt") or shot.get("prompt") or ""),
        duration_seconds=float(payload.get("duration_seconds") or shot.get("duration_seconds") or 5),
        camera_motion=str(payload.get("camera_motion") or shot.get("movement") or ""),
        audio_mode=str(payload.get("audio_mode") or "none"),
        aspect_ratio=str(payload.get("aspect_ratio") or "16:9"),
        model_profile=selection.profile,
        local_model=str(payload.get("local_model") or "wan"),
    )

    provider = get_video_provider(draft_mode=bool(payload.get("draft_mode")))

    if hasattr(provider, "submit") and hasattr(provider, "check_task"):
        # Any provider implementing the non-blocking submit()/check_task()
        # contract goes through the resumable path: the task id is
        # persisted before polling so a crash/retry never resubmits.
        task_id = _submit_or_resume_task(provider, request, job)
        provider_video_url = _wait_for_provider_task(provider, task_id)
        model, cost = _resolve_model_and_cost(provider, request)
        # The browser must never depend on the provider's own video URL for
        # playback (it can be blocked by network filtering, or expire) — the
        # generation itself is already paid for and complete at this point,
        # so a persistence failure here is retryable purely as a re-download,
        # never as a reason to resubmit to the provider (see
        # _submit_or_resume_task: provider_task_id is already persisted).
        persisted = persist_remote_video(
            provider_video_url,
            job["shot_id"],
            allow_private_host=bool(getattr(provider, "trusted_local", False)),
        )
        result = VideoGenerationResult(
            url=persisted["url"],
            provider=getattr(provider, "name", ""),
            model=model,
            external_task_id=task_id,
            actual_cost_usd=cost,
        )
    else:
        result = provider.generate(request)

    final_url = _maybe_apply_sync(result.url, payload, job=job)

    media = shots.create_media_result(job["shot_id"], {
        "media_type": "video",
        "url": final_url,
        "provider": result.provider,
        "model": result.model,
        "prompt_version_id": payload.get("prompt_version_id"),
        "status": "טיוטה",
        "metadata": {
            "provider_task_id": result.external_task_id,
            "media_job_id": job["id"],
            "idempotency_key": job["idempotency_key"],
            "model_profile": selection.profile,
            "model_selection_reason": selection.reason,
            "sync_applied": final_url != result.url,
        },
    })
    shots.update_shot(job["shot_id"], {"status": "וידאו טיוטה"})
    return {
        "media_result_id": media["id"],
        "url": media["url"],
        "provider_task_id": result.external_task_id,
        "actual_cost_usd": result.actual_cost_usd,
        "model_profile": selection.profile,
        "model_selection_reason": selection.reason,
    }


def process_one_job(worker_id: str | None = None) -> dict | None:
    job = jobs.claim_next_job(worker_id or _worker_id())
    if not job:
        return None

    try:
        if job["job_type"] == "image":
            result = _process_image_job(job)
        elif job["job_type"] == "video":
            result = _process_video_job(job)
        else:
            raise ValueError(f"Unsupported media job type: {job['job_type']}")
        return jobs.complete_job(
            job["id"],
            result,
            float(result.get("actual_cost_usd", 0)),
        )
    except (GenerationNotConfigured, VideoProviderNotConfigured, ValueError) as exc:
        return jobs.fail_job(job["id"], str(exc), retryable=False)
    except (TimeoutError, ConnectionError) as exc:
        return jobs.fail_job(job["id"], str(exc), retryable=True)
    except Exception as exc:
        # ProviderTaskFailed / SeedanceProviderError carry a stable .retryable
        # verdict (e.g. authentication_failed and moderation_rejected must not
        # retry); anything else defaults to retryable, unchanged from before.
        retryable = bool(getattr(exc, "retryable", True))
        return jobs.fail_job(job["id"], str(exc), retryable=retryable)


def run_forever() -> None:
    worker_id = _worker_id()
    # On startup requeue anything a previous worker left mid-flight so it can
    # be resumed (via the persisted provider_task_id) instead of stalling in
    # 'running' forever.
    jobs.reclaim_stale_jobs()
    while True:
        processed = process_one_job(worker_id)
        if processed is None:
            # Idle: also sweep for jobs a crashed sibling worker abandoned.
            jobs.reclaim_stale_jobs()
            time.sleep(IDLE_SLEEP_SECONDS)


if __name__ == "__main__":
    run_forever()
