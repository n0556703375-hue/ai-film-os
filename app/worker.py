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
IDLE_SLEEP_SECONDS = float(os.getenv("MEDIA_WORKER_IDLE_SLEEP", "2"))


def _worker_id() -> str:
    return os.getenv("MEDIA_WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"


def _wait_for_magnific(
    task_id: str,
    *,
    timeout_seconds: float = TASK_TIMEOUT_SECONDS,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        task = get_magnific_image(task_id)
        status = task.get("status", "UNKNOWN")
        if status == "COMPLETED":
            return task
        if status in {"FAILED", "CANCELLED", "ERROR"}:
            raise RuntimeError(f"Magnific task ended with status {status}.")
        sleep(poll_interval)
    raise TimeoutError("Magnific task polling timed out.")


def _wait_for_kling(
    provider,
    task_id: str,
    *,
    timeout_seconds: float = TASK_TIMEOUT_SECONDS,
    poll_interval: float = KLING_POLL_INTERVAL,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Poll provider.check_task() until Kling task succeeds or fails.

    Args:
        provider: KlingProvider instance (has check_task method).
        task_id: Kling task_id returned by provider.submit().
        timeout_seconds: total seconds before TimeoutError.
        poll_interval: seconds between polls.
        sleep: injectable for testing.

    Returns:
        Video URL from Kling CDN.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        sleep(poll_interval)
        status = provider.check_task(task_id)
        if status["status"] == "succeed":
            return status["url"]
        if status["status"] == "failed":
            raise RuntimeError(f"Kling כשל ביצירת הווידאו: {status['reason']}")
    raise TimeoutError(
        f"Kling לא השלים את יצירת הווידאו אחרי {timeout_seconds:.0f} שניות."
    )


def _maybe_apply_sync(
    video_url: str,
    payload: dict,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Apply Sync.so lip-sync when dialogue audio is available and configured.

    Conditions for Sync to run:
      - audio_mode == "dialogue"
      - payload["audio_url"] is a non-empty string
      - SYNC_API_KEY is configured

    A Sync failure is logged as a warning but never cancels the Kling video:
    the original video_url is returned unchanged.

    Returns:
        Lip-synced video URL, or original video_url if Sync is skipped/fails.
    """
    if payload.get("audio_mode") != "dialogue":
        return video_url
    audio_url = str(payload.get("audio_url") or "").strip()
    if not audio_url:
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
    submitted = submit_magnific_image(
        shot,
        instructions=str(payload.get("instructions", "")),
        aspect_ratio=str(payload.get("aspect_ratio", "16:9")),
    )
    task_id = submitted["task_id"]
    task = _wait_for_magnific(task_id)

    if any(task.get("has_nsfw", [])):
        raise ValueError("Magnific חסם את התוצאה בבדיקת התוכן.")
    generated = task.get("generated") or []
    if not generated:
        raise RuntimeError("Magnific completed without an image result.")

    image_url = generated[0]
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
    )

    provider = get_video_provider()

    from app.services.kling_provider import KlingProvider
    if isinstance(provider, KlingProvider):
        task_id = provider.submit(request)
        video_url = _wait_for_kling(provider, task_id)
        from app.services.kling_provider import _model_for, _estimate_cost
        model = _model_for(request.model_profile)
        cost = _estimate_cost(request.duration_seconds, model)
        result = VideoGenerationResult(
            url=video_url,
            provider="kling",
            model=model,
            external_task_id=task_id,
            actual_cost_usd=cost,
        )
    else:
        result = provider.generate(request)

    final_url = _maybe_apply_sync(result.url, payload)

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
        return jobs.fail_job(job["id"], str(exc), retryable=True)


def run_forever() -> None:
    worker_id = _worker_id()
    while True:
        processed = process_one_job(worker_id)
        if processed is None:
            time.sleep(IDLE_SLEEP_SECONDS)


if __name__ == "__main__":
    run_forever()
