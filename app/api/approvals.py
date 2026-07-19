from fastapi import APIRouter, HTTPException

from app.models.schemas import MediaDecisionRequest, ShotFinalizeRequest
from app.repositories import approvals as repo

router = APIRouter(prefix="/api/shots", tags=["approvals"])


@router.get("/{shot_id}/pipeline")
def get_pipeline(shot_id: int):
    pipeline = repo.get_pipeline(shot_id)
    if not pipeline:
        raise HTTPException(404, "השוט לא נמצא.")
    return pipeline


@router.post("/{shot_id}/media/{media_id}/decision")
def decide_media(shot_id: int, media_id: int, request: MediaDecisionRequest):
    try:
        pipeline = repo.decide_media(shot_id, media_id, request.decision, request.notes)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not pipeline:
        raise HTTPException(404, "השוט לא נמצא.")
    return pipeline


@router.post("/{shot_id}/finalize")
def finalize_shot(shot_id: int, request: ShotFinalizeRequest):
    try:
        pipeline = repo.finalize_shot(shot_id, request.notes)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not pipeline:
        raise HTTPException(404, "השוט לא נמצא.")
    return pipeline
