from contextlib import closing

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.core.version import APP_VERSION
from app.database.connection import get_connection

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "project": settings.project_name,
    }


@router.get("/ready")
def readiness():
    try:
        with closing(get_connection()) as conn:
            conn.execute("SELECT 1").fetchone()
            required_tables = {"projects", "scenes", "shots", "media_jobs"}
            existing_tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
    except Exception as exc:
        raise HTTPException(503, "Database readiness check failed.") from exc

    missing_tables = sorted(required_tables - existing_tables)
    if missing_tables:
        raise HTTPException(
            503,
            "Database schema is incomplete: " + ", ".join(missing_tables),
        )

    return {
        "status": "ready",
        "version": APP_VERSION,
        "database": "ok",
    }
