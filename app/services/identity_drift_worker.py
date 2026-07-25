from datetime import datetime, timezone
from typing import Any


def validate_identity_drift_worker_ownership(
    assessment: dict[str, Any],
    worker_id: str,
) -> str:
    """Validate that a running identity-drift job is completed by its claimant.

    Returns the normalized worker ID for callers that need to persist or log it.
    This helper is intentionally side-effect free so API and worker orchestration
    can share the same ownership rule without touching production data.
    """
    normalized_worker_id = worker_id.strip()
    if not normalized_worker_id:
        raise ValueError("worker_id must contain non-whitespace characters.")

    if assessment.get("status") != "running":
        raise ValueError("identity drift assessment is not currently running.")

    claimed_worker_id = assessment.get("worker_id")
    if not isinstance(claimed_worker_id, str) or not claimed_worker_id.strip():
        raise ValueError("identity drift assessment has no valid claimed worker.")

    if claimed_worker_id.strip() != normalized_worker_id:
        raise ValueError("identity drift assessment is claimed by another worker.")

    return normalized_worker_id


def build_completed_identity_drift_assessment(
    current_assessment: dict[str, Any],
    result: dict[str, Any],
    worker_id: str,
    *,
    completed_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a completed result while retaining claim audit metadata."""
    normalized_worker_id = validate_identity_drift_worker_ownership(
        current_assessment,
        worker_id,
    )
    completed = dict(result)
    completed["worker_id"] = normalized_worker_id
    completed["attempt"] = int(current_assessment.get("attempt") or 1)
    claimed_at = current_assessment.get("claimed_at")
    if claimed_at:
        completed["claimed_at"] = claimed_at
    timestamp = completed_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("completed_at must be timezone-aware.")
    completed["completed_at"] = timestamp.astimezone(timezone.utc).isoformat()
    return completed
