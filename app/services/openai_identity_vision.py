from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import settings


IDENTITY_PROMPT = """Compare the same character in two production images.
Return JSON only with this exact shape:
{
  "identity_similarity": 0.0,
  "flags": [],
  "evidence": {
    "summary": "",
    "stable_features": [],
    "changed_features": []
  }
}
identity_similarity must be a number from 0 to 1.
Allowed flags: different_person, face_structure_changed, age_shift,
gender_presentation_changed, hair_changed, makeup_changed, expression_changed,
lighting_or_angle_uncertain.
Judge identity, not image quality, clothing, background, pose, or camera style.
Use lighting_or_angle_uncertain when the images are not sufficient for a confident comparison.
"""


class OpenAIIdentityVisionAdapter:
    """OpenAI Responses API adapter for provider-neutral identity comparison."""

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

    def compare_identity(self, *, reference_url: str, candidate_url: str) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for identity assessment.")
        if not reference_url.strip() or not candidate_url.strip():
            raise ValueError("reference_url and candidate_url are required.")

        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": IDENTITY_PROMPT},
                        {"type": "input_image", "image_url": reference_url, "detail": "high"},
                        {"type": "input_image", "image_url": candidate_url, "detail": "high"},
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
        score = float(parsed["identity_similarity"])
        if not 0 <= score <= 1:
            raise ValueError("OpenAI identity_similarity must be between 0 and 1.")

        flags = sorted({str(flag).strip() for flag in parsed.get("flags", []) if str(flag).strip()})
        evidence = parsed.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {"raw_evidence": evidence}

        return {
            "identity_similarity": score,
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
            raise ValueError("OpenAI identity response was not valid JSON.") from exc
        if not isinstance(parsed, dict) or "identity_similarity" not in parsed:
            raise ValueError("OpenAI identity response is missing identity_similarity.")
        return parsed
