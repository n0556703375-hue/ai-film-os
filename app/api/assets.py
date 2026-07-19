from fastapi import APIRouter, HTTPException
from app.models.schemas import AssetCreate, AssetUpdate
from app.repositories import assets as repo

router = APIRouter(prefix="/api/assets", tags=["assets"])

@router.get("")
def list_assets(project_id: int | None = None):
    return repo.list_assets(project_id)

@router.get("/{asset_id}")
def get_asset(asset_id: int):
    asset = repo.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "הנכס לא נמצא.")
    return asset

@router.post("")
def create_asset(asset: AssetCreate):
    try:
        return repo.create_asset(asset.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@router.patch("/{asset_id}")
def update_asset(asset_id: int, update: AssetUpdate):
    fields = update.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "לא התקבלו שדות לעדכון.")
    asset = repo.update_asset(asset_id, fields)
    if not asset:
        raise HTTPException(404, "הנכס לא נמצא.")
    return asset

@router.delete("/{asset_id}")
def delete_asset(asset_id: int):
    if not repo.delete_asset(asset_id):
        raise HTTPException(404, "הנכס לא נמצא.")
    return {"deleted": True}
