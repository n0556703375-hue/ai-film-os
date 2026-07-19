import json
import re

from app.core.config import settings
from app.services.generation import GenerationNotConfigured, _openai_client

MAX_CHUNK_CHARACTERS = 12000


def _split_screenplay(screenplay: str, max_characters: int = MAX_CHUNK_CHARACTERS) -> list[str]:
    """Split a long screenplay on paragraph boundaries without dropping content."""
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", screenplay) if item.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for paragraph in paragraphs:
        # Extremely long paragraphs are cut safely so one malformed block cannot
        # force a single oversized provider request.
        pieces = [
            paragraph[index:index + max_characters]
            for index in range(0, len(paragraph), max_characters)
        ] or [paragraph]
        for piece in pieces:
            added_length = len(piece) + (2 if current else 0)
            if current and current_length + added_length > max_characters:
                chunks.append("\n\n".join(current))
                current = []
                current_length = 0
            current.append(piece)
            current_length += len(piece) + (2 if len(current) > 1 else 0)

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _extract_json_array(raw: str) -> list[dict]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end <= start:
            raise RuntimeError("OpenAI החזיר תשובה שאינה JSON תקין.")
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenAI החזיר פירוק סצנות חלקי או קטוע.") from exc

    if not isinstance(parsed, list) or not parsed:
        raise RuntimeError("OpenAI לא החזיר פירוק סצנות תקין.")
    if not all(isinstance(item, dict) for item in parsed):
        raise RuntimeError("OpenAI החזיר מבנה סצנות לא תקין.")
    return parsed


def _breakdown_chunk(
    project: dict,
    chunk: str,
    target_shots_per_minute: float,
    chunk_index: int,
    chunk_count: int,
) -> list[dict]:
    prompt = f"""You are a senior film editor and production breakdown supervisor.
Return ONLY valid JSON: an array of scene objects covering EVERY part of this screenplay segment in order.
This is segment {chunk_index} of {chunk_count}. Do not invent material from other segments and do not omit the end of this segment.

Each scene object must contain:
scene_number, title, story_goal, emotion, conflict, beginning, ending, notes,
estimated_duration_seconds, recommended_shot_count.

Rules:
- Detect scene boundaries from headings, location/time changes, and dramatic beats.
- Preserve every meaningful part; do not summarize away scenes.
- recommended_shot_count must be between 1 and 60 and should reflect action, dialogue,
  pacing, coverage and an average target of about {target_shots_per_minute} shots per minute.
- estimated_duration_seconds must be realistic and at least 5.
- Output Hebrew fields in Hebrew when the screenplay is Hebrew.
- Return a JSON array only. No markdown and no explanation.

PROJECT: {json.dumps(project, ensure_ascii=False)}
SCREENPLAY SEGMENT:\n{chunk}
"""
    response = _openai_client().responses.create(model=settings.openai_text_model, input=prompt)
    return _extract_json_array(response.output_text or "")


def breakdown_screenplay(project: dict, screenplay: str, target_shots_per_minute: float = 5.0) -> list[dict]:
    if not settings.openai_api_key:
        raise GenerationNotConfigured("OPENAI_API_KEY אינו מוגדר.")
    if not screenplay.strip():
        raise ValueError("התסריט ריק.")

    chunks = _split_screenplay(screenplay)
    if not chunks:
        raise ValueError("התסריט ריק.")

    scenes: list[dict] = []
    for index, chunk in enumerate(chunks, 1):
        try:
            scenes.extend(
                _breakdown_chunk(
                    project,
                    chunk,
                    target_shots_per_minute,
                    index,
                    len(chunks),
                )
            )
        except Exception as exc:
            raise RuntimeError(
                f"פירוק התסריט נכשל במקטע {index} מתוך {len(chunks)}: {exc}"
            ) from exc

    normalized = []
    for index, scene in enumerate(scenes, 1):
        try:
            shot_count = max(1, min(60, int(scene.get("recommended_shot_count") or 6)))
            duration = max(5, float(scene.get("estimated_duration_seconds") or 60))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"OpenAI החזיר נתונים מספריים לא תקינים בסצנה {index}.") from exc
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
            "estimated_duration_seconds": duration,
            "recommended_shot_count": shot_count,
        })
    return normalized
