from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    BatchApprovalRequest,
    BatchFinalizePreviewRequest,
    BatchFinalizeRequest,
    MediaDecisionRequest,
    ShotFinalizeRequest,
)
from app.repositories import approvals as repo
from app.repositories import batch_approvals as batch_repo

router = APIRouter(prefix="/api/shots", tags=["approvals"])


@router.post("/batch/approval")
def batch_approval(request: BatchApprovalRequest):
    return batch_repo.batch_approval(
        action=request.action,
        items=[item.model_dump() for item in request.items],
        project_id=request.project_id,
        notes=request.notes,
    )


@router.post("/batch/finalize-preview")
def preview_batch_finalize(request: BatchFinalizePreviewRequest):
    return repo.preview_batch_finalize(request.shot_ids, request.project_id)


@router.post("/batch/finalize")
def finalize_batch(request: BatchFinalizeRequest):
    return repo.finalize_batch(request.shot_ids, request.project_id, request.notes)


@router.get("/{shot_id}/pipeline")
def get_pipeline(shot_id: int):
    pipeline = repo.get_pipeline(shot_id)
    if not pipeline:
        raise HTTPException(404, "השוט לא נמצא.")
    return pipeline


@router.post("/{shot_id}/media/{media_id}/decision")
def decide_media(shot_id: int, media_id: int, request: MediaDecisionRequest):
    try:
        pipeline = repo.decide_media(
            shot_id, media_id, request.decision, request.project_id, request.notes
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not pipeline:
        raise HTTPException(404, "השוט לא נמצא בפרויקט שנבחר.")
    return pipeline


@router.post("/{shot_id}/finalize")
def finalize_shot(shot_id: int, request: ShotFinalizeRequest):
    try:
        pipeline = repo.finalize_shot(shot_id, request.project_id, request.notes)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not pipeline:
        raise HTTPException(404, "השוט לא נמצא בפרויקט שנבחר.")
    return pipeline
