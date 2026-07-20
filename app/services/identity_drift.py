from __future__ import annotations

from typing import Any


DEFAULT_MIN_IDENTITY_SIMILARITY = 0.82
CRITICAL_FLAGS = {
    "different_person",
    "face_structure_changed",
    "age_shift",
    "gender_presentation_changed",
}


def assess_identity_drift(
    *,
    identity_similarity: float,
    flags: list[str] | None = None,
    min_similarity: float = DEFAULT_MIN_IDENTITY_SIMILARITY,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a provider-neutral identity drift verdict for a character image.

    The caller supplies normalized comparison output from a vision provider or a
    human QA workflow. This function performs no external calls and stores no data.
    """
    if not 0 <= identity_similarity <= 1:
        raise ValueError("identity_similarity must be between 0 and 1.")
    if not 0 < min_similarity <= 1:
        raise ValueError("min_similarity must be greater than 0 and at most 1.")

    normalized_flags = sorted({str(flag).strip() for flag in (flags or []) if str(flag).strip()})
    blocking_flags = sorted(CRITICAL_FLAGS.intersection(normalized_flags))
    similarity_passed = identity_similarity >= min_similarity
    passed = similarity_passed and not blocking_flags

    reasons: list[str] = []
    if not similarity_passed:
        reasons.append(
            f"Identity similarity {identity_similarity:.3f} is below the required {min_similarity:.3f}."
        )
    if blocking_flags:
        reasons.append("Critical identity drift flags: " + ", ".join(blocking_flags) + ".")

    return {
        "status": "passed" if passed else "blocked",
        "passed": passed,
        "identity_similarity": round(identity_similarity, 4),
        "min_similarity": round(min_similarity, 4),
        "flags": normalized_flags,
        "blocking_flags": blocking_flags,
        "reasons": reasons,
        "evidence": dict(evidence or {}),
    }
