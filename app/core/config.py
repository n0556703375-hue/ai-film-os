import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

class Settings:
    app_name = "AI Film OS"
    project_name = os.getenv("FILM_PROJECT_NAME", "כתובת אפס")
    database_path = Path(os.getenv("FILM_OS_DB", BASE_DIR / "film_os.db"))
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    openai_text_model = os.getenv("OPENAI_TEXT_MODEL", "gpt-5-mini")
    magnific_api_key = os.getenv("MAGNIFIC_API_KEY", "")
    magnific_api_base = os.getenv("MAGNIFIC_API_BASE", "https://api.magnific.com").rstrip("/")
    magnific_image_model = os.getenv("MAGNIFIC_IMAGE_MODEL", "realism")
    magnific_resolution = os.getenv("MAGNIFIC_RESOLUTION", "2k")
    magnific_adherence = int(os.getenv("MAGNIFIC_ADHERENCE", "70"))
    magnific_hdr = int(os.getenv("MAGNIFIC_HDR", "50"))
    magnific_creative_detailing = int(os.getenv("MAGNIFIC_CREATIVE_DETAILING", "33"))
    generated_media_path = Path(os.getenv("GENERATED_MEDIA_PATH", BASE_DIR / "generated"))
    port = int(os.getenv("PORT", "8000"))

settings = Settings()
