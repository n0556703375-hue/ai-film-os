from fastapi import APIRouter
from contextlib import closing
from app.database.connection import get_connection

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("")
def dashboard():
    with closing(get_connection()) as conn:
        total = conn.execute("SELECT COUNT(*) FROM shots").fetchone()[0]
        statuses = {
            row["status"]: row["count"]
            for row in conn.execute(
                "SELECT status,COUNT(*) AS count FROM shots GROUP BY status"
            ).fetchall()
        }
        assets = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        scenes = conn.execute("SELECT COUNT(*) FROM scenes").fetchone()[0]
        issues = conn.execute(
            "SELECT COUNT(*) FROM continuity_issues WHERE resolved=0"
        ).fetchone()[0]
    return {
        "shots_total": total,
        "status_counts": statuses,
        "assets_total": assets,
        "scenes_total": scenes,
        "open_issues": issues,
    }
