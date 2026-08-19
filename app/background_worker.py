"""Background worker threads for processing video generation jobs and AI
identity-drift assessments on Render free tier.

Runs two daemon threads (media generation, identity assessment) inside the
same web process rather than a separate Render worker service — see
tests/test_deployment_persistence_safety.py, which pins render.yaml to a
single service. The two are split across threads (not just interleaved on
one, as before) so a slow/hanging OpenAI Vision call can't delay media
generation jobs behind it in the queue, and vice versa.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.services.identity_worker_runner import process_next_identity_assessment
from app.worker import process_one_job, _worker_id

logger = logging.getLogger(__name__)

_worker_thread: Optional[threading.Thread] = None
_identity_worker_thread: Optional[threading.Thread] = None
_last_job_timestamp: Optional[str] = None
_last_job_shot_id: Optional[int] = None
_jobs_processed_count: int = 0
_identity_assessments_processed_count: int = 0
_thread_lock = threading.Lock()
_stop_event = threading.Event()
_identity_stop_event = threading.Event()


def _process_next_identity_assessment_safely(worker_id: str) -> bool:
    """Best-effort: process one pending identity-drift assessment (image or
    video), if any and if OpenAI is configured. Never raises — a vision
    provider hiccup must not take down the media generation queue this
    shares a thread with. Returns True if an assessment was processed.

    Skipped entirely when OPENAI_API_KEY is unset, rather than attempting
    it and recording a terminal "error" verdict on every pending item —
    that would burn through the queue instead of just leaving it pending
    until a key is eventually configured (see app/services/
    identity_worker_runner.py, which is what actually claims/evaluates).
    """
    if not settings.openai_api_key:
        return False
    try:
        result = process_next_identity_assessment(worker_id=worker_id)
    except Exception as exc:
        logger.exception(f"Identity assessment worker error: {exc}")
        return False
    if result.get("processed"):
        logger.info(
            f"Identity assessment processed (shot_id={result.get('shot_id')}, "
            f"media_id={result.get('media_id')})"
        )
        return True
    return False


def _worker_loop(stop_event: threading.Event) -> None:
    """Main worker loop that runs in a background thread.

    Processes media generation jobs only — identity assessments run on their
    own thread (_identity_worker_loop) so one can't block the other. Exits
    when ``stop_event`` is set (used by ``stop()`` / tests).
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
                continue

            stop_event.wait(2)
        except Exception as exc:
            logger.exception(f"Background worker error: {exc}")
            stop_event.wait(5)


def _identity_worker_loop(stop_event: threading.Event) -> None:
    """Identity-drift assessment loop, on its own thread so a slow or hung
    OpenAI Vision call never delays media generation jobs on the other
    thread. Exits when ``stop_event`` is set (used by ``stop()`` / tests)."""
    global _identity_assessments_processed_count

    worker_id = _worker_id()
    logger.info(f"Identity assessment worker thread started (worker_id={worker_id})")

    while not stop_event.is_set():
        try:
            processed = _process_next_identity_assessment_safely(worker_id)
            if processed:
                with _thread_lock:
                    _identity_assessments_processed_count += 1
                continue
            stop_event.wait(2)
        except Exception as exc:
            logger.exception(f"Identity assessment worker error: {exc}")
            stop_event.wait(5)


def start() -> None:
    """Start the background worker threads on app startup."""
    global _worker_thread, _identity_worker_thread

    with _thread_lock:
        if _worker_thread and _worker_thread.is_alive():
            logger.warning("Background worker thread is already running")
        else:
            _stop_event.clear()
            _worker_thread = threading.Thread(
                target=_worker_loop, args=(_stop_event,), daemon=True
            )
            _worker_thread.start()
            logger.info("Background worker thread started")

        if _identity_worker_thread and _identity_worker_thread.is_alive():
            logger.warning("Identity assessment worker thread is already running")
        else:
            _identity_stop_event.clear()
            _identity_worker_thread = threading.Thread(
                target=_identity_worker_loop, args=(_identity_stop_event,), daemon=True
            )
            _identity_worker_thread.start()
            logger.info("Identity assessment worker thread started")


def stop(timeout: float = 5.0) -> None:
    """Signal both background worker threads to exit and wait for them.

    Intended for tests and clean shutdown; the threads are already daemons
    so process exit does not depend on this being called.
    """
    global _worker_thread, _identity_worker_thread

    with _thread_lock:
        thread = _worker_thread
        identity_thread = _identity_worker_thread
        _stop_event.set()
        _identity_stop_event.set()

    if thread:
        thread.join(timeout=timeout)
    if identity_thread:
        identity_thread.join(timeout=timeout)

    with _thread_lock:
        _worker_thread = None
        _identity_worker_thread = None


def is_alive() -> bool:
    """Check if the media generation worker thread is running."""
    with _thread_lock:
        return _worker_thread is not None and _worker_thread.is_alive()


def is_identity_worker_alive() -> bool:
    """Check if the identity assessment worker thread is running."""
    with _thread_lock:
        return _identity_worker_thread is not None and _identity_worker_thread.is_alive()


def get_status() -> dict:
    """Get the status of the background worker thread."""
    from app.repositories import jobs

    queued_count = sum(
        1 for job in jobs.list_jobs() if job["status"] in ("queued", "retrying")
    )

    with _thread_lock:
        alive = _worker_thread is not None and _worker_thread.is_alive()
        identity_alive = _identity_worker_thread is not None and _identity_worker_thread.is_alive()
        return {
            "alive": alive,
            "thread_id": _worker_thread.ident if _worker_thread else None,
            "last_job_timestamp": _last_job_timestamp,
            "last_job_shot_id": _last_job_shot_id,
            "jobs_processed": _jobs_processed_count,
            "queued_job_count": queued_count,
            "identity_worker_alive": identity_alive,
            "identity_worker_thread_id": _identity_worker_thread.ident if _identity_worker_thread else None,
            "identity_assessments_processed": _identity_assessments_processed_count,
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
