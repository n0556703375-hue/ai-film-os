import json
import re
import threading

from openai import APIConnectionError, APITimeoutError, RateLimitError

from app.core.config import settings
from app.services.generation import GenerationNotConfigured, _openai_client

# Keep each provider request comfortably below typical reverse-proxy timeouts.
# Smaller chunks trade a few more requests for a lower risk of a long screenplay
# breakdown returning an HTML timeout page before the API can emit structured JSON.
MAX_CHUNK_CHARACTERS = 3000
# Keep one provider attempt below the production smoke client's 120-second timeout.
# The idempotent process-next caller owns retries, avoiding nested retry amplification.
PROVIDER_TIMEOUT_SECONDS = 90.0
MAX_PROVIDER_ATTEMPTS = 1
TRANSIENT_PROVIDER_ERRORS = (APIConnectionError, APITimeoutError, RateLimitError)

# Maximum concurrent in-flight provider threads. When timed-out daemon threads
# remain alive after their deadline (Python cannot forcibly terminate them once
# blocked in the SDK), this cap bounds the number of leaked threads at any time.
# Calls that cannot acquire a slot fail immediately as APIConnectionError so
# the project-scoped caller can retry the same unchanged chunk safely.
_PROVIDER_SEMAPHORE = threading.Semaphore(4)


def _split_screenplay(screenplay: str, max_characters: int = MAX_CHUNK_CHARACTERS) -> list[str]:
    """Split a long screenplay on paragraph boundaries without dropping content."""
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", screenplay) if item.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for paragraph in paragraphs:
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


def _request_breakdown(prompt: str):
    """Keep each provider call bounded; idempotent callers own retry policy.

    Enforces an independent app-level deadline using daemon threads to ensure
    control returns even if the provider SDK's timeout parameter is unreliable.
    The timeout path raises APITimeoutError, which flows through the retry logic.

    A module-level semaphore caps concurrent in-flight provider threads. Timed-out
    daemon threads cannot be forcibly terminated by Python once they are blocked
    inside the SDK, but the semaphore prevents unbounded accumulation of leaked
    threads. Attempts that cannot acquire a slot fail immediately as
    APIConnectionError (treated as transient) and are consumed by the retry budget.

    Known limitation: Python cannot forcibly terminate a thread already blocked in
    the SDK. The semaphore bounds the count of such threads; it does not eliminate
    them.
    """
    client = _openai_client()
    for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
        try:
            if not _PROVIDER_SEMAPHORE.acquire(blocking=False):
                raise APIConnectionError(
                    request=None,
                    message="Concurrent provider thread capacity exceeded",
                )

            result_container: dict = {}
            exception_container: dict = {}

            def call_provider(
                _result=result_container,
                _exc=exception_container,
            ):
                try:
                    _result['result'] = client.responses.create(
                        model=settings.openai_text_model,
                        input=prompt,
                        timeout=PROVIDER_TIMEOUT_SECONDS,
                    )
                except Exception as e:
                    _exc['exception'] = e
                finally:
                    _PROVIDER_SEMAPHORE.release()

            thread = threading.Thread(
                target=call_provider,
                daemon=True,
                name=f"provider_deadline_attempt_{attempt}",
            )
            thread.start()
            thread.join(timeout=PROVIDER_TIMEOUT_SECONDS)

            if thread.is_alive():
                # Thread is still blocking in the SDK. The semaphore slot will be
                # released by the daemon thread's finally block when the SDK call
                # eventually returns or the process exits. Bounded accumulation is
                # enforced by _PROVIDER_SEMAPHORE's capacity.
                raise APITimeoutError("Provider request exceeded application deadline")

            if exception_container:
                raise exception_container['exception']

            return result_container['result']

        except TRANSIENT_PROVIDER_ERRORS:
            if attempt == MAX_PROVIDER_ATTEMPTS:
                raise


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
    response = _request_breakdown(prompt)
    return _extract_json_array(response.output_text or "")


def _normalize_scenes(scenes: list[dict], *, start_number: int = 1) -> list[dict]:
    """Return deterministic scene metadata independent of provider numbering.

    Providers process screenplay chunks independently and may restart
    ``scene_number`` inside every chunk.  The application owns the global scene
    sequence, so both the one-shot and resumable import paths assign contiguous
    numbers before persistence.
    """
    normalized = []
    for offset, scene in enumerate(scenes):
        scene_number = start_number + offset
        try:
            shot_count = max(1, min(60, int(scene.get("recommended_shot_count") or 6)))
            duration = max(5, float(scene.get("estimated_duration_seconds") or 60))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"OpenAI החזיר נתונים מספריים לא תקינים בסצנה {scene_number}."
            ) from exc
        normalized.append({
            "scene_number": scene_number,
            "title": str(scene.get("title") or f"סצנה {scene_number}")[:300],
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

    return _normalize_scenes(scenes)
