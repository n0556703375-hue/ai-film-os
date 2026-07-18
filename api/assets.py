from fastapi import APIRouter
from app.models.schemas import AssetCreate
from app.repositories import assets as repo

router = APIRouter(prefix="/api/assets", tags=["assets"])

@router.get("")
def list_assets():
    return repo.list_assets()

@router.post("")
def create_asset(asset: AssetCreate):
    return repo.create_asset(asset.model_dump())
