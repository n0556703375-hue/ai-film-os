"""Suggests which project assets (characters/locations/props/wardrobe) a
shot needs, by matching asset names against the shot's own free-text
fields — the same fields a human would read to decide this manually
(action, dialogue, camera notes, prompt, ...).

Deliberately rule-based rather than AI: it's exact-name matching, so it's
free, instant, and needs no API key — unlike the identity-drift/visual-
continuity checks, which need to judge an image and can't be done by
string matching.
"""

from __future__ import annotations

import re

# Every free-text field a human would read to figure out what a shot needs.
_TEXT_FIELDS = (
    "action", "dialogue", "notes", "camera", "camera_angle", "composition",
    "lighting", "movement", "mood", "color_palette", "audio", "prompt",
)

_MIN_NAME_LENGTH = 2


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _shot_text(shot: dict) -> str:
    return " ".join(_normalize(shot.get(field)) for field in _TEXT_FIELDS if shot.get(field))


def suggest_shot_asset_ids(shot: dict, project_assets: list[dict]) -> list[int]:
    """Return ids of project assets whose name appears in the shot's text.

    Pure function: takes plain dicts, does no I/O. project_assets is every
    asset in the shot's project (any asset_type) — callers don't need to
    pre-filter by type.
    """
    text = _shot_text(shot)
    if not text:
        return []

    matched: list[int] = []
    for asset in project_assets:
        name = _normalize(asset.get("name"))
        if len(name) < _MIN_NAME_LENGTH:
            continue
        # Allows up to two leading Hebrew prefix letters (ב/כ/ל/מ/ש/ו/ה —
        # "in/as/to/from/that/and/the") glued directly onto the noun with no
        # space ("בסכין"="with the knife", "והבית"="and the house") — a
        # plain \b-style boundary would miss almost every such mention,
        # which is most of them in ordinary shot description prose.
        if re.search(rf"(?<!\w)[בכלמשוה]{{0,2}}{re.escape(name)}(?!\w)", text):
            matched.append(int(asset["id"]))
    return matched
