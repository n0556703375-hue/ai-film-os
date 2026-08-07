import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repositories import projects as project_repo
from app.repositories import scenes as scene_repo
from app.services.resumable_screenplay_import import (
    ImportRunState,
    process_next_chunk,
    serialize_state,
)
from app.services.screenplay_breakdown import classify_provider_failure

router = APIRouter(prefix="/api/import-runs", tags=["import-runs"])
logger = logging.getLogger(__name__)


class ImportRunStepRequest(BaseModel):
    project_id: int = Field(ge=1)
    screenplay: str = Field(min_length=50, max_length=500000)
    screenplay_fingerprint: str = Field(default="", max_length=64)
    target_shots_per_minute: float = Field(default=5.0, ge=1.0, le=12.0)
    next_chunk_index: int = Field(default=0, ge=0)
    scenes: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)


class ImportRunPersistRequest(BaseModel):
    project_id: int = Field(ge=1)
    completed: Literal[True]
    scenes: list[dict[str, Any]] = Field(min_length=1, max_length=1000)


def _scene_signature(scene: dict[str, Any]) -> tuple[int, str]:
    try:
        scene_number = int(scene.get("scene_number"))
    except (TypeError, ValueError) as exc:
        raise ValueError("לכל סצנה נדרש מספר סצנה תקין.") from exc
    title = str(scene.get("title") or "").strip()
    if scene_number < 1 or not title:
        raise ValueError("לכל סצנה נדרשים מספר וכותרת תקינים.")
    return scene_number, title


@router.post(
    "/process-next",
    summary="Start or resume a screenplay import (the production entry point)",
    description=(
        "This is the entry point for importing a screenplay: there is no separate "
        "\"start import\" endpoint. Call it first with `next_chunk_index` at its "
        "default of 0 and the full `screenplay` text — that call both starts the "
        "run and processes the first bounded chunk. Each response returns "
        "`screenplay_fingerprint`, `next_chunk_index`, `scenes`, and `completed`; "
        "feed those back into the next call unchanged until `completed` is true. "
        "The endpoint is project-scoped (`project_id`), never persists data, and "
        "is safe to retry — resuming with a changed screenplay is rejected (409) "
        "so a stale retry can never silently overwrite progress. Once `completed` "
        "is true, call POST /api/import-runs/persist with the accumulated `scenes`."
    ),
)
def process_next_import_chunk(request: ImportRunStepRequest):
    project = project_repo.get_project(request.project_id)
    if not project:
        raise HTTPException(404, "הפרויקט לא נמצא.")

    state = ImportRunState(
        project_id=request.project_id,
        screenplay=request.screenplay,
        target_shots_per_minute=request.target_shots_per_minute,
        next_chunk_index=request.next_chunk_index,
        scenes=[dict(item) for item in request.scenes],
    )

    if state.next_chunk_index > state.chunk_count:
        raise HTTPException(409, "מצב הייבוא אינו תואם למספר המקטעים.")
    if state.next_chunk_index > 0:
        if not request.screenplay_fingerprint:
            raise HTTPException(409, "חסר מזהה תסריט להמשך הייבוא.")
        if request.screenplay_fingerprint != state.screenplay_fingerprint:
            raise HTTPException(409, "התסריט השתנה מאז תחילת הייבוא. לא בוצעה כתיבה.")

    try:
        process_next_chunk(project, state)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        failure_category, retryable = classify_provider_failure(exc)
        logger.warning(
            "screenplay chunk failure category=%s retryable=%s",
            failure_category,
            retryable,
        )
        raise HTTPException(
            502,
            {
                "message": "פירוק מקטע התסריט נעצר עקב תקלה זמנית.",
                "code": "screenplay_chunk_failure",
                "failure_category": failure_category,
                "retryable": retryable,
                "next_chunk_index": state.next_chunk_index,
                "chunk_count": state.chunk_count,
            },
        ) from exc

    payload = serialize_state(state)
    payload.update(
        {
            "completed": state.completed,
            "chunk_count": state.chunk_count,
            "processed_chunks": state.next_chunk_index,
            "retryable": not state.completed,
        }
    )
    return payload


@router.post(
    "/persist",
    summary="Persist a completed screenplay breakdown (call only after process-next reports completed)",
    description=(
        "Writes the scenes accumulated by repeated POST /api/import-runs/process-next "
        "calls once that endpoint reports `completed: true`. Project-scoped and "
        "non-destructive: if the project already has scenes, this call only "
        "succeeds when they exactly match the requested breakdown, in which case "
        "it returns `idempotent_replay: true` and creates nothing — it never "
        "replaces or deletes existing scenes. Calling this twice with the same "
        "breakdown is therefore safe and does not increase scene counts."
    ),
)
def persist_completed_import(request: ImportRunPersistRequest):
    if not project_repo.get_project(request.project_id):
        raise HTTPException(404, "הפרויקט לא נמצא.")

    try:
        requested_signatures = [_scene_signature(scene) for scene in request.scenes]
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if len(requested_signatures) != len(set(requested_signatures)):
        raise HTTPException(409, "פירוק התסריט מכיל סצנות כפולות.")

    existing = scene_repo.list_scenes(request.project_id)
    if existing:
        existing_signatures = [_scene_signature(scene) for scene in existing]
        if existing_signatures == requested_signatures:
            return {
                "project_id": request.project_id,
                "persisted": False,
                "idempotent_replay": True,
                "scenes_created": 0,
                "imported_scenes": existing,
            }
        raise HTTPException(
            409,
            "בפרויקט כבר קיימות סצנות שונות. לא בוצעה החלפה או כתיבה נוספת.",
        )

    try:
        created = scene_repo.import_scenes(request.project_id, request.scenes, False)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "project_id": request.project_id,
        "persisted": True,
        "idempotent_replay": False,
        "scenes_created": len(created),
        "imported_scenes": created,
    }
