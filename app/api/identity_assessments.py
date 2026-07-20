import json
from contextlib import closing
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.database.connection import get_connection
from app.services.identity_drift import (
    DEFAULT_MIN_IDENTITY_SIMILARITY,
    assess_identity_drift,
)


router = APIRouter(prefix="/api/shots", tags=["identity-assessments"])


class IdentityDriftAssessmentRequest(BaseModel):
    status: Literal["passed", "blocked", "error"]
    passed: bool
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list, max_length=20)
    provider: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def validate_outcome(self):
        if self.status == "passed" and not self.passed:
            raise ValueError("A passed assessment must set passed=true.")
        if self.status != "passed" and self.passed:
            raise ValueError("A blocked or error assessment must set passed=false.")
        return self


class IdentityDriftEvaluationRequest(BaseModel):
    identity_similarity: float = Field(ge=0.0, le=1.0)
    flags: list[str] = Field(default_factory=list, max_length=50)
    min_similarity: float = Field(
        default=DEFAULT_MIN_IDENTITY_SIMILARITY,
        gt=0.0,
        le=1.0,
    )
    evidence: dict[str, Any] = Field(default_factory=dict)
    provider: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)


def _store_identity_drift(shot_id: int, media_id: int, assessment: dict[str, Any]):
    with closing(get_connection()) as conn:
        media = conn.execute(
            "SELECT * FROM media_results WHERE id=? AND shot_id=?",
            (media_id, shot_id),
        ).fetchone()
        if not media:
            raise HTTPException(404, "תוצאת המדיה לא נמצאה בשוט.")
        if media["media_type"] != "image":
            raise HTTPException(409, "בדיקת Identity Drift זמינה לתמונות בלבד.")

        metadata = json.loads(media["metadata_json"] or "{}")
        metadata["identity_drift"] = assessment
        conn.execute(
            "UPDATE media_results SET metadata_json=? WHERE id=?",
            (json.dumps(metadata, ensure_ascii=False), media_id),
        )
        conn.commit()

        updated = conn.execute(
            "SELECT * FROM media_results WHERE id=?",
            (media_id,),
        ).fetchone()

    result = dict(updated)
    result["metadata"] = json.loads(result["metadata_json"] or "{}")
    return {"shot_id": shot_id, "media": result}


@router.post("/{shot_id}/media/{media_id}/identity-drift")
def record_identity_drift(
    shot_id: int,
    media_id: int,
    request: IdentityDriftAssessmentRequest,
):
    return _store_identity_drift(
        shot_id,
        media_id,
        request.model_dump(exclude_none=True),
    )


@router.post("/{shot_id}/media/{media_id}/identity-drift/evaluate")
def evaluate_and_record_identity_drift(
    shot_id: int,
    media_id: int,
    request: IdentityDriftEvaluationRequest,
):
    assessment = assess_identity_drift(
        identity_similarity=request.identity_similarity,
        flags=request.flags,
        min_similarity=request.min_similarity,
        evidence=request.evidence,
    )
    assessment["provider"] = request.provider
    assessment["model"] = request.model
    return _store_identity_drift(shot_id, media_id, assessment)
