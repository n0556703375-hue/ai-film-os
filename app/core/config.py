import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


# Documented Kling international (global) API host. Kept as a module constant
# so callers and tests can assert the default without reloading this module.
KLING_DEFAULT_API_BASE = "https://api-singapore.klingai.com"
KLING_FALLBACK_MODEL = "kling-v2-master"
SYNC_DEFAULT_API_BASE = "https://api.sync.so"
SYNC_FALLBACK_MODEL = "sync-3"


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    app_name = "AI Film OS"
    project_name = os.getenv("FILM_PROJECT_NAME", "כתובת אפס")
    database_path = Path(os.getenv("FILM_OS_DB", BASE_DIR / "film_os.db"))
    database_url = os.getenv("DATABASE_URL", "").strip()
    enable_postgresql = _env_flag("ENABLE_POSTGRESQL", False)
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    openai_text_model = os.getenv("OPENAI_TEXT_MODEL", "gpt-5-mini")
    openai_vision_model = os.getenv("OPENAI_VISION_MODEL", "gpt-5.6-luna")
    openai_api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    identity_vision_provider = os.getenv("IDENTITY_VISION_PROVIDER", "openai").strip().lower()
    magnific_api_key = os.getenv("MAGNIFIC_API_KEY", "")
    magnific_api_base = os.getenv("MAGNIFIC_API_BASE", "https://api.magnific.com").rstrip("/")
    magnific_image_model = os.getenv("MAGNIFIC_IMAGE_MODEL", "nano-banana-pro")
    magnific_resolution = os.getenv("MAGNIFIC_RESOLUTION", "2K")
    generated_media_path = Path(os.getenv("GENERATED_MEDIA_PATH", BASE_DIR / "generated"))
    port = int(os.getenv("PORT", "8000"))
    # Seedance via fal.ai
    fal_api_key = os.getenv("FAL_API_KEY", "").strip()
    fal_api_base = os.getenv("FAL_API_BASE", "https://queue.fal.run").rstrip("/")
    fal_seedance_model = os.getenv("FAL_SEEDANCE_MODEL", "bytedance/seedance-2.0/image-to-video")
    fal_seedance_fast_model = os.getenv("FAL_SEEDANCE_FAST_MODEL", "bytedance/seedance-2.0/image-to-video-fast")
    # Sync.so lip-sync (future use)
    sync_api_key = os.getenv("SYNC_API_KEY", "").strip()
    sync_api_base = os.getenv("SYNC_API_BASE", SYNC_DEFAULT_API_BASE).rstrip("/")


settings = Settings()
