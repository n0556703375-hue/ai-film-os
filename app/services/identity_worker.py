from __future__ import annotations

from typing import Any

from app.api.identity_assessments import (
    IdentityDriftAssessmentRequest,
    IdentityDriftClaimRequest,
    claim_identity_drift,
    record_identity_drift,
)
from app.repositories import shots as shot_repo
from app.services.identity_vision import IdentityVisionAdapter, evaluate_shot_identity


def process_identity_assessment(
    *,
    shot_id: int,
    media_id: int,
    worker_id: str,
    adapter: IdentityVisionAdapter,
) -> dict[str, Any]:
    """Claim, evaluate and persist one pending identity assessment.

    The adapter owns provider-specific comparison logic and credentials. This
    orchestration function performs no destructive data replacement and handles
    failures by recording a terminal error verdict for the claimed media item.
    """
    claimed = claim_identity_drift(
        shot_id,
        media_id,
        IdentityDriftClaimRequest(worker_id=worker_id),
    )

    try:
        shot = shot_repo.get_shot(shot_id)
        if not shot:
            raise ValueError("The claimed shot no longer exists.")

        verdict = evaluate_shot_identity(
            shot=shot,
            candidate_url=claimed["url"],
            adapter=adapter,
        )
        request = IdentityDriftAssessmentRequest(
            status=verdict["status"],
            passed=verdict["passed"],
            score=verdict.get("identity_similarity"),
            reasons=verdict.get("reasons", []),
            provider=verdict.get("provider", ""),
            model=verdict.get("model", ""),
        )
    except Exception as exc:
        request = IdentityDriftAssessmentRequest(
            status="error",
            passed=False,
            reasons=[f"Identity assessment worker failed: {type(exc).__name__}."],
        )

    stored = record_identity_drift(shot_id, media_id, request)
    return {
        "shot_id": shot_id,
        "media_id": media_id,
        "worker_id": worker_id,
        "identity_drift": stored["media"]["metadata"]["identity_drift"],
    }
