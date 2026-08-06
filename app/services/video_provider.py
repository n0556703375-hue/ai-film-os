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
    import os
    # Kling requires both halves of the AccessKey/SecretKey pair to sign a JWT;
    # a partially configured environment stays disabled rather than failing later.
    if os.getenv("KLING_ACCESS_KEY", "").strip() and os.getenv("KLING_SECRET_KEY", "").strip():
        from app.services.kling_provider import KlingProvider
        return KlingProvider()
    return DisabledVideoProvider()
