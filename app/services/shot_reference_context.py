"""Load scene-level reference variants for an already-loaded shot.

This helper is read-only. It copies shot and asset dictionaries, loads only
variants belonging to the shot's own scene and linked assets, then delegates
ordering and Character Lock isolation to the propagation contract.
"""

from __future__ import annotations

from contextlib import closing
from typing import Any

from app.database.connection import get_connection
from app.database.query import execute_query
from app.services.reference_propagation import apply_scene_reference_propagation


def build_shot_reference_context(shot: dict[str, Any]) -> dict[str, Any]:
    result = dict(shot)
    assets = [dict(asset) for asset in (shot.get("assets") or [])]
    scene_id = shot.get("scene_id")
    asset_ids = [asset.get("id") for asset in assets if asset.get("id") is not None]

    variants_by_asset_id: dict[int, dict[str, Any]] = {}
    if scene_id is not None and asset_ids:
        placeholders = ",".join("?" for _ in asset_ids)
        with closing(get_connection()) as conn:
            rows = execute_query(
                conn,
                f"""
                SELECT scene_id, asset_id, state_name, description,
                       reference_url, visual_rules, updated_at
                FROM scene_asset_variants
                WHERE scene_id=? AND asset_id IN ({placeholders})
                ORDER BY asset_id
                """,
                (scene_id, *asset_ids),
            ).fetchall()
        variants_by_asset_id = {row["asset_id"]: dict(row) for row in rows}

    for asset in assets:
        variant = variants_by_asset_id.get(asset.get("id"))
        if variant is not None:
            asset["scene_variant"] = variant

    result["assets"] = apply_scene_reference_propagation(assets)
    return result
