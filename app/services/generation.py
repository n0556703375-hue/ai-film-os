import httpx
from openai import OpenAI

from app.core.config import settings
from app.services.prompt_builder import build_prompt


class GenerationNotConfigured(RuntimeError):
    pass


def integration_status() -> dict:
    openai_ready = bool(settings.openai_api_key)
    magnific_ready = bool(settings.magnific_api_key)
    return {
        "openai": {
            "configured": openai_ready,
            "text": {
                "enabled": openai_ready,
                "model": settings.openai_text_model,
            },
        },
        "magnific": {
            "configured": magnific_ready,
            "image": {
                "enabled": magnific_ready,
                "model": settings.magnific_image_model,
                "resolution": settings.magnific_resolution,
            },
            "video": {
                "enabled": False,
                "reason": "video_model_not_selected",
            },
        },
    }


def _openai_client() -> OpenAI:
    if not settings.openai_api_key:
        raise GenerationNotConfigured(
            "OPENAI_API_KEY אינו מוגדר. יש להוסיף אותו לסודות של סביבת ההפעלה."
        )
    return OpenAI(api_key=settings.openai_api_key)


def _magnific_headers() -> dict:
    if not settings.magnific_api_key:
        raise GenerationNotConfigured(
            "MAGNIFIC_API_KEY אינו מוגדר. יש ליצור מפתח API ב־Magnific ולשמור אותו בסודות של Render."
        )
    return {
        "x-magnific-api-key": settings.magnific_api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def refine_prompt(shot: dict, instructions: str = "") -> str:
    source_prompt = shot.get("prompt") or build_prompt(shot)
    request = f"""You are the production prompt specialist for AI Film OS.
Rewrite the source as one precise, production-ready cinematic image prompt for Magnific Nano Banana Pro.
Preserve every approved character, wardrobe, location and prop rule.
Do not add people, objects, text, logos or story facts that are not supplied.
Return only the final prompt in English.

SOURCE PROMPT:
{source_prompt}

ADDITIONAL DIRECTION:
{instructions or "None"}
"""
    response = _openai_client().responses.create(
        model=settings.openai_text_model,
        input=request,
    )
    result = (response.output_text or "").strip()
    if not result:
        raise RuntimeError("OpenAI החזיר פרומפט ריק.")
    return result


def submit_magnific_image(
    shot: dict,
    *,
    instructions: str = "",
    aspect_ratio: str = "16:9",
) -> dict:
    prompt = shot.get("prompt") or build_prompt(shot)
    if instructions:
        prompt = f"{prompt}\n\nADDITIONAL DIRECTION\n{instructions}"

    payload = {
        "prompt": prompt,
        "resolution": settings.magnific_resolution,
        "aspect_ratio": aspect_ratio,
        "reference_images": [],
    }
    with httpx.Client(timeout=45.0) as client:
        response = client.post(
            f"{settings.magnific_api_base}/v1/ai/text-to-image/nano-banana-pro",
            headers=_magnific_headers(),
            json=payload,
        )
    response.raise_for_status()
    data = response.json().get("data", {})
    task_id = data.get("task_id")
    if not task_id:
        raise RuntimeError("Magnific לא החזיר מזהה משימה.")
    return {
        "task_id": task_id,
        "status": data.get("status", "IN_PROGRESS"),
        "generated": data.get("generated", []),
        "provider": "Magnific",
        "model": "Nano Banana Pro",
    }


def get_magnific_image(task_id: str) -> dict:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            f"{settings.magnific_api_base}/v1/ai/text-to-image/nano-banana-pro/{task_id}",
            headers=_magnific_headers(),
        )
    response.raise_for_status()
    data = response.json().get("data", {})
    return {
        "task_id": data.get("task_id", task_id),
        "status": data.get("status", "UNKNOWN"),
        "generated": data.get("generated", []),
        "has_nsfw": data.get("has_nsfw", []),
    }
