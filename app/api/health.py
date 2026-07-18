from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(tags=["health"])

@router.get("/health")
def health():
    return {
        "status": "ok",
        "version": "3.0.0",
        "project": settings.project_name,
        "api_key_configured": bool(settings.openai_api_key),
    }
