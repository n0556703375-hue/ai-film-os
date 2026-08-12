"""Persistence for the structural screenplay breakdown: scenes' new
structural columns, content blocks, and canonical characters/locations.

Kept separate from app/repositories/scenes.py (which still owns the plain
scene CRUD used everywhere else) and from app/repositories/import_runs.py
(which owns the import_runs audit/preview row) because this module is
specifically the "apply an approved breakdown to production tables" layer.
"""

import json
from contextlib import closing

from app.database.connection import get_connection


def has_downstream_data(scene_id: int) -> bool:
    """True if a scene has any shots — the protection boundary for re-import.

    A shot existing (even before any media/approval) already represents
    production work; re-import must never silently delete a scene once this
    is true, regardless of explicit confirmation.
    """
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM shots WHERE scene_id=?", (scene_id,)
        ).fetchone()
    return bool(row["n"])


def list_scene_content_blocks(scene_id: int) -> list[dict]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM scene_content_blocks WHERE scene_id=? ORDER BY block_order",
            (scene_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_screenplay_characters(project_id: int) -> list[dict]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM screenplay_characters WHERE project_id=? ORDER BY canonical_name",
            (project_id,),
        ).fetchall()
    return [_decode_entity(row) for row in rows]


def list_screenplay_locations(project_id: int) -> list[dict]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM screenplay_locations WHERE project_id=? ORDER BY canonical_name",
            (project_id,),
        ).fetchall()
    return [_decode_entity(row) for row in rows]


def list_screenplay_props(project_id: int) -> list[dict]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM screenplay_props WHERE project_id=? ORDER BY canonical_name",
            (project_id,),
        ).fetchall()
    return [_decode_entity(row) for row in rows]


def _decode_entity(row) -> dict:
    data = dict(row)
    data["aliases"] = json.loads(data.pop("aliases_json") or "[]")
    return data


