import json

from app.core.config import settings
from app.services.generation import GenerationNotConfigured, _openai_client


def breakdown_screenplay(project: dict, screenplay: str, target_shots_per_minute: float = 5.0) -> list[dict]:
    if not settings.openai_api_key:
        raise GenerationNotConfigured("OPENAI_API_KEY אינו מוגדר.")
    if not screenplay.strip():
        raise ValueError("התסריט ריק.")

    prompt = f"""You are a senior film editor and production breakdown supervisor.
Return ONLY valid JSON: an array of scene objects covering the ENTIRE screenplay in order.
Do not cap the result at 20 scenes or 20 shots.

Each scene object must contain:
scene_number, title, story_goal, emotion, conflict, beginning, ending, notes,
estimated_duration_seconds, recommended_shot_count.

Rules:
- Detect scene boundaries from headings, location/time changes, and dramatic beats.
- Preserve every meaningful part of the screenplay; do not summarize away scenes.
- recommended_shot_count must be between 1 and 60 and should reflect action, dialogue,
  pacing, coverage and an average target of about {target_shots_per_minute} shots per minute.
- estimated_duration_seconds must be realistic and at least 5.
- Output Hebrew fields in Hebrew when the screenplay is Hebrew.

PROJECT: {json.dumps(project, ensure_ascii=False)}
SCREENPLAY:\n{screenplay}
"""
    response = _openai_client().responses.create(model=settings.openai_text_model, input=prompt)
    raw = (response.output_text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    scenes = json.loads(raw)
    if not isinstance(scenes, list) or not scenes:
        raise RuntimeError("OpenAI לא החזיר פירוק סצנות תקין.")

    normalized = []
    for index, scene in enumerate(scenes, 1):
        shot_count = max(1, min(60, int(scene.get("recommended_shot_count") or 6)))
        normalized.append({
            "scene_number": index,
            "title": str(scene.get("title") or f"סצנה {index}")[:300],
            "status": "מתוכנן",
            "story_goal": str(scene.get("story_goal") or ""),
            "emotion": str(scene.get("emotion") or ""),
            "conflict": str(scene.get("conflict") or ""),
            "beginning": str(scene.get("beginning") or ""),
            "ending": str(scene.get("ending") or ""),
            "notes": str(scene.get("notes") or ""),
            "estimated_duration_seconds": max(5, float(scene.get("estimated_duration_seconds") or 60)),
            "recommended_shot_count": shot_count,
        })
    return normalized
