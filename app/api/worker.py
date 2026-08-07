"""API endpoints for background worker management and debugging."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/worker", tags=["worker"])


@router.get("/status")
def get_worker_status():
    """Get the status of the background worker thread.

    Returns:
        {
            "alive": bool - is the worker thread running?
            "thread_id": int or null - OS thread ID
            "last_job_timestamp": string or null - ISO timestamp of last processed job
            "last_job_shot_id": int or null - shot ID of last processed job
            "jobs_processed": int - total jobs processed by this thread
            "queued_job_count": int - jobs waiting in queue
        }
    """
    from app import background_worker

    return background_worker.get_status()


@router.post("/process-next")
def trigger_next_job():
    """Manually trigger processing of the next queued job.

    Useful for debugging and immediate testing. The background thread
    continues processing independently.

    Returns:
        The result of process_one_job(), or {} if no job was queued.
    """
    from app import background_worker

    return background_worker.process_next_job()
