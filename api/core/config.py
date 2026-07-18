import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

class Settings:
    app_name = "AI Film OS"
    project_name = os.getenv("FILM_PROJECT_NAME", "כתובת אפס")
    database_path = Path(os.getenv("FILM_OS_DB", BASE_DIR / "film_os.db"))
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    port = int(os.getenv("PORT", "8000"))

settings = Settings()
