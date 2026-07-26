from __future__ import annotations

from typing import Any


COMPLETED_IDENTITY_DRIFT_STATUSES = frozenset({"passed", "blocked", "error"})


def summarize_completed_identity_drift(
    assessment: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a stable, read-only summary for a completed drift assessment.

    The helper intentionally exposes only operator-safe audit and outcome fields.
    It does not mutate the stored assessment or include arbitrary provider evidence.
    """
    if not isinstance(assessment, dict):
        return None

    status = assessment.get("status")
    if status not in COMPLETED_IDENTITY_DRIFT_STATUSES:
        return None

    summary = {
        "status": status,
        "passed": bool(assessment.get("passed")),
        "worker_id": assessment.get("worker_id"),
        "attempt": assessment.get("attempt"),
        "claimed_at": assessment.get("claimed_at"),
        "completed_at": assessment.get("completed_at"),
        "score": assessment.get("score"),
        "provider": assessment.get("provider"),
        "model": assessment.get("model"),
        "reasons": list(assessment.get("reasons") or []),
    }
    return summary
