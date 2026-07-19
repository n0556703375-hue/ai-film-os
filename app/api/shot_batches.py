from contextlib import closing
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database.connection import get_connection


router = APIRouter(prefix="/api/shots/batch", tags=["shots"])

SAFE_BATCH_STATUSES = {"מתוכנן", "פרומפט מוכן"}


class BatchShotStatusRequest(BaseModel):
    project_id: int = Field(ge=1)
    shot_ids: list[int] = Field(min_length=1, max_length=200)
    status: Literal["מתוכנן", "פרומפט מוכן"]
    confirmed: bool = False


@router.patch("/status")
def batch_update_shot_status(request: BatchShotStatusRequest):
    if not request.confirmed:
        raise HTTPException(409, "נדרש אישור מפורש לעדכון קבוצתי.")

    shot_ids = list(dict.fromkeys(request.shot_ids))
    placeholders = ",".join("?" for _ in shot_ids)
    with closing(get_connection()) as conn:
        rows = conn.execute(
            f"SELECT id,project_id,prompt FROM shots WHERE id IN ({placeholders})",
            shot_ids,
        ).fetchall()
        if len(rows) != len(shot_ids):
            raise HTTPException(404, "אחד השוטים שנבחרו אינו קיים.")
        if any(row["project_id"] != request.project_id for row in rows):
            raise HTTPException(409, "כל השוטים חייבים להשתייך להפקה הפעילה.")
        if request.status == "פרומפט מוכן" and any(not (row["prompt"] or "").strip() for row in rows):
            raise HTTPException(409, "לא ניתן לסמן כפרומפט מוכן שוט שאין לו פרומפט.")

        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            f"UPDATE shots SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
            [request.status, *shot_ids],
        )
        conn.commit()

    return {
        "updated_count": len(shot_ids),
        "shot_ids": shot_ids,
        "status": request.status,
    }
