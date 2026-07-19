from fastapi import APIRouter, HTTPException

from app.models.schemas import GenerationRequest
from app.repositories import shots as repo
from app.services.generation import (
    GenerationNotConfigured,
    generate_image,
    integration_status,
    refine_prompt,
)

router = APIRouter(prefix="/api/generation", tags=["generation"])


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
                "openai",
            )
            updated = repo.update_shot(
                shot_id,
                {"prompt": prompt, "status": "פרומפט מוכן"},
            )
            return {
                "status": "completed",
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
            versions = repo.list_prompt_versions(shot_id)
            prompt_version_id = versions[0]["id"] if versions else None
            generated = generate_image(
                shot,
                instructions=request.instructions,
                size=request.size,
                quality=request.quality,
            )
            media = repo.create_media_result(
                shot_id,
                {
                    "media_type": "image",
                    "url": generated["url"],
                    "provider": generated["provider"],
                    "model": generated["model"],
                    "prompt_version_id": prompt_version_id,
                    "status": "טיוטה",
                    "notes": "נוצר אוטומטית מתוך Shot Workspace",
                    "metadata": generated["metadata"],
                },
            )
            repo.update_shot(shot_id, {"status": "רפרנס"})
            return {
                "status": "completed",
                "media_type": "image",
                "media": media,
            }

        raise HTTPException(
            501,
            "חיבור הווידאו יופעל לאחר בחירת ספק וידאו בעל API.",
        )
    except GenerationNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"שירות היצירה נכשל: {exc}")
