from fastapi import APIRouter, HTTPException

from app.models.schemas import CharacterReferenceRequest, GenerationRequest
from app.repositories import shots as repo
from app.repositories import assets as asset_repo
from app.services.generation import (
    GenerationNotConfigured,
    get_magnific_image,
    integration_status,
    refine_prompt,
    submit_magnific_image,
    build_character_reference_prompt,
    submit_magnific_reference,
    validate_generated_image,
)

router = APIRouter(prefix="/api/generation", tags=["generation"])

ASPECT_RATIOS = {
    "1024x1024": "1:1",
    "1536x1024": "16:9",
    "1024x1536": "9:16",
}


def _validate_locked_characters(shot: dict) -> None:
    unlocked = [
        asset["name"] for asset in shot.get("assets", [])
        if asset.get("asset_type") == "דמות" and asset.get("lock_status") != "locked"
    ]
    if unlocked:
        raise HTTPException(
            409,
            "לא ניתן ליצור שוט עם דמויות לא נעולות: " + ", ".join(unlocked),
        )


@router.get("/status")
def status():
    return integration_status()

@router.post("/assets/{asset_id}/references")
def generate_asset_reference(asset_id: int, request: CharacterReferenceRequest):
    asset = asset_repo.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "הדמות לא נמצאה.")
    if asset["asset_type"] != "דמות":
        raise HTTPException(400, "יצירת רפרנס זו זמינה כרגע לנכסים מסוג דמות.")
    if asset.get("lock_status") == "locked":
        raise HTTPException(409, "הדמות נעולה. יש לפתוח את הנעילה לפני יצירת רפרנסים חדשים.")
    try:
        prompt = build_character_reference_prompt(asset, request.view_type, request.instructions)
        approved = [item["url"] for item in asset.get("reference_images", []) if item.get("approved")]
        existing = approved or [item["url"] for item in asset.get("reference_images", [])]
        seed_references = [] if request.view_type == "portrait" else existing[:1]
        task = submit_magnific_reference(prompt, seed_references)
        return {**task, "asset_id": asset_id, "view_type": request.view_type}
    except GenerationNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"יצירת רפרנס הדמות נכשלה: {exc}")

@router.get("/assets/{asset_id}/references/{task_id}")
def asset_reference_task(asset_id: int, task_id: str, view_type: str = "portrait", prompt: str = ""):
    asset = asset_repo.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "הדמות לא נמצאה.")
    try:
        task = get_magnific_image(task_id)
        if task["status"] != "COMPLETED":
            return {"status": task["status"], "task_id": task_id}
        if any(task.get("has_nsfw", [])):
            raise HTTPException(422, "Magnific חסם את התוצאה בבדיקת התוכן.")
        if not task.get("generated"):
            raise HTTPException(502, "המשימה הושלמה ללא תמונה.")
        validate_generated_image(task["generated"][0])
        existing = next((r for r in asset.get("reference_images", [])
                         if r.get("metadata", {}).get("magnific_task_id") == task_id), None)
        reference = existing or asset_repo.create_reference_image(asset_id, {
            "view_type": view_type, "url": task["generated"][0], "prompt": prompt,
            "metadata": {"magnific_task_id": task_id},
        })
        return {"status": "COMPLETED", "task_id": task_id, "reference": reference}
    except GenerationNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"בדיקת רפרנס הדמות נכשלה: {exc}")

@router.post("/shots/{shot_id}")
def generate_for_shot(shot_id: int, request: GenerationRequest):
    shot = repo.get_shot(shot_id)
    if not shot:
        raise HTTPException(404, "השוט לא נמצא.")

    try:
        if request.media_type == "text":
            prompt = refine_prompt(shot, request.instructions)
            version_id = repo.save_prompt_version(
                shot_id,
                prompt,
                shot.get("negative_prompt", ""),
                "openai-for-magnific",
            )
            updated = repo.update_shot(
                shot_id,
                {"prompt": prompt, "status": "פרומפט מוכן"},
            )
            return {
                "status": "COMPLETED",
                "media_type": "text",
                "prompt": prompt,
                "prompt_version_id": version_id,
                "shot": updated,
            }

        if request.media_type == "image":
            _validate_locked_characters(shot)
            if not shot.get("prompt"):
                raise HTTPException(
                    400,
                    "יש לבנות או לשפר פרומפט לפני יצירת תמונה.",
                )
            task = submit_magnific_image(
                shot,
                instructions=request.instructions,
                aspect_ratio=ASPECT_RATIOS[request.size],
            )
            return {
                "status": task["status"],
                "media_type": "image",
                "task_id": task["task_id"],
                "provider": task["provider"],
                "model": task["model"],
            }

        raise HTTPException(
            501,
            "חיבור הווידאו יופעל לאחר בחירת מודל וידאו ב־Magnific.",
        )
    except GenerationNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"שירות היצירה נכשל: {exc}")

@router.get("/shots/{shot_id}/magnific/{task_id}")
def magnific_task(shot_id: int, task_id: str):
    shot = repo.get_shot(shot_id)
    if not shot:
        raise HTTPException(404, "השוט לא נמצא.")

    try:
        task = get_magnific_image(task_id)
        if task["status"] != "COMPLETED":
            return {
                "status": task["status"],
                "media_type": "image",
                "task_id": task_id,
            }

        if any(task.get("has_nsfw", [])):
            raise HTTPException(422, "Magnific חסם את התוצאה בבדיקת התוכן.")

        generated = task.get("generated", [])
        if not generated:
            raise HTTPException(502, "המשימה הושלמה ללא קישור לתמונה.")

        existing = next(
            (
                media for media in repo.list_media_results(shot_id)
                if media.get("metadata", {}).get("magnific_task_id") == task_id
            ),
            None,
        )
        if existing:
            media = existing
        else:
            versions = repo.list_prompt_versions(shot_id)
            prompt_version_id = versions[0]["id"] if versions else None
            media = repo.create_media_result(
                shot_id,
                {
                    "media_type": "image",
                    "url": generated[0],
                    "provider": "Magnific",
                    "model": "Nano Banana Pro",
                    "prompt_version_id": prompt_version_id,
                    "status": "טיוטה",
                    "notes": "נוצר אוטומטית ב־Magnific מתוך Shot Workspace",
                    "metadata": {
                        "magnific_task_id": task_id,
                        "has_nsfw": task.get("has_nsfw", []),
                    },
                },
            )
            repo.update_shot(shot_id, {"status": "רפרנס"})

        return {
            "status": "COMPLETED",
            "media_type": "image",
            "task_id": task_id,
            "media": media,
        }
    except GenerationNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"בדיקת משימת Magnific נכשלה: {exc}")


def settings_model() -> str:
    from app.core.config import settings
    return settings.magnific_image_model
