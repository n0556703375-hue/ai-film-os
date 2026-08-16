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
    # S3-compatible object storage (Cloudflare R2 / AWS S3 / Backblaze B2) for
    # generated media — see app/services/object_storage.py. Optional: when
    # unset, media falls back to local disk under generated_media_path, which
    # does not survive a deploy/restart on a platform without a persistent disk.
    object_storage_endpoint = os.getenv("OBJECT_STORAGE_ENDPOINT", "").strip()
    object_storage_bucket = os.getenv("OBJECT_STORAGE_BUCKET", "").strip()
    object_storage_access_key = os.getenv("OBJECT_STORAGE_ACCESS_KEY", "").strip()
    object_storage_secret_key = os.getenv("OBJECT_STORAGE_SECRET_KEY", "").strip()
    object_storage_region = os.getenv("OBJECT_STORAGE_REGION", "auto").strip()
    object_storage_public_url_base = os.getenv("OBJECT_STORAGE_PUBLIC_URL_BASE", "").strip()
    # Local ComfyUI (draft-quality video/image generation on local hardware —
    # see app/services/providers/). Optional: unset means the local provider
    # is never selected, regardless of a shot's draft_mode request.
    comfyui_endpoint = os.getenv("COMFYUI_ENDPOINT", "").strip().rstrip("/")
    comfyui_workflow_ltx_path = os.getenv("COMFYUI_WORKFLOW_LTX_PATH", "").strip()
    comfyui_workflow_wan_path = os.getenv("COMFYUI_WORKFLOW_WAN_PATH", "").strip()
    comfyui_workflow_sdxl_path = os.getenv("COMFYUI_WORKFLOW_SDXL_PATH", "").strip()
    comfyui_workflow_flux_path = os.getenv("COMFYUI_WORKFLOW_FLUX_PATH", "").strip()
    port = int(os.getenv("PORT", "8000"))
    # Seedance via fal.ai (primary video provider for Gate 2)
    fal_api_key = os.getenv("FAL_API_KEY", "").strip()
    fal_api_base = os.getenv("FAL_API_BASE", "https://queue.fal.run").rstrip("/")
    fal_seedance_model = os.getenv("FAL_SEEDANCE_MODEL", "bytedance/seedance-2.0/image-to-video")
    fal_seedance_fast_model = os.getenv("FAL_SEEDANCE_FAST_MODEL", "bytedance/seedance-2.0/fast/image-to-video")
    # Kling (legacy provider, kept for test support)
    kling_access_key = os.getenv("KLING_ACCESS_KEY", "").strip()
    kling_secret_key = os.getenv("KLING_SECRET_KEY", "").strip()
    kling_api_base = os.getenv("KLING_API_BASE", KLING_DEFAULT_API_BASE).rstrip("/")
    kling_default_model = os.getenv("KLING_DEFAULT_MODEL", KLING_FALLBACK_MODEL)
    # Sync.so lip-sync (kept for test support)
    sync_api_key = os.getenv("SYNC_API_KEY", "").strip()
    sync_api_base = os.getenv("SYNC_API_BASE", SYNC_DEFAULT_API_BASE).rstrip("/")
    sync_default_model = os.getenv("SYNC_DEFAULT_MODEL", SYNC_FALLBACK_MODEL).strip()


settings = Settings()
