import httpx
from fastapi import APIRouter, HTTPException, Response
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

@router.get("/{asset_id}/references/{reference_id}/image")
def reference_image(asset_id: int, reference_id: int):
    reference = repo.get_reference_image(asset_id, reference_id)
    if not reference:
        raise HTTPException(404, "תמונת הרפרנס לא נמצאה.")
    url = reference["url"]
    if not url.startswith("https://"):
        raise HTTPException(400, "כתובת תמונת הרפרנס אינה מאובטחת.")
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            upstream = client.get(url, headers={"Accept": "image/*", "User-Agent": "AI-Film-OS/1.0"})
        upstream.raise_for_status()
        content_type = upstream.headers.get("content-type", "image/jpeg").split(";")[0]
        if not content_type.startswith("image/"):
            raise HTTPException(502, "מקור הרפרנס לא החזיר קובץ תמונה.")
        return Response(
            content=upstream.content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"טעינת תמונת הרפרנס נכשלה: {exc}")

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
