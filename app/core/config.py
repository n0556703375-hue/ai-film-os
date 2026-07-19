import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

class Settings:
    app_name = "AI Film OS"
    project_name = os.getenv("FILM_PROJECT_NAME", "כתובת אפס")
    database_path = Path(os.getenv("FILM_OS_DB", BASE_DIR / "film_os.db"))
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    openai_text_model = os.getenv("OPENAI_TEXT_MODEL", "gpt-5-mini")
    openai_image_model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")
    generated_media_path = Path(os.getenv("GENERATED_MEDIA_PATH", BASE_DIR / "generated"))
    port = int(os.getenv("PORT", "8000"))

settings = Settings()
