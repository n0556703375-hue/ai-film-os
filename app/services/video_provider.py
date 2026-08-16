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
    # Only read by LocalComfyUIProvider (app/services/providers/
    # local_comfyui_provider.py) — every other provider ignores this field.
    # "ltx" (LTX-2.3, produces synced audio too) or "wan" (Wan 2.2, no audio).
    local_model: str = "wan"


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

    def cost_for(self, request: VideoGenerationRequest) -> float:
        ...


class DisabledVideoProvider:
    name = "disabled"

    def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        raise VideoProviderNotConfigured(
            "Video provider is not configured. Select and configure a provider before running video jobs."
        )

    def cost_for(self, request: VideoGenerationRequest) -> float:
        # No provider configured means no jobs can actually run, so there is
        # nothing to cost — never invents a number for a provider that isn't
        # there.
        return 0.0


def get_video_provider(*, draft_mode: bool = False) -> VideoProvider:
    """Return the configured video provider.

    draft_mode (default False, unchanged behavior for every existing caller):
      True routes to the local ComfyUI provider instead of the normal
      external priority list below — for fast/free local iteration before
      committing to a paid external render. Requires COMFYUI_ENDPOINT to be
      configured; raises VideoProviderNotConfigured otherwise rather than
      silently falling back to an external (billed) provider, since that
      would defeat the purpose of explicitly requesting a draft.

    Normal (draft_mode=False) priority:
      1. FAL_API_KEY set → SeedanceProvider (Seedance 2.0 via fal.ai, primary)
      2. Both KLING_ACCESS_KEY and KLING_SECRET_KEY set → KlingProvider (legacy)
      3. Fallback → DisabledVideoProvider (safe no-op)
    """
    import os

    if draft_mode:
        from app.services.providers import comfyui_client
        from app.services.providers.local_comfyui_provider import LocalComfyUIProvider

        if not comfyui_client.is_configured():
            raise VideoProviderNotConfigured(
                "COMFYUI_ENDPOINT is not configured — draft mode requires a local "
                "ComfyUI instance. See SETUP_NOTES.md for how to install and run one."
            )
        return LocalComfyUIProvider()

    if os.getenv("FAL_API_KEY", "").strip():
        from app.services.seedance_provider import SeedanceProvider

        return SeedanceProvider()
    if os.getenv("KLING_ACCESS_KEY", "").strip() and os.getenv("KLING_SECRET_KEY", "").strip():
        from app.services.kling_provider import KlingProvider

        return KlingProvider()
    return DisabledVideoProvider()


DEFAULT_SHOT_DURATION_SECONDS = 5.0


def estimate_default_shot_cost_usd(duration_seconds: float = DEFAULT_SHOT_DURATION_SECONDS) -> float:
    """Rough per-shot cost at the currently configured provider's default
    settings — no real image, prompt, or duration for a specific shot is
    known yet (shots don't carry a planned duration), so this is only ever
    used for a project-wide cost *projection* before any generation has
    run, never for an actual job's estimated_cost_usd.
    """
    request = VideoGenerationRequest(image_url="", prompt="", duration_seconds=duration_seconds)
    return get_video_provider().cost_for(request)
