from fastapi import APIRouter, HTTPException
from app.models.schemas import SceneUpdate
from app.repositories import scenes as repo

router = APIRouter(prefix="/api/scenes", tags=["scenes"])

@router.get("")
def list_scenes():
    return repo.list_scenes()

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
