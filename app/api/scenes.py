from fastapi import APIRouter, HTTPException
from app.models.schemas import SceneCreate, SceneUpdate, ShotMapRequest
from app.repositories import scenes as repo
from app.repositories import assets as asset_repo
from app.repositories import projects as project_repo
from app.repositories import shots as shot_repo
from app.services.generation import GenerationNotConfigured
from app.services.prompt_builder import build_prompt
from app.services.shot_map import generate_shot_map

router = APIRouter(prefix="/api/scenes", tags=["scenes"])

@router.get("")
def list_scenes(project_id: int | None = None):
    return repo.list_scenes(project_id)

@router.post("")
def create_scene(scene: SceneCreate):
    try:
        return repo.create_scene(scene.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@router.get("/{scene_id}")
def get_scene(scene_id: int):
    scene = repo.get_scene(scene_id)
    if not scene:
        raise HTTPException(404, "הסצנה לא נמצאה.")
    return scene

@router.patch("/{scene_id}")
def update_scene(scene_id: int, update: SceneUpdate):
    fields = update.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "לא התקבלו שדות לעדכון.")
    scene = repo.update_scene(scene_id, fields)
    if not scene:
        raise HTTPException(404, "הסצנה לא נמצאה.")
    return scene

@router.post("/{scene_id}/shot-map")
def create_shot_map(scene_id: int, request: ShotMapRequest):
    scene = repo.get_scene(scene_id)
    if not scene:
        raise HTTPException(404, "הסצנה לא נמצאה.")
    project = project_repo.get_project(scene["project_id"])
    assets = [a for a in asset_repo.list_assets(scene["project_id"]) if a["approved"]]
    try:
        generated = generate_shot_map(scene, project, assets, request.shot_count)
        result = repo.create_generated_shots(scene_id, generated, request.replace_existing)
        for item in result["shots"]:
            shot = shot_repo.get_shot(item["id"])
            prompt = build_prompt(shot)
            shot_repo.save_prompt_version(item["id"], prompt, shot.get("negative_prompt", ""), "shot-map")
            shot_repo.update_shot(item["id"], {"prompt": prompt, "status": "פרומפט מוכן"})
        return repo.get_scene(scene_id)
    except GenerationNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"יצירת מפת השוטים נכשלה: {exc}")
