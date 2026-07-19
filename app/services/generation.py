import base64
import uuid
from pathlib import Path

from openai import OpenAI

from app.core.config import settings
from app.services.prompt_builder import build_prompt


class GenerationNotConfigured(RuntimeError):
    pass


def integration_status() -> dict:
    configured = bool(settings.openai_api_key)
    return {
        "openai": {
            "configured": configured,
            "text": {
                "enabled": configured,
                "model": settings.openai_text_model,
            },
            "image": {
                "enabled": configured,
                "model": settings.openai_image_model,
            },
            "video": {
                "enabled": False,
                "reason": "video_provider_not_configured",
            },
        }
    }


def _client() -> OpenAI:
    if not settings.openai_api_key:
        raise GenerationNotConfigured(
            "OPENAI_API_KEY אינו מוגדר. יש להוסיף אותו לסודות של סביבת ההפעלה."
        )
    return OpenAI(api_key=settings.openai_api_key)


def refine_prompt(shot: dict, instructions: str = "") -> str:
    source_prompt = shot.get("prompt") or build_prompt(shot)
    request = f"""You are the production prompt specialist for AI Film OS.
Rewrite the source as one precise, production-ready cinematic image prompt.
Preserve every approved character, wardrobe, location and prop rule.
Do not add people, objects, text, logos or story facts that are not supplied.
Return only the final prompt in English.

SOURCE PROMPT:
{source_prompt}

ADDITIONAL DIRECTION:
{instructions or "None"}
"""
    response = _client().responses.create(
        model=settings.openai_text_model,
        input=request,
    )
    result = (response.output_text or "").strip()
    if not result:
        raise RuntimeError("OpenAI החזיר פרומפט ריק.")
    return result


def generate_image(
    shot: dict,
    *,
    instructions: str = "",
    size: str = "1536x1024",
    quality: str = "medium",
) -> dict:
    prompt = shot.get("prompt") or build_prompt(shot)
    if instructions:
        prompt = f"{prompt}\n\nADDITIONAL DIRECTION\n{instructions}"

    result = _client().images.generate(
        model=settings.openai_image_model,
        prompt=prompt,
        size=size,
        quality=quality,
        n=1,
    )
    image_base64 = result.data[0].b64_json
    if not image_base64:
        raise RuntimeError("OpenAI לא החזיר נתוני תמונה.")

    settings.generated_media_path.mkdir(parents=True, exist_ok=True)
    filename = f"shot-{shot['id']}-{uuid.uuid4().hex[:12]}.png"
    target = Path(settings.generated_media_path) / filename
    target.write_bytes(base64.b64decode(image_base64))

    return {
        "url": f"/generated/{filename}",
        "provider": "OpenAI",
        "model": settings.openai_image_model,
        "metadata": {
            "size": size,
            "quality": quality,
            "source": "automatic_generation",
        },
    }
