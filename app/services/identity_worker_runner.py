from __future__ import annotations

from typing import Any

from app.api.identity_assessments import list_pending_identity_drift
from app.core.config import settings
from app.services.identity_vision import IdentityVisionAdapter
from app.services.identity_worker import process_identity_assessment
from app.services.openai_identity_vision import OpenAIIdentityVisionAdapter


def build_identity_vision_adapter(
    provider: str | None = None,
) -> IdentityVisionAdapter:
    """Build the configured identity adapter without exposing credentials."""
    selected = (provider or settings.identity_vision_provider).strip().lower()
    if selected == "openai":
        return OpenAIIdentityVisionAdapter()
    raise ValueError(f"Unsupported identity vision provider: {selected or '<empty>'}.")


def process_next_identity_assessment(
    *,
    worker_id: str,
    adapter: IdentityVisionAdapter | None = None,
) -> dict[str, Any]:
    """Process the oldest pending identity assessment, if one exists."""
    normalized_worker_id = worker_id.strip()
    if not normalized_worker_id:
        raise ValueError("worker_id is required.")

    queue = list_pending_identity_drift(limit=1)
    items = queue.get("items", [])
    if not items:
        return {"processed": False, "reason": "no_pending_identity_assessments"}

    item = items[0]
    result = process_identity_assessment(
        shot_id=int(item["shot_id"]),
        media_id=int(item["media_id"]),
        worker_id=normalized_worker_id,
        adapter=adapter or build_identity_vision_adapter(),
    )
    return {"processed": True, **result}
