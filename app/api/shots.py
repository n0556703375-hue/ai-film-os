from fastapi import APIRouter, File, HTTPException, UploadFile
from app.models.schemas import AssetLinkRequest, MediaResultCreate, ShotCreate, ShotUpdate
from app.repositories import assets as assets_repo
from app.repositories import shots as repo
from app.repositories import issues as issue_repo
from app.services.prompt_builder import build_prompt
from app.services.continuity import check_shot_continuity
from app.services.director import run_director
from app.services.media_upload import MediaUploadError, validate_and_store_upload
from app.services.shot_asset_autofill import suggest_shot_asset_ids

router = APIRouter(prefix="/api/shots", tags=["shots"])

@router.get("")
def list_shots(project_id: int | None = None, pipeline_status: str | None = None):
    try:
        return repo.list_shots(project_id, pipeline_status)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@router.post("")
def create_shot(shot: ShotCreate):
    try:
        return repo.create_shot(shot.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@router.get("/{shot_id}")
def get_shot(shot_id: int):
    shot = repo.get_shot(shot_id)
    if not shot:
        raise HTTPException(404, "השוט לא נמצא.")
    return shot

@router.patch("/{shot_id}")
def update_shot(shot_id: int, update: ShotUpdate):
    fields = update.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "לא התקבלו שדות לעדכון.")
    try:
        shot = repo.update_shot(shot_id, fields)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not shot:
        raise HTTPException(404, "השוט לא נמצא.")
    return shot

@router.put("/{shot_id}/assets")
def link_assets(shot_id: int, request: AssetLinkRequest):
    if not repo.get_shot(shot_id):
        raise HTTPException(404, "השוט לא נמצא.")
    try:
        repo.set_shot_assets(shot_id, request.asset_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return repo.get_shot(shot_id)

@router.post("/{shot_id}/assets/autofill")
def autofill_assets(shot_id: int):
    """Suggest and link characters/locations/props/wardrobe whose name
    appears in the shot's own text fields (action, dialogue, camera notes,
    prompt, ...) — additive only, never removes an asset a human already
    linked manually."""
    shot = repo.get_shot(shot_id)
    if not shot:
        raise HTTPException(404, "השוט לא נמצא.")
    project_assets = assets_repo.list_assets(shot["project_id"])
    suggested_ids = suggest_shot_asset_ids(shot, project_assets)
    existing_ids = {asset["id"] for asset in shot["assets"]}
    combined_ids = sorted(existing_ids | set(suggested_ids))
    if combined_ids != sorted(existing_ids):
        repo.set_shot_assets(shot_id, combined_ids)
    added_ids = sorted(set(suggested_ids) - existing_ids)
    return {**repo.get_shot(shot_id), "added_asset_ids": added_ids}

@router.post("/{shot_id}/prompt")
def generate_prompt(shot_id: int):
    shot = repo.get_shot(shot_id)
    if not shot:
        raise HTTPException(404, "השוט לא נמצא.")
    prompt = build_prompt(shot)
    repo.save_prompt_version(shot_id, prompt, shot.get("negative_prompt", ""), "builder")
    repo.update_shot(shot_id, {"prompt": prompt, "status": "פרומפט מוכן"})
    return {"shot_id": shot_id, "prompt": prompt}

@router.post("/{shot_id}/continuity")
def continuity_check(shot_id: int):
    shot = repo.get_shot(shot_id)
    if not shot:
        raise HTTPException(404, "השוט לא נמצא.")
    issues = check_shot_continuity(shot)
    issue_repo.replace_shot_issues(shot_id, issues)
    return {"issues": issues}

@router.post("/{shot_id}/director")
def director(shot_id: int):
    shot = repo.get_shot(shot_id)
    if not shot:
        raise HTTPException(404, "השוט לא נמצא.")
    result = run_director(shot)
    issue_repo.replace_shot_issues(shot_id, result["issues"])
    if result["prompt"]:
        repo.save_prompt_version(
            shot_id, result["prompt"], shot.get("negative_prompt", ""), "director"
        )
        repo.update_shot(shot_id, {
            "prompt": result["prompt"],
            "status": "פרומפט מוכן"
        })
    return result

@router.get("/{shot_id}/prompts")
def prompt_versions(shot_id: int):
    if not repo.get_shot(shot_id):
        raise HTTPException(404, "השוט לא נמצא.")
    return repo.list_prompt_versions(shot_id)

@router.get("/{shot_id}/media")
def media_results(shot_id: int):
    if not repo.get_shot(shot_id):
        raise HTTPException(404, "השוט לא נמצא.")
    return repo.list_media_results(shot_id)

@router.post("/{shot_id}/media")
def create_media_result(shot_id: int, media: MediaResultCreate):
    try:
        result = repo.create_media_result(shot_id, media.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not result:
        raise HTTPException(404, "השוט לא נמצא.")
    return result

@router.post("/{shot_id}/media/upload")
async def upload_media(shot_id: int, file: UploadFile = File(...)):
    """Upload an image file directly from the user's computer.

    This is the primary way to add a shot's source image — the client sends
    the file itself (multipart/form-data), not a URL. The file is validated
    (MIME type, size, and that it actually decodes as an image), stored
    under a fresh UUID filename, and its media_result is created in the same
    request so the frontend doesn't need a second call.
    """
    if not repo.get_shot(shot_id):
        raise HTTPException(404, "השוט לא נמצא.")
    content = await file.read()
    try:
        stored = validate_and_store_upload(shot_id, file.content_type or "", content)
    except MediaUploadError as exc:
        raise HTTPException(400, exc.reason)
    result = repo.create_media_result(shot_id, {
        "media_type": "image",
        "url": stored["url"],
        "provider": "upload",
        "status": "טיוטה",
        "metadata": {
            # Informational only — never used to build a filesystem path.
            "original_filename": (file.filename or "")[:255],
            "size_bytes": stored["size_bytes"],
            "content_type": stored["content_type"],
        },
    })
    if not result:
        raise HTTPException(404, "השוט לא נמצא.")
    return result