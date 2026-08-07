from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from app.services.screenplay_breakdown import (
    _breakdown_chunk,
    _normalize_scenes,
    _split_screenplay,
)


@dataclass
class ImportRunState:
    project_id: int
    screenplay: str
    target_shots_per_minute: float = 5.0
    next_chunk_index: int = 0
    scenes: list[dict[str, Any]] = field(default_factory=list)

    @property
    def chunks(self) -> list[str]:
        return _split_screenplay(self.screenplay)

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    @property
    def completed(self) -> bool:
        return self.next_chunk_index >= self.chunk_count

    @property
    def screenplay_fingerprint(self) -> str:
        """Stable digest used to prevent resuming against changed screenplay text."""
        return hashlib.sha256(self.screenplay.encode("utf-8")).hexdigest()


def process_next_chunk(project: dict, state: ImportRunState) -> ImportRunState:
    """Process exactly one screenplay chunk and return resumable state.

    This function is deliberately side-effect free. It never persists scenes or
    mutates production records, so a retry can safely re-run only the failed
    chunk before persistence begins.
    """
    chunks = state.chunks
    if not chunks:
        raise ValueError("התסריט ריק.")
    if state.completed:
        return state

    chunk_index = state.next_chunk_index
    generated = _normalize_scenes(
        _breakdown_chunk(
            project,
            chunks[chunk_index],
            state.target_shots_per_minute,
            chunk_index + 1,
            len(chunks),
        ),
        start_number=len(state.scenes) + 1,
    )
    state.scenes.extend(generated)
    state.next_chunk_index += 1
    return state


def serialize_state(state: ImportRunState) -> dict[str, Any]:
    return {
        "project_id": state.project_id,
        "screenplay": state.screenplay,
        "screenplay_fingerprint": state.screenplay_fingerprint,
        "target_shots_per_minute": state.target_shots_per_minute,
        "next_chunk_index": state.next_chunk_index,
        "scenes": list(state.scenes),
    }


def restore_state(payload: dict[str, Any]) -> ImportRunState:
    state = ImportRunState(
        project_id=int(payload["project_id"]),
        screenplay=str(payload["screenplay"]),
        target_shots_per_minute=float(payload.get("target_shots_per_minute") or 5.0),
        next_chunk_index=max(0, int(payload.get("next_chunk_index") or 0)),
        scenes=[dict(item) for item in payload.get("scenes") or []],
    )
    expected_fingerprint = str(payload.get("screenplay_fingerprint") or "")
    if expected_fingerprint and expected_fingerprint != state.screenplay_fingerprint:
        raise ValueError("מצב הייבוא אינו תואם לתסריט הנוכחי.")
    return state
