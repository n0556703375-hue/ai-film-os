import json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings
from app.database.connection import get_connection
from app.services.identity_drift import (
    DEFAULT_MIN_IDENTITY_SIMILARITY,
    assess_identity_drift,
)
from app.services.identity_drift_observability import (
    summarize_completed_identity_drift,
)
from app.services.identity_drift_worker import (
    build_completed_identity_drift_assessment,
)


router = APIRouter(prefix="/api/shots", tags=["identity-assessments"])

# Both media types share one identity-drift queue/lifecycle — same
# metadata_json["identity_drift"] shape, same claim/evaluate/record
# endpoints. Only which frame the vision adapter is shown differs (see
# app/services/identity_worker.py, which extracts a frame from video before
# comparing — everything else here is media_type-agnostic.
_IDENTITY_DRIFT_MEDIA_TYPES = {"image", "video"}


class IdentityDriftAssessmentRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=200)
    status: Literal["passed", "blocked", "error"]
    passed: bool
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list, max_length=20)
    provider: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)

    @field_validator("worker_id")
    @classmethod
    def normalize_worker_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("worker_id must contain non-whitespace characters.")
        return normalized

    @model_validator(mode="after")
    def validate_outcome(self):
        if self.status == "passed" and not self.passed:
            raise ValueError("A passed assessment must set passed=true.")
        if self.status != "passed" and self.passed:
            raise ValueError("A blocked or error assessment must set passed=false.")
        return self


class IdentityDriftEvaluationRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=200)
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

    @field_validator("worker_id")
    @classmethod
    def normalize_worker_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("worker_id must contain non-whitespace characters.")
        return normalized


class IdentityDriftClaimRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=200)

    @field_validator("worker_id")
    @classmethod
    def normalize_worker_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("worker_id must contain non-whitespace characters.")
        return normalized


