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

POLL_INTERVAL_SECONDS = float(os.getenv("MEDIA_WORKER_POLL_INTERVAL", "3"))
TASK_TIMEOUT_SECONDS = float(os.getenv("MEDIA_WORKER_TASK_TIMEOUT", "600"))
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


def process_one_job(worker_id: str | None = None) -> dict | None:
    job = jobs.claim_next_job(worker_id or _worker_id())
    if not job:
        return None

    try:
        if job["job_type"] == "image":
            result = _process_image_job(job)
        else:
            raise ValueError("Video worker is not configured yet.")
        return jobs.complete_job(job["id"], result)
    except (GenerationNotConfigured, ValueError) as exc:
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
