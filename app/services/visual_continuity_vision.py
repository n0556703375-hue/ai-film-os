"""AI-driven visual continuity comparison between two shot frames.

Deliberately mirrors app.services.identity_vision / openai_identity_vision:
same OpenAI Responses API call shape, same Protocol-adapter pattern, so the
rest of the app (worker wiring, config, testing approach) stays consistent.
The difference is what's being judged — here it's wardrobe, lighting and
framing continuity between neighboring shots, not character identity.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from app.core.config import settings

DEFAULT_MIN_CONTINUITY_SCORE = 0.6

VISUAL_CONTINUITY_PROMPT = """Compare two consecutive shots from the same film scene.
Return JSON only with this exact shape:
{
  "continuity_score": 0.0,
  "flags": [],
  "evidence": {
    "summary": "",
    "changed_features": []
  }
}
continuity_score must be a number from 0 to 1, where 1 means fully continuous
(same wardrobe, same lighting setup, compatible framing/eyeline) and 0 means a
jarring, almost certainly unintentional break in continuity.
Allowed flags: wardrobe_changed, lighting_changed, framing_mismatch,
prop_position_changed, time_of_day_mismatch, uncertain_comparison.
Judge continuity only — not image quality, resolution, or artistic style choices
that are clearly deliberate (e.g. a scene transition).
Use uncertain_comparison when the images are not sufficient for a confident judgment.
"""


class VisualContinuityAdapter(Protocol):
    """Provider adapter that compares two shot frames for continuity."""

    def compare_continuity(self, *, current_url: str, neighbor_url: str) -> dict[str, Any]:
        """Return continuity_score, optional flags, evidence, provider and model."""


class OpenAIVisualContinuityAdapter:
    """OpenAI Responses API adapter for provider-neutral continuity comparison."""

    provider = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        api_base: str | None = None,
        timeout_seconds: float = 45.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.openai_api_key
        self.model = model or settings.openai_vision_model
        self.api_base = (api_base or settings.openai_api_base).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client

    def compare_continuity(self, *, current_url: str, neighbor_url: str) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for visual continuity assessment.")
        if not current_url.strip() or not neighbor_url.strip():
            raise ValueError("current_url and neighbor_url are required.")

        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": VISUAL_CONTINUITY_PROMPT},
                        {"type": "input_image", "image_url": current_url, "detail": "high"},
                        {"type": "input_image", "image_url": neighbor_url, "detail": "high"},
                    ],
                }
            ],
            "text": {"format": {"type": "json_object"}},
        }

        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout_seconds)
        try:
            response = client.post(
                f"{self.api_base}/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        finally:
            if owns_client:
                client.close()

        parsed = self._parse_output(body)
        score = float(parsed["continuity_score"])
        if not 0 <= score <= 1:
            raise ValueError("OpenAI continuity_score must be between 0 and 1.")

        flags = sorted({str(flag).strip() for flag in parsed.get("flags", []) if str(flag).strip()})
        evidence = parsed.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {"raw_evidence": evidence}

        return {
            "continuity_score": score,
            "flags": flags,
            "evidence": evidence,
            "provider": self.provider,
            "model": self.model,
        }

    @staticmethod
    def _parse_output(body: dict[str, Any]) -> dict[str, Any]:
        output_text = body.get("output_text")
        if not output_text:
            for item in body.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text" and content.get("text"):
                        output_text = content["text"]
                        break
                if output_text:
                    break
        if not output_text:
            raise ValueError("OpenAI response did not contain output text.")

        try:
            parsed = json.loads(output_text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("OpenAI continuity response was not valid JSON.") from exc
        if not isinstance(parsed, dict) or "continuity_score" not in parsed:
            raise ValueError("OpenAI continuity response is missing continuity_score.")
        return parsed


_FLAG_LABELS = {
    "wardrobe_changed": "שינוי לבוש",
    "lighting_changed": "שינוי תאורה",
    "framing_mismatch": "אי-התאמת פריימינג",
    "prop_position_changed": "שינוי מיקום אביזר",
    "time_of_day_mismatch": "אי-התאמת שעה ביום",
    "uncertain_comparison": "השוואה לא ודאית",
}


def assess_visual_continuity(
    *,
    current_url: str,
    neighbor_url: str,
    adapter: VisualContinuityAdapter,
    relation: str,
    neighbor_shot_id: int,
    neighbor_shot_number: Any,
    min_continuity_score: float = DEFAULT_MIN_CONTINUITY_SCORE,
) -> list[dict[str, Any]]:
    """Compare one frame pair and return continuity issues in the same shape
    app.services.continuity already produces (severity/category/message/...).

    Pure w.r.t. the database: no writes, no shot lookups — the caller passes
    already-resolved frame URLs and neighbor identifiers.
    """
    raw = adapter.compare_continuity(current_url=current_url, neighbor_url=neighbor_url)
    score = float(raw["continuity_score"])
    flags = list(raw.get("flags") or [])

    if score >= min_continuity_score and not flags:
        return []

    severity = "high" if score < min_continuity_score else "low"
    flag_labels = [_FLAG_LABELS.get(flag, flag) for flag in flags] or ["ירידה בציון הרציפות החזותית"]
    return [{
        "severity": severity,
        "category": "ai_visual_continuity",
        "message": f"בדיקת AI לרציפות חזותית מול שוט {relation}: {', '.join(flag_labels)}.",
        "continuity_score": score,
        "flags": flags,
        "evidence": raw.get("evidence") or {},
        "neighbor_shot_id": neighbor_shot_id,
        "neighbor_shot_number": neighbor_shot_number,
        "relation": relation,
        "provider": raw.get("provider") or "",
        "model": raw.get("model") or "",
    }]
