import json

from app.core.config import settings
from app.services.generation import GenerationNotConfigured, _openai_client

_BIBLE_TEXT_FIELDS = ("description", "visual_rules", "master_prompt", "negative_prompt")

_ASSET_TYPE_LABELS = {
    "דמות": "a character",
    "לוקיישן": "a filming location",
    "אביזר": "a prop",
    "לבוש": "a wardrobe/costume piece",
}


def generate_asset_bible(asset: dict, project: dict) -> dict:
    if not settings.openai_api_key:
        raise GenerationNotConfigured("OPENAI_API_KEY אינו מוגדר.")
    asset_type = asset.get("asset_type", "")
    subject = _ASSET_TYPE_LABELS.get(asset_type, "a production asset")
    asset_context = {
        "asset_type": asset_type,
        "name": asset.get("name", ""),
        "description": asset.get("description", ""),
        "visual_rules": asset.get("visual_rules", ""),
        "master_prompt": asset.get("master_prompt", ""),
    }
    project_context = {
        "name": project.get("name", ""),
        "description": project.get("description", ""),
        "visual_style": project.get("visual_style", ""),
        "rules": project.get("rules", ""),
    }
    request = f"""You are a production designer building a Story Bible entry for {subject} in a film.
Return ONLY valid JSON: one object with exactly these string fields:
description (a concise 2-4 sentence description of its appearance and character/atmosphere, in Hebrew),
visual_rules (specific visual continuity rules to keep it consistent across shots, in Hebrew),
master_prompt (a detailed English text-to-image prompt describing it for AI image generation),
negative_prompt (an English negative prompt listing things to avoid generating).
Ground your answer in the project's visual style and any existing notes given below. If a field
already has content, refine and expand it rather than contradicting it — never discard an existing
detail. It is expected and appropriate to invent plausible creative details consistent with the
project's style, since these fields describe a fictional creative asset, not a real document.
PROJECT: {json.dumps(project_context, ensure_ascii=False)}
ASSET: {json.dumps(asset_context, ensure_ascii=False)}
"""
    response = _openai_client().responses.create(model=settings.openai_text_model, input=request)
    raw = (response.output_text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    result = json.loads(raw)
    if not isinstance(result, dict) or not all(isinstance(result.get(f), str) for f in _BIBLE_TEXT_FIELDS):
        raise RuntimeError("OpenAI לא החזיר Story Bible תקין.")
    return {field: result[field] for field in _BIBLE_TEXT_FIELDS}
