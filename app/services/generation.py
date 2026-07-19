import httpx
from io import BytesIO
from PIL import Image, ImageStat
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

def build_character_reference_prompt(asset: dict, view_type: str, instructions: str = "") -> str:
    views = {
        "portrait": "clean head-and-shoulders identity portrait, eye-level camera",
        "full_body": "full-body character identity reference, entire figure visible, neutral standing pose",
        "three_quarter": "three-quarter body identity reference, slight 30-degree turn",
    }
    request = f"""Create one precise English image prompt for a film character reference.
The output is an identity reference, not a story scene. Use a simple neutral studio background,
even realistic lighting, natural proportions, no text, no collage and no additional people.
View: {views[view_type]}.
Character name: {asset['name']}
Description: {asset.get('description', '')}
Visual continuity rules: {asset.get('visual_rules', '')}
Master prompt: {asset.get('master_prompt', '')}
Additional direction: {instructions or 'None'}
Return only the final English prompt."""
    response = _openai_client().responses.create(model=settings.openai_text_model, input=request)
    result = (response.output_text or "").strip()
    if not result:
        raise RuntimeError("OpenAI החזיר פרומפט דמות ריק.")
    return result

def submit_magnific_reference(prompt: str, reference_images: list[str] | None = None) -> dict:
    payload = {
        "prompt": prompt,
        "resolution": settings.magnific_resolution,
        "aspect_ratio": "3:4",
        "reference_images": (reference_images or [])[:14],
    }
    with httpx.Client(timeout=45.0) as client:
        response = client.post(
            f"{settings.magnific_api_base}/v1/ai/text-to-image/nano-banana-pro",
            headers=_magnific_headers(), json=payload,
        )
    response.raise_for_status()
    data = response.json().get("data", {})
    if not data.get("task_id"):
        raise RuntimeError("Magnific לא החזיר מזהה משימה.")
    return {"task_id": data["task_id"], "status": data.get("status", "IN_PROGRESS"),
            "prompt": prompt, "provider": "Magnific", "model": "Nano Banana Pro"}


def submit_magnific_image(
    shot: dict,
    *,
    instructions: str = "",
    aspect_ratio: str = "16:9",
) -> dict:
    prompt = shot.get("prompt") or build_prompt(shot)
    if instructions:
        prompt = f"{prompt}\n\nADDITIONAL DIRECTION\n{instructions}"

    reference_images = []
    for asset in shot.get("assets", []):
        urls = asset.get("reference_images") or [asset.get("reference_url", "")]
        for candidate in urls[:1]:
            url = (candidate or "").strip()
            if url and url not in reference_images:
                reference_images.append(url)
    payload = {
        "prompt": prompt,
        "resolution": settings.magnific_resolution,
        "aspect_ratio": aspect_ratio,
        "reference_images": reference_images[:14],
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

def validate_generated_image(url: str) -> None:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url, headers={"Accept": "image/*", "User-Agent": "AI-Film-OS/1.0"})
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").split(";")[0]
    if content_type and not content_type.startswith("image/"):
        raise RuntimeError("Magnific החזיר קישור שאינו קובץ תמונה.")
    try:
        image = Image.open(BytesIO(response.content)).convert("RGB")
        image.thumbnail((256, 256))
        stat = ImageStat.Stat(image)
    except Exception as exc:
        raise RuntimeError("קובץ התוצאה של Magnific אינו תמונה תקינה.") from exc
    if image.width < 64 or image.height < 64:
        raise RuntimeError("Magnific החזיר תמונה קטנה או ריקה.")
    nearly_white = all(mean > 247 for mean in stat.mean) and all(value < 4 for value in stat.var)
    if nearly_white:
        raise RuntimeError("Magnific החזיר תמונה לבנה. יש ליצור את הרפרנס מחדש.")
