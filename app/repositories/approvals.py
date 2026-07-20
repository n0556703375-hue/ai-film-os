import json
from contextlib import closing

from app.database.connection import get_connection


APPROVED = "מאושר"
REJECTED = "נדחה"
BLOCKING_CONTINUITY_SEVERITIES = ("critical", "high")


def _shot_status_for_media(conn, shot_id: int) -> str:
    approved_image = conn.execute(
        "SELECT 1 FROM media_results WHERE shot_id=? AND media_type='image' AND status=? LIMIT 1",
        (shot_id, APPROVED),
    ).fetchone()
    approved_video = conn.execute(
        "SELECT 1 FROM media_results WHERE shot_id=? AND media_type='video' AND status=? LIMIT 1",
        (shot_id, APPROVED),
    ).fetchone()
    any_image = conn.execute(
        "SELECT 1 FROM media_results WHERE shot_id=? AND media_type='image' LIMIT 1",
        (shot_id,),
    ).fetchone()
    any_video = conn.execute(
        "SELECT 1 FROM media_results WHERE shot_id=? AND media_type='video' LIMIT 1",
        (shot_id,),
    ).fetchone()
    if approved_video:
        return "וידאו מאושר"
    if approved_image and any_video:
        return "וידאו טיוטה"
    if approved_image:
        return "תמונה מאושרת"
    if any_image:
        return "תמונת טיוטה"
    return "פרומפט מוכן"


def _identity_drift_blocker(metadata):
    if not metadata:
        return None
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            return None
    if not isinstance(metadata, dict):
        return None

    assessment = metadata.get("identity_drift")
    if not isinstance(assessment, dict):
        return None

    if assessment.get("passed") is True and assessment.get("status") not in {"blocked", "failed"}:
        return None

    reasons = assessment.get("reasons") or []
    if isinstance(reasons, list) and reasons:
        reason_text = " ".join(str(reason) for reason in reasons if str(reason).strip())
        if reason_text:
            return reason_text

    status = str(assessment.get("status") or "").strip().lower()
    if status in {"pending", "queued", "running", "in_progress"}:
        return "בדיקת זהות הדמות טרם הושלמה."
    if status in {"error", "unavailable"}:
        return "בדיקת זהות הדמות אינה זמינה ויש להריץ אותה מחדש."
    return "בדיקת זהות הדמות לא עברה בהצלחה."


def decide_media(shot_id: int, media_id: int, decision: str, notes: str = ""):
    if decision not in {"approve", "reject"}:
        raise ValueError("החלטת האישור אינה תקינה.")
    with closing(get_connection()) as conn:
        shot = conn.execute("SELECT * FROM shots WHERE id=?", (shot_id,)).fetchone()
        if not shot:
            return None
        media = conn.execute(
            "SELECT * FROM media_results WHERE id=? AND shot_id=?",
            (media_id, shot_id),
        ).fetchone()
        if not media:
            raise ValueError("תוצאת המדיה אינה שייכת לשוט.")

        if decision == "approve" and media["media_type"] == "image":
            blocker = _identity_drift_blocker(media["metadata"])
            if blocker:
                raise ValueError(f"לא ניתן לאשר תמונה עם סטיית זהות חסומה: {blocker}")

        if decision == "approve" and media["media_type"] == "video":
            approved_image = conn.execute(
                "SELECT 1 FROM media_results WHERE shot_id=? AND media_type='image' AND status=? LIMIT 1",
                (shot_id, APPROVED),
            ).fetchone()
            if not approved_image:
                raise ValueError("יש לאשר תמונת שוט לפני אישור וידאו.")

        new_media_status = APPROVED if decision == "approve" else REJECTED
        if decision == "approve":
            conn.execute(
                "UPDATE media_results SET status='הוחלף' WHERE shot_id=? AND media_type=? AND id<>? AND status=?",
                (shot_id, media["media_type"], media_id, APPROVED),
            )
        conn.execute(
            "UPDATE media_results SET status=?, notes=CASE WHEN ?='' THEN notes ELSE ? END WHERE id=?",
            (new_media_status, notes, notes, media_id),
        )

        new_shot_status = _shot_status_for_media(conn, shot_id)
        conn.execute(
            "UPDATE shots SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (new_shot_status, shot_id),
        )
        conn.execute(
            """
            INSERT INTO approval_events
            (shot_id,media_result_id,event_type,from_status,to_status,notes)
            VALUES (?,?,?,?,?,?)
            """,
            (
                shot_id,
                media_id,
                "media_approved" if decision == "approve" else "media_rejected",
                media["status"],
                new_media_status,
                notes,
            ),
        )
        conn.commit()
    return get_pipeline(shot_id)


