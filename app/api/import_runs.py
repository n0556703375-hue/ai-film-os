from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repositories import projects as project_repo
from app.services.resumable_screenplay_import import (
    ImportRunState,
    process_next_chunk,
    serialize_state,
)

router = APIRouter(prefix="/api/import-runs", tags=["import-runs"])


class ImportRunStepRequest(BaseModel):
    project_id: int = Field(ge=1)
    screenplay: str = Field(min_length=50, max_length=500000)
    target_shots_per_minute: float = Field(default=5.0, ge=1.0, le=12.0)
    next_chunk_index: int = Field(default=0, ge=0)
    scenes: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)


@router.post("/process-next")
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

    try:
        process_next_chunk(project, state)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            502,
            {
                "message": "פירוק מקטע התסריט נעצר עקב תקלה זמנית.",
                "code": "screenplay_chunk_failure",
                "retryable": True,
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
