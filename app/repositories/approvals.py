from contextlib import closing

from app.database.connection import get_connection


APPROVED = "מאושר"
REJECTED = "נדחה"
DRAFT = "טיוטה"


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
    if any_video:
        return "וידאו טיוטה"
    if approved_image:
        return "תמונה מאושרת"
    if any_image:
        return "תמונת טיוטה"
    return "פרומפט מוכן"


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
        critical_open = conn.execute(
            """
            SELECT 1 FROM continuity_issues
            WHERE shot_id=? AND severity='critical'
              AND COALESCE(status, CASE WHEN resolved=1 THEN 'נפתר' ELSE 'פתוח' END)
                  NOT IN ('נפתר','אושר כחריגה')
            LIMIT 1
            """,
            (shot_id,),
        ).fetchone()
        if not approved_image:
            raise ValueError("לא ניתן לסיים שוט ללא תמונה מאושרת.")
        if not approved_video:
            raise ValueError("לא ניתן לסיים שוט ללא וידאו מאושר.")
        if critical_open:
            raise ValueError("לא ניתן לסיים שוט עם בעיית רציפות קריטית פתוחה.")

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
        "status": shot["status"],
        "media_results": [dict(row) for row in media],
        "approval_events": [dict(row) for row in events],
    }
