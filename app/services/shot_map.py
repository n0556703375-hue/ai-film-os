import json

from app.core.config import settings
from app.services.generation import GenerationNotConfigured, _openai_client


def generate_shot_map(scene: dict, project: dict, assets: list[dict], shot_count: int) -> list[dict]:
    if not settings.openai_api_key:
        raise GenerationNotConfigured("OPENAI_API_KEY אינו מוגדר.")
    catalog = [{
        "id": a["id"], "type": a["asset_type"], "name": a["name"],
        "description": a.get("description", ""), "visual_rules": a.get("visual_rules", ""),
        "has_reference_image": bool(a.get("reference_url")),
    } for a in assets]
    request = f"""You are a film director creating a production shot map.
Return ONLY valid JSON: an array of exactly {shot_count} objects.
Each object must contain: title, shot_type, duration_seconds, action, camera,
camera_angle, composition, lens, lighting, movement, mood, color_palette,
dialogue, asset_ids. shot_type must be one of: Establishing, Close-up, Medium,
Wide, Insert, POV, Reaction, Transition. asset_ids may only contain catalog IDs.
Link every character, location, prop and wardrobe visible in each shot.
Build a visually varied, coherent sequence with strong continuity.
PROJECT: {json.dumps(project, ensure_ascii=False)}
SCENE: {json.dumps(scene, ensure_ascii=False)}
APPROVED ASSETS: {json.dumps(catalog, ensure_ascii=False)}
"""
    response = _openai_client().responses.create(model=settings.openai_text_model, input=request)
    raw = (response.output_text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    result = json.loads(raw)
    if not isinstance(result, list) or len(result) != shot_count:
        raise RuntimeError("OpenAI לא החזיר מפת שוטים תקינה.")
    return result
