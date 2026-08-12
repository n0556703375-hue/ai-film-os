"""Orchestrates the two-stage screenplay import flow: parse -> preview ->
review -> approve. This is the service layer app/api/screenplay_imports.py
calls; it owns no HTTP concerns and does no I/O beyond the repositories it
composes.

Stage A (parse) never writes to production tables (scenes/shots/etc.) — it
only creates/updates an import_runs row holding the full structured preview.
Stage B (approve) is the only place that touches production tables, and does
so in one atomic transaction (see app.repositories.screenplay_structure.
commit_breakdown).
"""

from __future__ import annotations

import hashlib

from app.repositories import import_runs as import_runs_repo
from app.repositories import scenes as scene_repo
from app.repositories import screenplay_structure
from app.services.screenplay_parser import ScreenplayParseError, parse_screenplay

_ACTIVE_STATUSES = {"review_required", "draft"}


class ImportRunNotFound(ValueError):
    def __init__(self, import_run_id: int):
        self.import_run_id = import_run_id
        super().__init__(f"import run {import_run_id} not found")


class ImportRunNotEditable(ValueError):
    """The run is not in a state that can be re-parsed or approved."""

    def __init__(self, import_run_id: int, status: str):
        self.import_run_id = import_run_id
        self.status = status
        super().__init__(f"import run {import_run_id} is {status}")


class ImportRunConflict(ValueError):
    """Approval requires explicit confirmation, or is blocked outright.

    reason:
      - "confirmation_required": the new breakdown changes or removes
        existing scenes; the caller must re-request with confirm=True.
      - "downstream_data_protected": at least one scene the new breakdown
        would remove has shots (or further downstream data) attached — this
        is refused unconditionally, confirmation cannot override it.
    """

    def __init__(self, reason: str, diff: dict, protected_scene_ids: list[int] | None = None):
        self.reason = reason
        self.diff = diff
        self.protected_scene_ids = protected_scene_ids or []
        super().__init__(reason)


