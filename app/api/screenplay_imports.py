"""Two-stage screenplay import API: parse -> preview -> review -> approve.

This is deliberately a separate router/prefix from app/api/import_runs.py
(the older LLM-chunked resumable import, still in place for the existing
smoke-tested flow). This router is the new deterministic-parser flow:

  POST   /api/screenplay-imports                -> create a preview (no production writes)
  POST   /api/screenplay-imports/upload-chunk    -> same, in small pieces (network-filter workaround)
  GET    /api/screenplay-imports?project_id=..   -> list a project's import runs
  GET    /api/screenplay-imports/{id}            -> fetch one run's full structured preview
  POST   /api/screenplay-imports/{id}/reparse    -> re-parse (optionally with edited text)
  POST   /api/screenplay-imports/{id}/entities/{type}/rename -> rename/merge a character/location/prop
  POST   /api/screenplay-imports/{id}/entities/{type}/delete -> remove a character/location/prop
  GET    /api/screenplay-imports/{id}/diff       -> preview vs. the project's current scenes
  POST   /api/screenplay-imports/{id}/approve    -> atomically commit to production tables

Every error surfaced to the client carries a stable `code` (an error
category from the product spec) and a Hebrew `message` — raw exception
text and provider/model internals are never returned.
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repositories import import_runs as import_runs_repo
from app.repositories import projects as project_repo
from app.services import chunked_screenplay_upload as chunk_service
from app.services import screenplay_import_service as import_service

router = APIRouter(prefix="/api/screenplay-imports", tags=["screenplay-imports"])
logger = logging.getLogger(__name__)

_CATEGORY_STATUS = {
    "invalid_file": 422,
    "unsupported_format": 422,
    "empty_script": 422,
    "text_extraction_failed": 422,
    "scene_detection_failed": 422,
    "model_parse_failed": 422,
    "schema_validation_failed": 422,
    "duplicate_import": 409,
    "import_conflict": 409,
    "database_write_failed": 500,
    "chunk_too_large": 409,
    "too_many_chunks": 409,
    "upload_mismatch": 409,
}

_CATEGORY_MESSAGES = {
    "invalid_file": "הקובץ שהועלה אינו תקין.",
    "unsupported_format": "פורמט הקובץ אינו נתמך.",
    "empty_script": "התסריט ריק או קצר מדי לניתוח.",
    "text_extraction_failed": "לא ניתן היה לחלץ טקסט מהקובץ.",
    "scene_detection_failed": "לא זוהו סצנות תקינות בתסריט. יש לבדוק את מבנה כותרות הסצנות.",
    "model_parse_failed": "ניתוח התסריט נכשל עקב תקלה זמנית. ניתן לנסות שוב.",
    "schema_validation_failed": "מבנה הפירוק שהתקבל אינו תקין.",
    "duplicate_import": "התסריט הזה כבר יובא ואושר בעבר בפרויקט.",
    "import_conflict": "הייבוא מתנגש עם נתוני הפקה קיימים ודורש אישור מפורש.",
    "database_write_failed": "שמירת הפירוק נכשלה עקב תקלה במסד הנתונים. ניתן לנסות שוב.",
    "chunk_too_large": "אחד ממקטעי ההעלאה גדול מדי.",
    "too_many_chunks": "ההעלאה מכילה יותר מדי מקטעים.",
    "upload_mismatch": "ההעלאה המקוטעת אינה עקבית. יש להתחיל את הניתוח מחדש.",
}


def _error_response(category: str) -> HTTPException:
    status = _CATEGORY_STATUS.get(category, 422)
    message = _CATEGORY_MESSAGES.get(category, "אירעה שגיאה בעיבוד התסריט.")
    return HTTPException(status, {"message": message, "code": category})


class CreateImportRunRequest(BaseModel):
    project_id: int = Field(ge=1)
    screenplay_text: str = Field(min_length=1, max_length=1_000_000)
    source_type: str = Field(default="paste", max_length=20)
    source_filename: str = Field(default="", max_length=255)
    force: bool = False


class ReparseRequest(BaseModel):
    screenplay_text: str | None = Field(default=None, max_length=1_000_000)


class ApproveRequest(BaseModel):
    confirm: bool = False


class RenameEntityRequest(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=300)
    new_name: str = Field(min_length=1, max_length=300)


class DeleteEntityRequest(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=300)


class UploadChunkRequest(BaseModel):
    upload_id: str = Field(min_length=8, max_length=64)
    chunk_text: str = Field(max_length=chunk_service.MAX_CHUNK_CHARS)
    is_final: bool = False
    project_id: int = Field(ge=1)
    source_type: str = Field(default="paste", max_length=20)
    source_filename: str = Field(default="", max_length=255)
    import_run_id: int | None = Field(default=None, ge=1)
    force: bool = False


def _serialize_run_detail(run: dict) -> dict:
    breakdown = run.get("breakdown", {})
    return {
        "id": run["id"],
        "project_id": run["project_id"],
        "status": run["status"],
        "source_type": run["source_type"],
        "source_filename": run["source_filename"],
        "source_hash": run["source_hash"],
        "screenplay_text": run.get("screenplay_text", ""),
        "scene_count": run["scene_count"],
        "character_count": run["character_count"],
        "location_count": run["location_count"],
        "prop_count": run["prop_count"],
        "warnings": run.get("warnings", []),
        "scenes": breakdown.get("scenes", []),
        "characters": breakdown.get("characters", []),
        "locations": breakdown.get("locations", []),
        "props": breakdown.get("props", []),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "approved_at": run.get("approved_at"),
        "duplicate_of_import_run_id": run.get("duplicate_of_import_run_id"),
    }


def _serialize_run_summary(run: dict) -> dict:
    return {
        "id": run["id"],
        "project_id": run["project_id"],
        "status": run["status"],
        "source_type": run["source_type"],
        "source_filename": run["source_filename"],
        "scene_count": run["scene_count"],
        "character_count": run["character_count"],
        "location_count": run["location_count"],
        "prop_count": run["prop_count"],
        "warning_count": len(run.get("warnings", [])),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "approved_at": run.get("approved_at"),
    }


def _serialize_diff(diff: dict) -> dict:
    return {
        "added": diff["added"],
        "changed": [
            {"existing_scene_id": scene_id, "scene": scene}
            for scene_id, scene in diff["changed"]
        ],
        "unchanged": [
            {"existing_scene_id": scene_id, "scene": scene}
            for scene_id, scene in diff["unchanged"]
        ],
        "removed": diff["removed"],
        "has_differences": diff["has_differences"],
        "requires_confirmation": diff["requires_confirmation"],
    }


@router.post(
    "",
    summary="Parse a screenplay and create a reviewable import preview (no production writes)",
    description=(
        "Deterministically parses the screenplay text into scenes, content "
        "blocks, characters and locations and stores the result as a "
        "review_required import run — it never touches scenes/shots/etc. "
        "If a screenplay with the exact same text was already approved for "
        "this project, that approved run is returned unchanged instead "
        "(idempotent — see `duplicate_of_import_run_id`), unless `force` is "
        "true, which always re-parses — the escape hatch for re-checking "
        "already-approved text against a newer parser version."
    ),
)
def create_import_run(request: CreateImportRunRequest):
    if not project_repo.get_project(request.project_id):
        raise HTTPException(404, "הפרויקט לא נמצא.")
    try:
        run = import_service.create_import_run(
            request.project_id,
            request.screenplay_text,
            source_type=request.source_type,
            source_filename=request.source_filename,
            force=request.force,
        )
    except import_service.ScreenplayImportError as exc:
        raise _error_response(exc.category) from exc
    return _serialize_run_detail(run)


@router.post(
    "/upload-chunk",
    summary="Upload one piece of screenplay text (transport workaround for POST-size-limiting networks)",
    description=(
        "Some networks (observed in production: an ISP/organizational "
        "content filter that returns an HTML block page with HTTP 200 for "
        "POST bodies above a certain size) reject the single-shot create/"
        "reparse endpoints for a full-length screenplay. This endpoint "
        "accepts the same screenplay text split into small pieces — "
        "identified by a client-generated `upload_id`, appended in the "
        "order they arrive — and only reassembles them server-side. No "
        "piece is parsed on its own; once a request sets `is_final: true`, "
        "the complete reassembled text is handed to the exact same "
        "deterministic create (or, if `import_run_id` is set, reparse) "
        "flow the single-shot endpoints use. Intermediate responses report "
        "`completed: false`. The final response is deliberately small "
        "(just `import_run_id` and, if applicable, "
        "`duplicate_of_import_run_id`) rather than the full run detail, "
        "since the same network filter can also block on response size — "
        "fetch the full preview separately via GET /api/screenplay-imports/{id}."
    ),
)
def upload_screenplay_chunk(request: UploadChunkRequest):
    if not project_repo.get_project(request.project_id):
        raise HTTPException(404, "הפרויקט לא נמצא.")

    try:
        result = chunk_service.receive_chunk(
            upload_id=request.upload_id,
            chunk_text=request.chunk_text,
            is_final=request.is_final,
            project_id=request.project_id,
            import_run_id=request.import_run_id,
        )
    except chunk_service.ChunkedUploadError as exc:
        raise _error_response(exc.category) from exc

    if not result["completed"]:
        return result

    full_text = result["screenplay_text"]
    try:
        if request.import_run_id:
            run = import_service.reparse_import_run(request.import_run_id, full_text)
        else:
            run = import_service.create_import_run(
                request.project_id, full_text,
                source_type=request.source_type, source_filename=request.source_filename,
                force=request.force,
            )
    except import_service.ImportRunNotFound as exc:
        raise HTTPException(404, "ריצת הייבוא לא נמצאה.") from exc
    except import_service.ImportRunNotEditable as exc:
        raise HTTPException(409, "ריצת הייבוא כבר אושרה ולא ניתן לערוך אותה.") from exc
    except import_service.ScreenplayImportError as exc:
        raise _error_response(exc.category) from exc

    payload = {"completed": True, "import_run_id": run["id"]}
    if run.get("duplicate_of_import_run_id"):
        payload["duplicate_of_import_run_id"] = run["duplicate_of_import_run_id"]
    return payload


@router.get("", summary="List a project's import runs, most recent first")
def list_import_runs(project_id: int):
    if not project_repo.get_project(project_id):
        raise HTTPException(404, "הפרויקט לא נמצא.")
    runs = import_runs_repo.list_import_runs(project_id)
    return {"import_runs": [_serialize_run_summary(run) for run in runs]}


@router.get("/{import_run_id}", summary="Fetch one import run's full structured preview")
def get_import_run(import_run_id: int):
    run = import_runs_repo.get_import_run(import_run_id)
    if not run:
        raise HTTPException(404, "ריצת הייבוא לא נמצאה.")
    return _serialize_run_detail(run)


@router.post(
    "/{import_run_id}/reparse",
    summary="Re-parse an editable import run, optionally with corrected screenplay text",
    description=(
        "Only valid while the run is still review_required/draft (not yet "
        "approved). Omit screenplay_text to re-run the parser on the same "
        "text; pass it to re-parse edited text in place, replacing this "
        "run's preview."
    ),
)
def reparse_import_run(import_run_id: int, request: ReparseRequest):
    try:
        run = import_service.reparse_import_run(import_run_id, request.screenplay_text)
    except import_service.ImportRunNotFound as exc:
        raise HTTPException(404, "ריצת הייבוא לא נמצאה.") from exc
    except import_service.ImportRunNotEditable as exc:
        raise HTTPException(409, "ריצת הייבוא כבר אושרה ולא ניתן לערוך אותה.") from exc
    except import_service.ScreenplayImportError as exc:
        raise _error_response(exc.category) from exc
    return _serialize_run_detail(run)


@router.post(
    "/{import_run_id}/entities/{entity_type}/rename",
    summary="Rename (or merge) one character/location/prop in an editable import run's preview",
    description=(
        "Only valid while the run is still review_required/draft. Renaming "
        "a character keeps the old name as an alias so scene dialogue "
        "recorded under it still resolves correctly at approval time. If "
        "new_name collides with another entity of the same type, the two "
        "are merged instead of producing a duplicate."
    ),
)
def rename_import_run_entity(import_run_id: int, entity_type: str, request: RenameEntityRequest):
    if entity_type not in import_service.ENTITY_TYPES:
        raise HTTPException(404, "סוג ישות לא מוכר.")
    try:
        run = import_service.rename_entity(
            import_run_id, entity_type, request.canonical_name, request.new_name
        )
    except import_service.ImportRunNotFound as exc:
        raise HTTPException(404, "ריצת הייבוא לא נמצאה.") from exc
    except import_service.ImportRunNotEditable as exc:
        raise HTTPException(409, "ריצת הייבוא כבר אושרה ולא ניתן לערוך אותה.") from exc
    except import_service.EntityNotFound as exc:
        raise HTTPException(404, "הישות המבוקשת לא נמצאה בפירוק.") from exc
    return _serialize_run_detail(run)


@router.post(
    "/{import_run_id}/entities/{entity_type}/delete",
    summary="Remove one character/location/prop from an editable import run's preview",
)
def delete_import_run_entity(import_run_id: int, entity_type: str, request: DeleteEntityRequest):
    if entity_type not in import_service.ENTITY_TYPES:
        raise HTTPException(404, "סוג ישות לא מוכר.")
    try:
        run = import_service.delete_entity(import_run_id, entity_type, request.canonical_name)
    except import_service.ImportRunNotFound as exc:
        raise HTTPException(404, "ריצת הייבוא לא נמצאה.") from exc
    except import_service.ImportRunNotEditable as exc:
        raise HTTPException(409, "ריצת הייבוא כבר אושרה ולא ניתן לערוך אותה.") from exc
    except import_service.EntityNotFound as exc:
        raise HTTPException(404, "הישות המבוקשת לא נמצאה בפירוק.") from exc
    return _serialize_run_detail(run)


@router.get(
    "/{import_run_id}/diff",
    summary="Preview how this run's breakdown differs from the project's current scenes",
    description=(
        "Read-only, always safe to call. added/changed/unchanged/removed "
        "scenes are matched by heading first (survives renumbering), scene "
        "number as fallback. `requires_confirmation` is true whenever "
        "approving this run would change or remove an existing scene — "
        "call approve with confirm=true to proceed in that case."
    ),
)
def get_import_run_diff(import_run_id: int):
    try:
        diff = import_service.preview_diff(import_run_id)
    except import_service.ImportRunNotFound as exc:
        raise HTTPException(404, "ריצת הייבוא לא נמצאה.") from exc
    return _serialize_diff(diff)


@router.post(
    "/{import_run_id}/approve",
    summary="Approve an import run and atomically commit its breakdown to production tables",
    description=(
        "The only endpoint in this router that writes to scenes/content "
        "blocks/characters/locations, and does so in a single all-or-"
        "nothing transaction. Pure additions never require confirmation. "
        "Any change or removal of an existing scene requires confirm=true, "
        "returning 409 import_conflict otherwise with the diff attached. "
        "Removing a scene that has shots attached is refused unconditionally "
        "(409 import_conflict, protected_scene_ids), even with confirm=true."
    ),
)
def approve_import_run(import_run_id: int, request: ApproveRequest):
    try:
        summary = import_service.approve_import_run(import_run_id, confirm=request.confirm)
    except import_service.ImportRunNotFound as exc:
        raise HTTPException(404, "ריצת הייבוא לא נמצאה.") from exc
    except import_service.ImportRunNotEditable as exc:
        raise HTTPException(409, "ריצת הייבוא כבר אושרה.") from exc
    except import_service.ImportRunConflict as exc:
        message = (
            "קיימות סצנות שהשתנו או הוסרו בפרויקט. יש לאשר במפורש (confirm) כדי להמשיך."
            if exc.reason == "confirmation_required"
            else "לא ניתן להסיר סצנות שיש להן שוטים קיימים, גם עם אישור מפורש."
        )
        raise HTTPException(
            409,
            {
                "message": message,
                "code": exc.reason,
                "diff": _serialize_diff(exc.diff),
                "protected_scene_ids": exc.protected_scene_ids,
            },
        ) from exc
    except Exception as exc:
        logger.exception("screenplay import commit failed import_run_id=%s", import_run_id)
        raise _error_response("database_write_failed") from exc
    return summary
