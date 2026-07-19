from fastapi import APIRouter

from app.core.config import settings
from app.core.version import APP_VERSION

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "project": settings.project_name,
        "api_key_configured": bool(settings.openai_api_key),
    }