def _store_identity_drift(
    shot_id: int,
    media_id: int,
    assessment: dict[str, Any],
    worker_id: str,
):
    with closing(get_connection()) as conn:
        media = conn.execute(
            "SELECT * FROM media_results WHERE id=? AND shot_id=?",
            (media_id, shot_id),
        ).fetchone()
        if not media:
            raise HTTPException(404, "תוצאת המדיה לא נמצאה בשוט.")
        if media["media_type"] not in _IDENTITY_DRIFT_MEDIA_TYPES:
            raise HTTPException(409, "בדיקת Identity Drift זמינה לתמונות ולווידאו בלבד.")

        try:
            metadata = json.loads(media["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(409, "נתוני בדיקת הזהות אינם תקינים.") from exc
        current_assessment = metadata.get("identity_drift")
        if not isinstance(current_assessment, dict):
            raise HTTPException(409, "בדיקת הזהות לא נאספה לעיבוד.")
        try:
            completed_assessment = build_completed_identity_drift_assessment(
                current_assessment,
                assessment,
                worker_id,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

        metadata["identity_drift"] = completed_assessment
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


@router.get("/identity-drift/status")
def identity_drift_status():
    """Lets the UI tell "still queued, will run shortly" apart from "queued
    forever because OPENAI_API_KEY was never set" — see
    app/background_worker.py::_process_next_identity_assessment_safely,
    which silently skips processing whenever this is False."""
    return {"configured": bool(settings.openai_api_key)}


@router.get("/identity-drift/pending")
def list_pending_identity_drift(
    project_id: int = Query(ge=1),
    limit: int = Query(default=50, ge=1, le=200),
):
    with closing(get_connection()) as conn:
        project = conn.execute(
            "SELECT id FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
        if not project:
            raise HTTPException(404, "הפרויקט לא נמצא.")

        rows = conn.execute(
            """
            SELECT media_results.id, media_results.shot_id, media_results.media_type,
                   media_results.url, media_results.metadata_json
            FROM media_results
            JOIN shots ON shots.id = media_results.shot_id
            WHERE media_results.media_type IN ('image', 'video')
              AND shots.project_id=?
            ORDER BY media_results.id ASC
            """,
            (project_id,),
        ).fetchall()

    pending = []
    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        assessment = metadata.get("identity_drift")
        if not isinstance(assessment, dict) or assessment.get("status") != "pending":
            continue
        pending.append({
            "media_id": row["id"],
            "shot_id": row["shot_id"],
            "media_type": row["media_type"],
            "url": row["url"],
            "identity_drift": assessment,
        })
        if len(pending) >= limit:
            break

    return {"items": pending, "count": len(pending)}


@router.get("/identity-drift/completed")
def list_completed_identity_drift(
    project_id: int = Query(ge=1),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Return operator-safe summaries for one project's completed image/video assessments."""
    with closing(get_connection()) as conn:
        project = conn.execute(
            "SELECT id FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
        if not project:
            raise HTTPException(404, "הפרויקט לא נמצא.")

        rows = conn.execute(
            """
            SELECT media_results.id, media_results.shot_id, media_results.media_type,
                   media_results.url, media_results.metadata_json
            FROM media_results
            JOIN shots ON shots.id = media_results.shot_id
            WHERE media_results.media_type IN ('image', 'video')
              AND shots.project_id=?
            ORDER BY media_results.id DESC
            """,
            (project_id,),
        ).fetchall()

    completed = []
    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        summary = summarize_completed_identity_drift(metadata.get("identity_drift"))
        if summary is None:
            continue
        completed.append({
            "media_id": row["id"],
            "shot_id": row["shot_id"],
            "media_type": row["media_type"],
            "url": row["url"],
            "identity_drift": summary,
        })
        if len(completed) >= limit:
            break

    return {"items": completed, "count": len(completed)}


@router.post("/identity-drift/requeue-stale")
def requeue_stale_identity_drift(
    project_id: int = Query(ge=1),
    max_age_minutes: int = Query(default=30, ge=1, le=1440),
    limit: int = Query(default=50, ge=1, le=200),
):
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=max_age_minutes)
    requeued = []

    with closing(get_connection()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        project = conn.execute(
            "SELECT id FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
        if not project:
            raise HTTPException(404, "הפרויקט לא נמצא.")

        rows = conn.execute(
            """
            SELECT media_results.id, media_results.shot_id,
                   media_results.metadata_json
            FROM media_results
            JOIN shots ON shots.id = media_results.shot_id
            WHERE media_results.media_type IN ('image', 'video')
              AND shots.project_id=?
            ORDER BY media_results.id ASC
            """,
            (project_id,),
        ).fetchall()

        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            assessment = metadata.get("identity_drift")
            if not isinstance(assessment, dict) or assessment.get("status") != "running":
                continue

            claimed_at_raw = assessment.get("claimed_at")
            try:
                claimed_at = datetime.fromisoformat(claimed_at_raw)
            except (TypeError, ValueError):
                continue
            if claimed_at.tzinfo is None:
                claimed_at = claimed_at.replace(tzinfo=timezone.utc)
            if claimed_at.astimezone(timezone.utc) > stale_before:
                continue

            pending = dict(assessment)
            pending.update({
                "status": "pending",
                "passed": False,
                "requeued_at": now.isoformat(),
                "reasons": ["Previous worker claim expired before completion."],
            })
            pending.pop("worker_id", None)
            pending.pop("claimed_at", None)
            metadata["identity_drift"] = pending
            conn.execute(
                "UPDATE media_results SET metadata_json=? WHERE id=?",
                (json.dumps(metadata, ensure_ascii=False), row["id"]),
            )
            requeued.append({"media_id": row["id"], "shot_id": row["shot_id"]})
            if len(requeued) >= limit:
                break

        conn.commit()

    return {"items": requeued, "count": len(requeued)}


@router.post("/{shot_id}/media/{media_id}/identity-drift/claim")
def claim_identity_drift(
    shot_id: int,
    media_id: int,
    request: IdentityDriftClaimRequest,
):
    with closing(get_connection()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        media = conn.execute(
            "SELECT * FROM media_results WHERE id=? AND shot_id=?",
            (media_id, shot_id),
        ).fetchone()
        if not media:
            raise HTTPException(404, "תוצאת המדיה לא נמצאה בשוט.")
        if media["media_type"] not in _IDENTITY_DRIFT_MEDIA_TYPES:
            raise HTTPException(409, "בדיקת Identity Drift זמינה לתמונות ולווידאו בלבד.")

        try:
            metadata = json.loads(media["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(409, "נתוני בדיקת הזהות אינם תקינים.") from exc
        assessment = metadata.get("identity_drift")
        if not isinstance(assessment, dict) or assessment.get("status") != "pending":
            raise HTTPException(409, "בדיקת הזהות כבר נאספה או הושלמה.")

        claimed = dict(assessment)
        claimed.update({
            "status": "running",
            "passed": False,
            "worker_id": request.worker_id,
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "attempt": int(assessment.get("attempt") or 0) + 1,
        })
        metadata["identity_drift"] = claimed
        conn.execute(
            "UPDATE media_results SET metadata_json=? WHERE id=?",
            (json.dumps(metadata, ensure_ascii=False), media_id),
        )
        conn.commit()

    return {
        "media_id": media_id,
        "shot_id": shot_id,
        "media_type": media["media_type"],
        "url": media["url"],
        "identity_drift": claimed,
    }


@router.post("/{shot_id}/media/{media_id}/identity-drift")
def record_identity_drift(
    shot_id: int,
    media_id: int,
    request: IdentityDriftAssessmentRequest,
):
    return _store_identity_drift(
        shot_id,
        media_id,
        request.model_dump(exclude={"worker_id"}, exclude_none=True),
        request.worker_id,
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
    return _store_identity_drift(
        shot_id,
        media_id,
        assessment,
        request.worker_id,
    )
