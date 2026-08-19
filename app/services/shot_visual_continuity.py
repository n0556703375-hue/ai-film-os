"""Wires app.services.visual_continuity_vision into real shot data.

Kept separate from app.services.continuity (the rule-based check) on purpose:
the rule-based checks are pure and heavily tested against plain shot dicts,
while this module needs database access (media results, neighbor shots) and
network calls (OpenAI, and video downloads for frame extraction). Mixing the
two would make the pure function's tests need to mock network calls too.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.repositories import shots
from app.services.continuity import _neighbor_shots
from app.services.video_frame_extraction import VideoFrameExtractionError, extract_frame_data_uri
from app.services.visual_continuity_vision import (
    OpenAIVisualContinuityAdapter,
    VisualContinuityAdapter,
    assess_visual_continuity,
)

logger = logging.getLogger(__name__)

_DOWNLOAD_TIMEOUT_SECONDS = 60.0
_MAX_VIDEO_BYTES = 200 * 1024 * 1024


def _latest_frame_url(shot_id: int) -> str | None:
    """Return a usable image URL (or an extracted video-frame data: URI) for
    the shot's most recent media result, or None if there isn't one yet."""
    results = shots.list_media_results(shot_id)
    if not results:
        return None
    latest = results[0]
    if latest["media_type"] == "image":
        return latest["url"]

    try:
        with httpx.Client(timeout=_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = client.get(latest["url"])
        if response.status_code >= 300 or len(response.content) > _MAX_VIDEO_BYTES:
            return None
        return extract_frame_data_uri(response.content)
    except (httpx.RequestError, VideoFrameExtractionError):
        return None


def visual_continuity_ai_issues(
    shot_id: int,
    *,
    adapter: VisualContinuityAdapter | None = None,
) -> list[dict[str, Any]]:
    """Best-effort AI visual continuity issues for a shot vs. its neighbors.

    Returns [] rather than raising whenever the check can't run — no API key
    configured, no media generated yet for a shot, or a transient provider
    failure. This is a preview enhancement, not a required check.
    """
    if adapter is None:
        if not settings.openai_api_key:
            return []
        adapter = OpenAIVisualContinuityAdapter()

    current = shots.get_shot(shot_id)
    if not current:
        return []

    previous, following = _neighbor_shots(current)
    issues: list[dict[str, Any]] = []
    for neighbor, relation in ((previous, "הקודם"), (following, "הבא")):
        if not neighbor:
            continue
        current_frame = _latest_frame_url(shot_id)
        neighbor_frame = _latest_frame_url(neighbor["id"])
        if not current_frame or not neighbor_frame:
            continue
        try:
            issues.extend(assess_visual_continuity(
                current_url=current_frame,
                neighbor_url=neighbor_frame,
                adapter=adapter,
                relation=relation,
                neighbor_shot_id=neighbor["id"],
                neighbor_shot_number=neighbor.get("shot_number"),
            ))
        except Exception as exc:
            logger.warning(f"AI visual continuity check failed for shot {shot_id} vs {neighbor['id']}: {exc}")
    return issues
