from fastapi import APIRouter

from app.services.magnific_connection import check_magnific_connection


router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@router.get("/magnific/connection")
def magnific_connection():
    return check_magnific_connection()
