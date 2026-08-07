"""Background worker thread for processing video generation jobs on Render free tier.

Runs the worker loop in a daemon thread so it doesn't block the web server.
This allows video jobs to be processed without a separate worker service.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from app.worker import process_one_job, _worker_id

logger = logging.getLogger(__name__)

_worker_thread: Optional[threading.Thread] = None
_last_job_timestamp: Optional[str] = None
_last_job_shot_id: Optional[int] = None
_jobs_processed_count: int = 0
_thread_lock = threading.Lock()
_stop_event = threading.Event()


def _worker_loop(stop_event: threading.Event) -> None:
    """Main worker loop that runs in a background thread.

    Processes jobs continuously with exception handling to keep the thread
    alive. Exits when ``stop_event`` is set (used by ``stop()`` / tests).
    """
    global _last_job_timestamp, _last_job_shot_id, _jobs_processed_count

    worker_id = _worker_id()
    logger.info(f"Background worker thread started (worker_id={worker_id})")

    while not stop_event.is_set():
        try:
            result = process_one_job(worker_id)
            if result:
                with _thread_lock:
                    _last_job_timestamp = datetime.now(timezone.utc).isoformat()
                    _last_job_shot_id = result.get("shot_id")
                    _jobs_processed_count += 1
                logger.info(
                    f"Job processed (job_id={result.get('id')}, "
                    f"shot_id={result.get('shot_id')}, "
                    f"status={result.get('status')})"
                )
            else:
                stop_event.wait(2)
        except Exception as exc:
            logger.exception(f"Background worker error: {exc}")
            stop_event.wait(5)


def start() -> None:
    """Start the background worker thread on app startup."""
    global _worker_thread

    with _thread_lock:
        if _worker_thread and _worker_thread.is_alive():
            logger.warning("Background worker thread is already running")
            return

        _stop_event.clear()
        _worker_thread = threading.Thread(
            target=_worker_loop, args=(_stop_event,), daemon=True
        )
        _worker_thread.start()
        logger.info("Background worker thread started")


def stop(timeout: float = 5.0) -> None:
    """Signal the background worker thread to exit and wait for it.

    Intended for tests and clean shutdown; the thread is already a daemon so
    process exit does not depend on this being called.
    """
    global _worker_thread

    with _thread_lock:
        thread = _worker_thread
        _stop_event.set()

    if thread:
        thread.join(timeout=timeout)

    with _thread_lock:
        _worker_thread = None


def is_alive() -> bool:
    """Check if the background worker thread is running."""
    with _thread_lock:
        return _worker_thread is not None and _worker_thread.is_alive()


def get_status() -> dict:
    """Get the status of the background worker thread."""
    from app.repositories import jobs

    queued_count = sum(
        1 for job in jobs.list_jobs() if job["status"] in ("queued", "retrying")
    )

    with _thread_lock:
        alive = _worker_thread is not None and _worker_thread.is_alive()
        return {
            "alive": alive,
            "thread_id": _worker_thread.ident if _worker_thread else None,
            "last_job_timestamp": _last_job_timestamp,
            "last_job_shot_id": _last_job_shot_id,
            "jobs_processed": _jobs_processed_count,
            "queued_job_count": queued_count,
        }


def process_next_job() -> dict:
    """Process the next queued job (manual trigger for testing/debugging)."""
    worker_id = _worker_id()
    result = process_one_job(worker_id)
    if result:
        with _thread_lock:
            _last_job_timestamp = datetime.now(timezone.utc).isoformat()
            _last_job_shot_id = result.get("shot_id")
    return result or {}
