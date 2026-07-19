from fastapi import APIRouter, HTTPException

from app.models.schemas import SceneAssetVariantUpsert
from app.repositories import scene_asset_variants as repo
from app.repositories import scenes as scene_repo


router = APIRouter(prefix="/api/scenes", tags=["scene asset variants"])


@router.get("/{scene_id}/asset-variants")
def list_scene_asset_variants(scene_id: int):
    if not scene_repo.get_scene(scene_id):
        raise HTTPException(404, "הסצנה לא נמצאה.")
    return repo.list_scene_variants(scene_id)


@router.put("/{scene_id}/asset-variants/{asset_id}")
def upsert_scene_asset_variant(scene_id: int, asset_id: int, request: SceneAssetVariantUpsert):
    try:
        variant = repo.upsert_scene_variant(scene_id, asset_id, request.model_dump())
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not variant:
        raise HTTPException(404, "הסצנה לא נמצאה.")
    return variant
