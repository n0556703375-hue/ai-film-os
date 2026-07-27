from dataclasses import dataclass


@dataclass(frozen=True)
class VideoModelProfile:
    name: str
    reason: str


def select_video_model_profile(shot: dict, request: dict) -> VideoModelProfile:
    """Choose a provider-neutral model profile from explicit shot requirements.

    This function is deterministic and does not expose or depend on provider credentials.
    Explicit operator hints always win over inferred requirements.
    """
    hint = str(request.get("model_hint") or "auto")
    if hint != "auto":
        return VideoModelProfile(hint, "operator_hint")

    duration = float(request.get("duration_seconds") or 0)
    audio_mode = str(request.get("audio_mode") or "none")
    movement = " ".join(
        str(value or "")
        for value in (
            request.get("camera_motion"),
            shot.get("movement"),
            shot.get("camera"),
            shot.get("action"),
        )
    ).lower()

    high_motion_terms = (
        "handheld",
        "tracking",
        "dolly",
        "crane",
        "orbit",
        "whip",
        "run",
        "chase",
        "rapid",
        "fast",
    )
    fidelity_terms = (
        "close-up",
        "close up",
        "portrait",
        "face",
        "identity",
        "detail",
        "macro",
    )

    if any(term in movement for term in fidelity_terms) or audio_mode == "dialogue":
        return VideoModelProfile("high_fidelity", "identity_or_dialogue_detail")
    if duration >= 12 or any(term in movement for term in high_motion_terms):
        return VideoModelProfile("cinematic", "long_or_complex_motion")
    return VideoModelProfile("fast", "standard_short_shot")
