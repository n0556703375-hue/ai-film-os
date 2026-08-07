from dataclasses import dataclass
from typing import Protocol


class VideoProviderNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class VideoGenerationRequest:
    image_url: str
    prompt: str
    duration_seconds: float
    camera_motion: str = ""
    audio_mode: str = "none"
    aspect_ratio: str = "16:9"
    model_profile: str = "cinematic"


@dataclass(frozen=True)
class VideoGenerationResult:
    url: str
    provider: str
    model: str
    external_task_id: str = ""
    actual_cost_usd: float = 0


class VideoProvider(Protocol):
    name: str

    def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        ...


class DisabledVideoProvider:
    name = "disabled"

    def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        raise VideoProviderNotConfigured(
            "Video provider is not configured. Select and configure a provider before running video jobs."
        )


def get_video_provider() -> VideoProvider:
    """Return the configured video provider.

    Priority:
      1. FAL_API_KEY set → SeedanceProvider (Seedance 2.0 via fal.ai, primary)
      2. Both KLING_ACCESS_KEY and KLING_SECRET_KEY set → KlingProvider (legacy)
      3. Fallback → DisabledVideoProvider (safe no-op)
    """
    import os

    if os.getenv("FAL_API_KEY", "").strip():
        from app.services.seedance_provider import SeedanceProvider

        return SeedanceProvider()
    if os.getenv("KLING_ACCESS_KEY", "").strip() and os.getenv("KLING_SECRET_KEY", "").strip():
        from app.services.kling_provider import KlingProvider

        return KlingProvider()
    return DisabledVideoProvider()
