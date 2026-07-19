from fastapi import APIRouter, HTTPException

from app.models.schemas import GenerationRequest
from app.repositories import shots as repo
from app.services.generation import (
    GenerationNotConfigured,
    get_magnific_image,
    integration_status,
    refine_prompt,
    submit_magnific_image,
)

router = APIRouter(prefix="/api/generation", tags=["generation"])

ASPECT_RATIOS = {
    "1024x1024": "square_1_1",
    "1536x1024": "widescreen_16_9",
    "1024x1536": "portrait_9_16",
}


@router.get("/status")
def status():
    return integration_status()


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
                    "model": f"Mystic/{settings_model()}",
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
