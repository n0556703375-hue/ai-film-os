from __future__ import annotations

from typing import Any, Protocol

from app.services.identity_drift import (
    DEFAULT_MIN_IDENTITY_SIMILARITY,
    assess_identity_drift,
)


class IdentityVisionAdapter(Protocol):
    """Provider adapter that compares one locked identity reference to one image."""

    def compare_identity(self, *, reference_url: str, candidate_url: str) -> dict[str, Any]:
        """Return identity_similarity, optional flags, evidence, provider and model."""


def evaluate_shot_identity(
    *,
    shot: dict[str, Any],
    candidate_url: str,
    adapter: IdentityVisionAdapter,
    min_similarity: float = DEFAULT_MIN_IDENTITY_SIMILARITY,
) -> dict[str, Any]:
    """Evaluate a generated shot image against every locked character master.

    This function performs no database writes and does not know provider credentials.
    The caller is responsible for claiming the task and persisting the returned verdict.
    """
    if not candidate_url.strip():
        raise ValueError("candidate_url is required.")

    character_references: list[tuple[str, str]] = []
    for asset in shot.get("assets", []):
        if asset.get("asset_type") != "דמות" or asset.get("lock_status") != "locked":
            continue
        for reference_url in asset.get("reference_images", []):
            if str(reference_url).strip():
                character_references.append((asset.get("name") or f"asset-{asset.get('id')}", reference_url))

    if not character_references:
        return {
            "status": "error",
            "passed": False,
            "identity_similarity": None,
            "min_similarity": min_similarity,
            "flags": [],
            "blocking_flags": [],
            "reasons": ["No locked character master reference is linked to this shot."],
            "evidence": {"comparisons": []},
            "provider": "",
            "model": "",
        }

    comparisons: list[dict[str, Any]] = []
    all_flags: set[str] = set()
    reasons: list[str] = []
    provider = ""
    model = ""

    for character_name, reference_url in character_references:
        raw = adapter.compare_identity(
            reference_url=reference_url,
            candidate_url=candidate_url,
        )
        assessment = assess_identity_drift(
            identity_similarity=float(raw["identity_similarity"]),
            flags=list(raw.get("flags") or []),
            min_similarity=min_similarity,
            evidence=dict(raw.get("evidence") or {}),
        )
        comparison = {
            "character": character_name,
            "reference_url": reference_url,
            **assessment,
        }
        comparisons.append(comparison)
        all_flags.update(assessment["flags"])
        reasons.extend(f"{character_name}: {reason}" for reason in assessment["reasons"])
        provider = provider or str(raw.get("provider") or "")
        model = model or str(raw.get("model") or "")

    passed = all(item["passed"] for item in comparisons)
    scores = [item["identity_similarity"] for item in comparisons]
    return {
        "status": "passed" if passed else "blocked",
        "passed": passed,
        "identity_similarity": min(scores),
        "min_similarity": min_similarity,
        "flags": sorted(all_flags),
        "blocking_flags": sorted({flag for item in comparisons for flag in item["blocking_flags"]}),
        "reasons": reasons,
        "evidence": {"comparisons": comparisons},
        "provider": provider,
        "model": model,
    }
