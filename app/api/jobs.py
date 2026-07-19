from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Any, Literal

from app.repositories import jobs as repo

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobCreateRequest(BaseModel):
    project_id: int = Field(ge=1)
    shot_id: int = Field(ge=1)
    job_type: Literal["image", "video"]
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=300)
    max_attempts: int = Field(default=3, ge=1, le=10)
    estimated_cost_usd: float = Field(default=0, ge=0)


class JobFailureRequest(BaseModel):
    error: str = Field(min_length=1, max_length=5000)
    retryable: bool = True


class JobCompleteRequest(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)
    actual_cost_usd: float = Field(default=0, ge=0)


@router.get("")
def list_jobs(project_id: int | None = None, shot_id: int | None = None):
    return repo.list_jobs(project_id, shot_id)


@router.get("/cost-summary")
def cost_summary(project_id: int = Query(ge=1)):
    return repo.get_cost_summary(project_id)


@router.get("/{job_id}")
def get_job(job_id: int):
    job = repo.get_job(job_id)
    if not job:
        raise HTTPException(404, "המשימה לא נמצאה.")
    return job


@router.post("")
def enqueue_job(request: JobCreateRequest):
    try:
        job, created = repo.enqueue_job(
            request.project_id,
            request.shot_id,
            request.job_type,
            request.payload,
            request.idempotency_key,
            request.max_attempts,
            request.estimated_cost_usd,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"created": created, "job": job}


@router.post("/claim")
def claim_job(worker_id: str = "web-worker"):
    return repo.claim_next_job(worker_id) or {"job": None}


@router.post("/{job_id}/complete")
def complete_job(job_id: int, request: JobCompleteRequest):
    try:
        job = repo.complete_job(job_id, request.result, request.actual_cost_usd)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not job:
        raise HTTPException(404, "המשימה לא נמצאה.")
    return job


@router.post("/{job_id}/fail")
def fail_job(job_id: int, request: JobFailureRequest):
    job = repo.fail_job(job_id, request.error, request.retryable)
    if not job:
        raise HTTPException(404, "המשימה לא נמצאה.")
    return job
