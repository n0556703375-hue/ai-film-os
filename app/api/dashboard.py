from fastapi import APIRouter
from contextlib import closing
from app.database.connection import get_connection

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("")
def dashboard(project_id: int | None = None):
    shot_filter = " WHERE project_id=?" if project_id is not None else ""
    scene_filter = shot_filter
    asset_filter = shot_filter
    issue_filter = " WHERE project_id=? AND resolved=0" if project_id is not None else " WHERE resolved=0"
    critical_filter = (
        " WHERE project_id=? AND resolved=0 AND severity IN ('critical','high')"
        if project_id is not None
        else " WHERE resolved=0 AND severity IN ('critical','high')"
    )
    params = (project_id,) if project_id is not None else ()

    with closing(get_connection()) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM shots{shot_filter}", params).fetchone()[0]
        status_rows = conn.execute(
            f"SELECT status,COUNT(*) AS count FROM shots{shot_filter} GROUP BY status", params
        ).fetchall()
        statuses = {row["status"]: row["count"] for row in status_rows}
        assets = conn.execute(f"SELECT COUNT(*) FROM assets{asset_filter}", params).fetchone()[0]
        approved_assets = conn.execute(
            f"SELECT COUNT(*) FROM assets{asset_filter}{' AND' if asset_filter else ' WHERE'} approved=1",
            params
        ).fetchone()[0]
        scenes = conn.execute(f"SELECT COUNT(*) FROM scenes{scene_filter}", params).fetchone()[0]
        issues = conn.execute(
            f"SELECT COUNT(*) FROM continuity_issues{issue_filter}", params
        ).fetchone()[0]
        critical = conn.execute(
            f"SELECT COUNT(*) FROM continuity_issues{critical_filter}", params
        ).fetchone()[0]

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
