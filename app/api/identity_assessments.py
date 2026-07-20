import json
from contextlib import closing
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.database.connection import get_connection


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


@router.post("/{shot_id}/media/{media_id}/identity-drift")
def record_identity_drift(
    shot_id: int,
    media_id: int,
    request: IdentityDriftAssessmentRequest,
):
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
        metadata["identity_drift"] = request.model_dump(exclude_none=True)
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
