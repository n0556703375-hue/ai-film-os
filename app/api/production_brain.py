from fastapi import APIRouter, HTTPException

from app.services.production_brain import evaluate_production_snapshot
from app.services.production_snapshot import build_production_snapshot


router = APIRouter(prefix="/api/projects", tags=["production-brain"])


@router.get("/{project_id}/production-snapshot")
def get_production_snapshot(project_id: int):
    snapshot = build_production_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(404, "הפרויקט לא נמצא.")
    return snapshot


@router.get("/{project_id}/production-brain")
def get_production_brain(project_id: int):
    snapshot = build_production_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(404, "הפרויקט לא נמצא.")
    return {
        "snapshot": snapshot,
        "decision": evaluate_production_snapshot(snapshot),
    }
