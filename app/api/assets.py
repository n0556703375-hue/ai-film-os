import httpx
from fastapi import APIRouter, HTTPException, Response
from app.models.schemas import AssetCreate, AssetUpdate, AssetLockRequest, ReferenceApprovalRequest
from app.repositories import assets as repo
from app.repositories import projects as project_repo
from app.services.asset_bible import generate_asset_bible
from app.services.generation import GenerationNotConfigured
from app.services.reference_gallery import group_approved_references

router = APIRouter(prefix="/api/assets", tags=["assets"])

_BIBLE_AUTOFILL_ASSET_TYPES = {"דמות", "לוקיישן", "אביזר", "לבוש"}

@router.get("")
def list_assets(project_id: int | None = None):
    return repo.list_assets(project_id)

@router.get("/{asset_id}")
def get_asset(asset_id: int):
    asset = repo.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "הנכס לא נמצא.")
    return asset

@router.get("/{asset_id}/references/grouped")
def grouped_approved_references(asset_id: int):
    asset = repo.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "הנכס לא נמצא.")
    return {
        "asset_id": asset_id,
        "groups": group_approved_references(asset.get("reference_images", [])),
    }

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
        return Response(content=upstream.content, media_type=content_type,
                        headers={"Cache-Control": "public, max-age=3600"})
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
    try:
        asset = repo.update_asset(asset_id, fields)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not asset:
        raise HTTPException(404, "הנכס לא נמצא.")
    return asset

@router.post(
    "/{asset_id}/generate-bible",
    summary="Fill in an asset's Story Bible fields (description, visual rules, prompts) using AI",
    description=(
        "Available for asset_type דמות (character), לוקיישן (location), אביזר (prop) "
        "and לבוש (wardrobe) only. "
        "Overwrites description/visual_rules/master_prompt/negative_prompt — the "
        "caller is expected to warn the user before calling this on an asset that "
        "already has content filled in. Refused (409) on a locked asset, matching "
        "the existing rule that master fields require unlocking first."
    ),
)
def generate_bible(asset_id: int):
    asset = repo.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "הנכס לא נמצא.")
    if asset["asset_type"] not in _BIBLE_AUTOFILL_ASSET_TYPES:
        raise HTTPException(409, "מילוי אוטומטי עם AI זמין לדמויות, לוקיישנים, אביזרים ולבוש בלבד.")
    project = project_repo.get_project(asset["project_id"])
    try:
        fields = generate_asset_bible(asset, project)
        return repo.update_asset(asset_id, fields)
    except GenerationNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"מילוי אוטומטי נכשל: {exc}")

@router.put("/{asset_id}/references/{reference_id}/approval")
def approve_reference(asset_id: int, reference_id: int, request: ReferenceApprovalRequest):
    try:
        reference = repo.set_reference_approval(asset_id, reference_id, request.approved)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not reference:
        raise HTTPException(404, "תמונת הרפרנס לא נמצאה.")
    return reference

@router.post("/{asset_id}/lock")
def lock_asset(asset_id: int, request: AssetLockRequest):
    try:
        asset = repo.lock_asset(asset_id, request.master_reference_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not asset:
        raise HTTPException(404, "הנכס לא נמצא.")
    return asset

@router.post("/{asset_id}/unlock")
def unlock_asset(asset_id: int):
    try:
        asset = repo.unlock_asset(asset_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not asset:
        raise HTTPException(404, "הנכס לא נמצא.")
    return asset

@router.delete("/{asset_id}")
def delete_asset(asset_id: int):
    try:
        deleted = repo.delete_asset(asset_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not deleted:
        raise HTTPException(404, "הנכס לא נמצא.")
    return {"deleted": True}
