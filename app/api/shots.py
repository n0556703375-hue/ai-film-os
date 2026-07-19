from fastapi import APIRouter, HTTPException
from app.models.schemas import AssetLinkRequest, MediaResultCreate, ShotCreate, ShotUpdate
from app.repositories import shots as repo
from app.repositories import issues as issue_repo
from app.services.prompt_builder import build_prompt
from app.services.continuity import check_shot_continuity
from app.services.director import run_director

router = APIRouter(prefix="/api/shots", tags=["shots"])

@router.get("")
def list_shots(project_id: int | None = None):
    return repo.list_shots(project_id)

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