class ScreenplayImportError(ValueError):
    """Carries a stable error category — see app/api/screenplay_imports.py."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def create_import_run(
    project_id: int,
    screenplay_text: str,
    *,
    source_type: str = "paste",
    source_filename: str = "",
    force: bool = False,
) -> dict:
    """Parse a screenplay and store the preview server-side. No production writes.

    Idempotency (identical text to an already-approved run short-circuits
    without re-parsing) is skipped when ``force`` is True. This is the
    escape hatch for the one case idempotency-by-hash can't distinguish
    on its own: the *parser* changed since the text was approved, and the
    caller explicitly wants a fresh preview to see the new result — not
    a second accidental submission of the same text, which is what the
    hash check exists to catch.
    """
    source_hash = _hash_text(screenplay_text)

    if not force:
        existing_approved = import_runs_repo.find_approved_run_by_hash(project_id, source_hash)
        if existing_approved:
            return {**existing_approved, "duplicate_of_import_run_id": existing_approved["id"]}

    try:
        parsed = parse_screenplay(screenplay_text)
    except ScreenplayParseError as exc:
        category = str(exc) if str(exc) == "empty_script" else "scene_detection_failed"
        raise ScreenplayImportError(category) from exc

    breakdown = parsed.to_dict()
    warnings = breakdown["warnings"]
    return import_runs_repo.create_import_run(
        project_id,
        source_type=source_type,
        source_filename=source_filename,
        source_hash=source_hash,
        screenplay_text=screenplay_text,
        breakdown=breakdown,
        warnings=warnings,
        scene_count=len(breakdown["scenes"]),
        character_count=len(breakdown["characters"]),
        location_count=len(breakdown["locations"]),
        prop_count=len(breakdown["props"]),
        status="review_required",
    )


def reparse_import_run(import_run_id: int, screenplay_text: str | None = None) -> dict:
    run = import_runs_repo.get_import_run(import_run_id)
    if not run:
        raise ImportRunNotFound(import_run_id)
    if run["status"] not in _ACTIVE_STATUSES:
        raise ImportRunNotEditable(import_run_id, run["status"])

    text = screenplay_text if screenplay_text is not None else run["screenplay_text"]
    source_hash = _hash_text(text)

    try:
        parsed = parse_screenplay(text)
    except ScreenplayParseError as exc:
        category = str(exc) if str(exc) == "empty_script" else "scene_detection_failed"
        raise ScreenplayImportError(category) from exc

    breakdown = parsed.to_dict()
    return import_runs_repo.update_import_run(import_run_id, {
        "screenplay_text": text,
        "source_hash": source_hash,
        "breakdown": breakdown,
        "warnings": breakdown["warnings"],
        "scene_count": len(breakdown["scenes"]),
        "character_count": len(breakdown["characters"]),
        "location_count": len(breakdown["locations"]),
        "prop_count": len(breakdown["props"]),
        "status": "review_required",
    })


def _scene_content_equal(existing_row: dict, new_scene: dict) -> bool:
    """Compare a persisted scene against a freshly parsed one.

    Deliberately does NOT compare raw_scene_text: that field embeds the
    scene's own original heading line, including whatever number the
    source screenplay had at that point — so a scene shifted from #1 to #2
    purely because an earlier scene was inserted would show a raw_scene_text
    difference despite having identical semantic content. scene_number *is*
    still compared (a renumber is real, useful-to-see information — it's
    reported as "changed" and the row is updated in place, preserving id),
    but the actual content comparison is done block-by-block instead of via
    the numbered raw text blob.
    """
    fields = ("scene_number", "normalized_heading", "int_ext", "location", "time_of_day")
    if any((existing_row.get(field) or "") != (new_scene.get(field) or "") for field in fields):
        return False

    existing_blocks = screenplay_structure.list_scene_content_blocks(existing_row["id"])
    new_blocks = new_scene.get("blocks", [])
    if len(existing_blocks) != len(new_blocks):
        return False
    for old_block, new_block in zip(existing_blocks, new_blocks):
        old_tuple = (
            old_block["block_type"], old_block["character_name"],
            old_block["raw_text"], old_block["parenthetical"],
        )
        new_tuple = (
            new_block.get("block_type", ""), new_block.get("character_name", ""),
            new_block.get("raw_text", ""), new_block.get("parenthetical", ""),
        )
        if old_tuple != new_tuple:
            return False
    return True


def compute_diff(project_id: int, new_scenes: list[dict]) -> dict:
    """Match new (parsed) scenes against a project's current scenes.

    Matches primarily by normalized_heading (content identity — survives a
    scene being renumbered by an insertion earlier in the screenplay), with
    scene_number as a fallback for scenes whose heading doesn't match
    anything. Anything left unmatched on either side is added/removed.

    Runs as two complete passes over all new scenes — every possible
    heading match is claimed first, and only *then* is scene_number
    fallback attempted for what's left. Interleaving the two per scene (try
    heading, else fall back to position, move to the next scene) is unsafe:
    an early new scene with no heading match would greedily claim an
    existing scene by position, stealing it away from a later new scene
    that was actually its correct heading match — misattributing which
    scene changed and which was added/removed.
    """
    existing = scene_repo.list_scenes(project_id)
    existing_by_heading: dict[str, dict] = {}
    existing_by_number: dict[int, dict] = {}
    for row in existing:
        heading_key = (row.get("normalized_heading") or "").strip()
        if heading_key and heading_key not in existing_by_heading:
            existing_by_heading[heading_key] = row
        existing_by_number.setdefault(row["scene_number"], row)

    matched_ids: set[int] = set()
    match_by_new_index: dict[int, dict] = {}

    for index, scene in enumerate(new_scenes):
        heading_key = (scene.get("normalized_heading") or "").strip()
        if not heading_key:
            continue
        candidate = existing_by_heading.get(heading_key)
        if candidate and candidate["id"] not in matched_ids:
            match_by_new_index[index] = candidate
            matched_ids.add(candidate["id"])

    for index, scene in enumerate(new_scenes):
        if index in match_by_new_index:
            continue
        candidate = existing_by_number.get(scene["scene_number"])
        if candidate and candidate["id"] not in matched_ids:
            match_by_new_index[index] = candidate
            matched_ids.add(candidate["id"])

    added: list[dict] = []
    changed: list[tuple[int, dict]] = []
    unchanged: list[tuple[int, dict]] = []

    for index, scene in enumerate(new_scenes):
        match = match_by_new_index.get(index)
        if match is None:
            added.append(scene)
            continue
        if _scene_content_equal(match, scene):
            unchanged.append((match["id"], scene))
        else:
            changed.append((match["id"], scene))

    removed = [row for row in existing if row["id"] not in matched_ids]

    return {
        "added": added,
        "changed": changed,
        "unchanged": unchanged,
        "removed": removed,
        "has_differences": bool(added or changed or removed),
        "requires_confirmation": bool(changed or removed),
    }


def preview_diff(import_run_id: int) -> dict:
    run = import_runs_repo.get_import_run(import_run_id)
    if not run:
        raise ImportRunNotFound(import_run_id)
    return compute_diff(run["project_id"], run["breakdown"].get("scenes", []))


def _diff_summary(diff: dict) -> dict:
    return {
        "added": len(diff["added"]),
        "changed": len(diff["changed"]),
        "unchanged": len(diff["unchanged"]),
        "removed": len(diff["removed"]),
        "removed_scene_numbers": sorted(row["scene_number"] for row in diff["removed"]),
    }


def approve_import_run(import_run_id: int, *, confirm: bool = False) -> dict:
    run = import_runs_repo.get_import_run(import_run_id)
    if not run:
        raise ImportRunNotFound(import_run_id)
    if run["status"] not in _ACTIVE_STATUSES:
        raise ImportRunNotEditable(import_run_id, run["status"])

    project_id = run["project_id"]
    breakdown = run["breakdown"]
    new_scenes = breakdown.get("scenes", [])
    characters = breakdown.get("characters", [])
    locations = breakdown.get("locations", [])
    props = breakdown.get("props", [])

    diff = compute_diff(project_id, new_scenes)

    if diff["requires_confirmation"]:
        if not confirm:
            raise ImportRunConflict("confirmation_required", diff)
        protected = [
            row["id"] for row in diff["removed"]
            if screenplay_structure.has_downstream_data(row["id"])
        ]
        if protected:
            raise ImportRunConflict("downstream_data_protected", diff, protected_scene_ids=protected)

    plan = {
        "scenes_to_add": diff["added"],
        "scenes_to_update": diff["changed"],
        "scenes_to_remove": [row["id"] for row in diff["removed"]],
        "scenes_unchanged": diff["unchanged"],
        "characters": characters,
        "locations": locations,
        "props": props,
    }
    summary = screenplay_structure.commit_breakdown(project_id, import_run_id, plan)
    summary["diff"] = _diff_summary(diff)
    summary["import_run_id"] = import_run_id
    return summary