def _blocking_continuity_issue(conn, shot_id: int):
    placeholders = ",".join("?" for _ in BLOCKING_CONTINUITY_SEVERITIES)
    return conn.execute(
        f"""
        SELECT severity, message FROM continuity_issues
        WHERE shot_id=? AND severity IN ({placeholders})
          AND COALESCE(status, CASE WHEN resolved=1 THEN 'נפתר' ELSE 'פתוח' END)
              NOT IN ('נפתר','אושר כחריגה')
        ORDER BY CASE severity WHEN 'critical' THEN 1 ELSE 2 END, id
        LIMIT 1
        """,
        (shot_id, *BLOCKING_CONTINUITY_SEVERITIES),
    ).fetchone()


def finalize_shot(shot_id: int, notes: str = ""):
    with closing(get_connection()) as conn:
        shot = conn.execute("SELECT * FROM shots WHERE id=?", (shot_id,)).fetchone()
        if not shot:
            return None
        approved_image = conn.execute(
            "SELECT 1 FROM media_results WHERE shot_id=? AND media_type='image' AND status=? LIMIT 1",
            (shot_id, APPROVED),
        ).fetchone()
        approved_video = conn.execute(
            "SELECT 1 FROM media_results WHERE shot_id=? AND media_type='video' AND status=? LIMIT 1",
            (shot_id, APPROVED),
        ).fetchone()
        blocking_issue = _blocking_continuity_issue(conn, shot_id)
        if not approved_image:
            raise ValueError("לא ניתן לסיים שוט ללא תמונה מאושרת.")
        if not approved_video:
            raise ValueError("לא ניתן לסיים שוט ללא וידאו מאושר.")
        if blocking_issue:
            severity_label = "קריטית" if blocking_issue["severity"] == "critical" else "בחומרה גבוהה"
            raise ValueError(f"לא ניתן לסיים שוט עם בעיית רציפות {severity_label} פתוחה.")

        conn.execute("UPDATE shots SET status='סופי',updated_at=CURRENT_TIMESTAMP WHERE id=?", (shot_id,))
        conn.execute(
            """
            INSERT INTO approval_events
            (shot_id,event_type,from_status,to_status,notes)
            VALUES (?,?,?,?,?)
            """,
            (shot_id, "shot_finalized", shot["status"], "סופי", notes),
        )
        conn.commit()
    return get_pipeline(shot_id)


def get_pipeline(shot_id: int):
    with closing(get_connection()) as conn:
        shot = conn.execute("SELECT id,status FROM shots WHERE id=?", (shot_id,)).fetchone()
        if not shot:
            return None
        derived_status = shot["status"] if shot["status"] == "סופי" else _shot_status_for_media(conn, shot_id)
        media = conn.execute(
            "SELECT * FROM media_results WHERE shot_id=? ORDER BY media_type,version DESC",
            (shot_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM approval_events WHERE shot_id=? ORDER BY id DESC",
            (shot_id,),
        ).fetchall()
    return {
        "shot_id": shot_id,
        "status": derived_status,
        "media_results": [dict(row) for row in media],
        "approval_events": [dict(row) for row in events],
    }
