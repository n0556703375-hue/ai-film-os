from dataclasses import dataclass


@dataclass(frozen=True)
class VideoModelSelection:
    profile: str
    reason: str


VALID_HINTS = {"auto", "cinematic", "fast", "high_fidelity"}


def select_video_model(shot: dict, payload: dict) -> VideoModelSelection:
    """Choose a provider-neutral model profile from production requirements.

    The result is a capability profile rather than a vendor model name. A provider
    adapter can map the profile to its concrete model without changing queue logic.
    """
    hint = str(payload.get("model_hint") or "auto")
    if hint not in VALID_HINTS:
        hint = "auto"
    if hint != "auto":
        return VideoModelSelection(hint, f"operator selected {hint}")

    duration = float(payload.get("duration_seconds") or shot.get("duration_seconds") or 5)
    motion = str(payload.get("camera_motion") or shot.get("movement") or "").lower()
    audio_mode = str(payload.get("audio_mode") or "none")
    shot_type = str(shot.get("shot_type") or "").lower()
    dialogue = str(shot.get("dialogue") or "").strip()

    high_motion_terms = (
        "tracking", "orbit", "crane", "drone", "handheld", "whip",
        "fast", "run", "chase", "complex", "סיבוב", "מרדף", "ידנית",
    )
    identity_sensitive_types = {"close-up", "reaction", "pov"}

    if audio_mode == "dialogue" or dialogue:
        return VideoModelSelection(
            "high_fidelity",
            "dialogue or lip-sync sensitive shot",
        )
    if shot_type in identity_sensitive_types:
        return VideoModelSelection(
            "high_fidelity",
            "identity-sensitive close framing",
        )
    if duration >= 8 or any(term in motion for term in high_motion_terms):
        return VideoModelSelection(
            "cinematic",
            "long duration or complex camera motion",
        )
    if duration <= 4 and not motion and audio_mode == "none":
        return VideoModelSelection(
            "fast",
            "short static silent shot",
        )
    return VideoModelSelection(
        "cinematic",
        "balanced default for production quality",
    )
