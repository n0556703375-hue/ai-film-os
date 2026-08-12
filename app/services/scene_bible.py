import json

from app.core.config import settings
from app.services.generation import GenerationNotConfigured, _openai_client

_BIBLE_TEXT_FIELDS = ("story_goal", "emotion", "conflict", "beginning", "ending")
_MIN_SHOT_COUNT = 1
_MAX_SHOT_COUNT = 20
_DEFAULT_SHOT_COUNT = 6


def generate_scene_bible(scene: dict, project: dict) -> dict:
    if not settings.openai_api_key:
        raise GenerationNotConfigured("OPENAI_API_KEY אינו מוגדר.")
    scene_context = {
        "scene_number": scene.get("scene_number"),
        "title": scene.get("title", ""),
        "original_heading": scene.get("original_heading", ""),
        "int_ext": scene.get("int_ext", ""),
        "location": scene.get("location", ""),
        "time_of_day": scene.get("time_of_day", ""),
        "raw_scene_text": scene.get("raw_scene_text", ""),
    }
    request = f"""You are a script analyst preparing a scene bible for production.
Read the screenplay scene text below and return ONLY valid JSON: one object with
exactly these string fields: story_goal (the scene's dramatic purpose — what it
must accomplish in the story), emotion (the scene's central/dominant emotion),
conflict (the scene's central conflict or tension), beginning (the situation/state
at the start of the scene), ending (the situation/state at the end of the scene) —
plus one integer field: recommended_shot_count, between {_MIN_SHOT_COUNT} and
{_MAX_SHOT_COUNT}, reflecting how many distinct camera setups this scene's action,
dialogue exchanges and beats would naturally need in production.
Base every field strictly on the scene text provided — never invent plot details,
character traits, or outcomes that are not present in the text. Write in Hebrew.
Keep each text field to 1-3 concise sentences.
PROJECT: {json.dumps({"name": project.get("name", ""), "description": project.get("description", "")}, ensure_ascii=False)}
SCENE: {json.dumps(scene_context, ensure_ascii=False)}
"""
    response = _openai_client().responses.create(model=settings.openai_text_model, input=request)
    raw = (response.output_text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    result = json.loads(raw)
    if not isinstance(result, dict) or not all(isinstance(result.get(f), str) for f in _BIBLE_TEXT_FIELDS):
        raise RuntimeError("OpenAI לא החזיר Scene Bible תקין.")
    fields = {field: result[field] for field in _BIBLE_TEXT_FIELDS}
    try:
        shot_count = int(result.get("recommended_shot_count", _DEFAULT_SHOT_COUNT))
    except (TypeError, ValueError):
        shot_count = _DEFAULT_SHOT_COUNT
    fields["recommended_shot_count"] = max(_MIN_SHOT_COUNT, min(_MAX_SHOT_COUNT, shot_count))
    return fields
