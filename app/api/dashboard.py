from fastapi import APIRouter
from contextlib import closing
from app.database.connection import get_connection

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("")
def dashboard():
    with closing(get_connection()) as conn:
        total = conn.execute("SELECT COUNT(*) FROM shots").fetchone()[0]
        status_rows = conn.execute(
            "SELECT status,COUNT(*) AS count FROM shots GROUP BY status"
        ).fetchall()
        statuses = {row["status"]: row["count"] for row in status_rows}
        assets = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        approved_assets = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE approved=1"
        ).fetchone()[0]
        scenes = conn.execute("SELECT COUNT(*) FROM scenes").fetchone()[0]
        issues = conn.execute(
            "SELECT COUNT(*) FROM continuity_issues WHERE resolved=0"
        ).fetchone()[0]
        critical = conn.execute("""
            SELECT COUNT(*) FROM continuity_issues
            WHERE resolved=0 AND severity IN ('critical','high')
        """).fetchone()[0]

    completed = statuses.get("סופי", 0)
    progress = round((completed / total) * 100) if total else 0

    pipeline = [
        {"name": "מתוכנן", "count": statuses.get("מתוכנן", 0)},
        {"name": "רפרנס", "count": statuses.get("רפרנס", 0)},
        {"name": "פרומפט מוכן", "count": statuses.get("פרומפט מוכן", 0)},
        {"name": "תמונה מאושרת", "count": statuses.get("תמונה מאושרת", 0)},
        {"name": "וידאו מאושר", "count": statuses.get("וידאו מאושר", 0)},
        {"name": "אודיו", "count": statuses.get("אודיו", 0)},
        {"name": "QA", "count": statuses.get("QA", 0)},
        {"name": "סופי", "count": completed},
    ]

    return {
        "shots_total": total,
        "status_counts": statuses,
        "pipeline": pipeline,
        "project_progress": progress,
        "assets_total": assets,
        "approved_assets": approved_assets,
        "scenes_total": scenes,
        "open_issues": issues,
        "critical_issues": critical,
    }
