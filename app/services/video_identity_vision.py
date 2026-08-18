"""Video counterpart of app.services.identity_vision.evaluate_shot_identity.

Deliberately a thin wrapper, not a parallel implementation: a representative
frame is extracted from the generated video and handed to the exact same
evaluate_shot_identity() the image flow already uses — same locked-character
reference gathering, same adapter, same assess_identity_drift aggregation,
same result shape. The only genuinely new piece here is turning video bytes
into one still frame (app.services.video_frame_extraction), since OpenAI's
vision comparison operates on a still image either way.

The frame never needs to be persisted or publicly hosted: it's passed to the
adapter as a data: URI (see video_frame_extraction.extract_frame_data_uri),
which OpenAI's Responses API accepts directly in place of an image URL.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.identity_drift import DEFAULT_MIN_IDENTITY_SIMILARITY
from app.services.identity_vision import IdentityVisionAdapter, evaluate_shot_identity
from app.services.video_frame_extraction import extract_frame_data_uri

_DOWNLOAD_TIMEOUT_SECONDS = 60.0
_MAX_VIDEO_BYTES = 200 * 1024 * 1024  # matches video_persistence.MAX_VIDEO_BYTES


class VideoIdentityEvaluationError(RuntimeError):
    """A stable, sanitized reason the video could not be fetched for evaluation."""

    UNREACHABLE = "video_unreachable"
    TOO_LARGE = "video_too_large"

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"video_identity_evaluation_error: {reason}")


def _download_video(video_url: str) -> bytes:
    try:
        with httpx.Client(timeout=_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = client.get(video_url)
    except httpx.RequestError as exc:
        raise VideoIdentityEvaluationError(VideoIdentityEvaluationError.UNREACHABLE) from exc
    if response.status_code >= 300:
        raise VideoIdentityEvaluationError(VideoIdentityEvaluationError.UNREACHABLE)
    content = response.content
    if len(content) > _MAX_VIDEO_BYTES:
        raise VideoIdentityEvaluationError(VideoIdentityEvaluationError.TOO_LARGE)
    return content


def evaluate_shot_video_identity(
    *,
    shot: dict[str, Any],
    candidate_video_url: str,
    adapter: IdentityVisionAdapter,
    min_similarity: float = DEFAULT_MIN_IDENTITY_SIMILARITY,
) -> dict[str, Any]:
    """Evaluate a generated shot video against every locked character master.

    Same contract as evaluate_shot_identity: no database writes, no
    provider credentials known here. Raises VideoIdentityEvaluationError or
    VideoFrameExtractionError before ever reaching the adapter if the video
    can't be fetched or decoded — those are caller-visible failures distinct
    from a completed-but-blocked identity assessment.
    """
    if not candidate_video_url.strip():
        raise ValueError("candidate_video_url is required.")

    video_bytes = _download_video(candidate_video_url)
    frame_data_uri = extract_frame_data_uri(video_bytes)

    return evaluate_shot_identity(
        shot=shot,
        candidate_url=frame_data_uri,
        adapter=adapter,
        min_similarity=min_similarity,
    )
