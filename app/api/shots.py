from fastapi import APIRouter, HTTPException
from app.models.schemas import ShotUpdate, AssetLinkRequest
from app.repositories import shots as repo
from app.repositories import issues as issue_repo
from app.services.prompt_builder import build_prompt
from app.services.continuity import check_shot_continuity
from app.services.director import run_director

router = APIRouter(prefix="/api/shots", tags=["shots"])

@router.get("")
def list_shots():
    return repo.list_shots()

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
    shot = repo.update_shot(shot_id, fields)
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
    repo.save_prompt_version(shot_id, prompt)
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
        repo.save_prompt_version(shot_id, result["prompt"])
        repo.update_shot(shot_id, {
            "prompt": result["prompt"],
            "status": "פרומפט מוכן"
        })
    return result