def commit_breakdown(project_id: int, import_run_id: int, plan: dict) -> dict:
    """Apply an approved breakdown to production tables in one transaction.

    ``plan`` (built by app.services.screenplay_import_service):
        scenes_to_add: list of scene dicts (parser output shape)
        scenes_to_update: list of (existing_scene_id, scene dict) pairs
        scenes_to_remove: list of existing scene ids (already verified to
            carry no downstream shots — this function does not re-check)
        scenes_unchanged: list of (existing_scene_id, scene dict) pairs —
            content_blocks/character links are left untouched for these
        characters / locations / props: the full canonical breakdown entity
            lists (project-wide; upserted regardless of which scenes changed)

    Every character, location, and prop the breakdown reports also gets a
    matching Story Bible card in ``assets`` if one doesn't already exist by
    name (see ``_sync_story_bible_assets``) — this is what keeps the Story
    Bible from silently missing entities a re-parsed/updated screenplay
    introduces. An existing card is never modified or re-created: a
    creator's manual edits (description, visual rules, approval, lock) are
    never overwritten by a script re-import.

    Either the whole plan is applied and import_run_id becomes 'approved',
    or nothing is: any exception propagates before the transaction commits,
    and — matching the rest of this codebase's transaction pattern (see
    app/repositories/jobs.py claim_next_job) — the connection is closed
    without a commit, which discards the uncommitted work.
    """
    with closing(get_connection()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        for scene_id in plan.get("scenes_to_remove", []):
            conn.execute("DELETE FROM scenes WHERE id=?", (scene_id,))

        scene_id_by_number: dict[int, int] = {}

        for scene_id, scene in plan.get("scenes_to_update", []):
            title = (scene.get("normalized_heading") or scene.get("original_heading")
                     or f"סצנה {scene['scene_number']}")[:300]
            conn.execute(
                """
                UPDATE scenes SET
                    scene_number=?, title=?,
                    original_heading=?, normalized_heading=?, int_ext=?, location=?,
                    time_of_day=?, raw_scene_text=?, import_run_id=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    scene["scene_number"], title,
                    scene.get("original_heading", ""), scene.get("normalized_heading", ""),
                    scene.get("int_ext", ""), scene.get("location", ""),
                    scene.get("time_of_day", ""), scene.get("raw_scene_text", ""),
                    import_run_id, scene_id,
                ),
            )
            _replace_blocks(conn, scene_id, scene.get("blocks", []))
            scene_id_by_number[scene["scene_number"]] = scene_id

        for scene in plan.get("scenes_to_add", []):
            title = (scene.get("normalized_heading") or scene.get("original_heading")
                     or f"סצנה {scene['scene_number']}")[:300]
            cur = conn.execute(
                """
                INSERT INTO scenes (
                    project_id, scene_number, title, status,
                    original_heading, normalized_heading, int_ext, location,
                    time_of_day, raw_scene_text, synopsis, import_run_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    project_id, scene["scene_number"], title, "מתוכנן",
                    scene.get("original_heading", ""), scene.get("normalized_heading", ""),
                    scene.get("int_ext", ""), scene.get("location", ""),
                    scene.get("time_of_day", ""), scene.get("raw_scene_text", ""),
                    scene.get("synopsis", ""), import_run_id,
                ),
            )
            scene_id = cur.lastrowid
            _replace_blocks(conn, scene_id, scene.get("blocks", []))
            scene_id_by_number[scene["scene_number"]] = scene_id

        for scene_id, scene in plan.get("scenes_unchanged", []):
            scene_id_by_number[scene["scene_number"]] = scene_id

        character_id_by_canonical: dict[str, int] = {}
        for character in plan.get("characters", []):
            character_id_by_canonical[character["canonical_name"]] = _upsert_entity_in_conn(
                conn, "screenplay_characters", project_id, character
            )
        for location in plan.get("locations", []):
            _upsert_entity_in_conn(conn, "screenplay_locations", project_id, location)
        for prop in plan.get("props", []):
            _upsert_entity_in_conn(conn, "screenplay_props", project_id, prop)

        assets_created = _sync_story_bible_assets_in_conn(conn, project_id, plan)

        name_to_canonical = _build_alias_lookup(plan.get("characters", []))
        all_scenes = (
            plan.get("scenes_to_add", [])
            + [scene for _sid, scene in plan.get("scenes_to_update", [])]
            + [scene for _sid, scene in plan.get("scenes_unchanged", [])]
        )
        for scene in all_scenes:
            scene_id = scene_id_by_number.get(scene["scene_number"])
            if scene_id is None:
                continue
            character_ids = []
            for raw_name in scene.get("participants", []):
                canonical = name_to_canonical.get(raw_name, raw_name)
                character_id = character_id_by_canonical.get(canonical)
                if character_id is not None:
                    character_ids.append(character_id)
            conn.execute("DELETE FROM scene_characters WHERE scene_id=?", (scene_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO scene_characters (scene_id, screenplay_character_id) VALUES (?,?)",
                [(scene_id, character_id) for character_id in character_ids],
            )

        conn.execute(
            "UPDATE import_runs SET status='approved', approved_at=CURRENT_TIMESTAMP, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (import_run_id,),
        )
        conn.execute(
            "UPDATE import_runs SET status='superseded', updated_at=CURRENT_TIMESTAMP "
            "WHERE project_id=? AND status='approved' AND id<>?",
            (project_id, import_run_id),
        )

        conn.commit()

    return {
        "scenes_added": len(plan.get("scenes_to_add", [])),
        "scenes_removed": len(plan.get("scenes_to_remove", [])),
        "scenes_changed": len(plan.get("scenes_to_update", [])),
        "scenes_unchanged": len(plan.get("scenes_unchanged", [])),
        "characters_created": len(plan.get("characters", [])),
        "locations_created": len(plan.get("locations", [])),
        "props_created": len(plan.get("props", [])),
        "story_bible_cards_created": assets_created,
    }


def _replace_blocks(conn, scene_id: int, blocks: list[dict]) -> None:
    conn.execute("DELETE FROM scene_content_blocks WHERE scene_id=?", (scene_id,))
    conn.executemany(
        """
        INSERT INTO scene_content_blocks (
            scene_id, block_order, block_type, character_name, parenthetical,
            raw_text, confidence
        ) VALUES (?,?,?,?,?,?,?)
        """,
        [
            (
                scene_id, block["order"], block["block_type"],
                block.get("character_name", ""), block.get("parenthetical", ""),
                block.get("raw_text", ""), block.get("confidence", "high"),
            )
            for block in blocks
        ],
    )


# Maps a breakdown entity list (plan key) to the Story Bible asset_type it
# should surface as. Keeping this in one place is what makes the sync below
# treat characters, locations, and props identically instead of only some
# of them getting cards.
_ENTITY_PLAN_KEY_TO_ASSET_TYPE = {
    "characters": "דמות",
    "locations": "לוקיישן",
    "props": "אביזר",
}


def _sync_story_bible_assets_in_conn(conn, project_id: int, plan: dict) -> int:
    """Create a Story Bible ``assets`` card for any breakdown entity that
    doesn't already have one by (project, asset_type, name).

    Deliberately additive-only: an existing card is left completely
    untouched (never renamed, re-approved, or reset), so this can run on
    every approved import — including a re-parse of an already-known
    screenplay — without clobbering anything a user already curated.
    """
    created = 0
    for plan_key, asset_type in _ENTITY_PLAN_KEY_TO_ASSET_TYPE.items():
        for entity in plan.get(plan_key, []):
            name = entity["canonical_name"]
            existing = conn.execute(
                "SELECT 1 FROM assets WHERE project_id=? AND asset_type=? AND name=?",
                (project_id, asset_type, name),
            ).fetchone()
            if existing:
                continue
            conn.execute(
                """
                INSERT INTO assets (project_id, asset_type, name, approved)
                VALUES (?, ?, ?, 0)
                """,
                (project_id, asset_type, name),
            )
            created += 1
    return created


def _upsert_entity_in_conn(conn, table: str, project_id: int, entity: dict) -> int:
    canonical_name = entity["canonical_name"]
    aliases = entity.get("aliases", [])
    first_scene = entity.get("first_appearance_scene_number")
    existing = conn.execute(
        f"SELECT * FROM {table} WHERE project_id=? AND canonical_name=?",
        (project_id, canonical_name),
    ).fetchone()
    if existing:
        merged_aliases = sorted(set(json.loads(existing["aliases_json"] or "[]")) | set(aliases))
        existing_first = existing["first_appearance_scene_number"]
        merged_first = min(existing_first, first_scene) if existing_first is not None else first_scene
        conn.execute(
            f"UPDATE {table} SET aliases_json=?, first_appearance_scene_number=?, "
            f"updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(merged_aliases, ensure_ascii=False), merged_first, existing["id"]),
        )
        return existing["id"]
    cur = conn.execute(
        f"INSERT INTO {table} (project_id, canonical_name, aliases_json, first_appearance_scene_number) "
        f"VALUES (?,?,?,?)",
        (project_id, canonical_name, json.dumps(aliases, ensure_ascii=False), first_scene),
    )
    return cur.lastrowid


def _build_alias_lookup(characters: list[dict]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for character in characters:
        canonical = character["canonical_name"]
        lookup[canonical] = canonical
        for alias in character.get("aliases", []):
            lookup[alias] = canonical
    return lookup
