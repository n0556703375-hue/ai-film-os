from fastapi import APIRouter, HTTPException
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
