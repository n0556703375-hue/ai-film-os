from __future__ import annotations

from app.repositories.scene_asset_variants import list_scene_variants


def apply_scene_asset_variants(shot: dict) -> dict:
    """Return a prompt-safe shot copy with scene variants overlaid on linked assets."""
    scene_id = shot.get("scene_id")
    if not scene_id:
        return shot

    variants = {int(item["asset_id"]): item for item in list_scene_variants(int(scene_id))}
    if not variants:
        return shot

    propagated = dict(shot)
    propagated_assets = []
    for asset in shot.get("assets", []):
        variant = variants.get(int(asset["id"])) if asset.get("id") is not None else None
        if not variant:
            propagated_assets.append(asset)
            continue

        effective = dict(asset)
        state_name = (variant.get("state_name") or "").strip()
        if state_name:
            effective["name"] = f"{asset['name']} — {state_name}"
        if variant.get("description"):
            effective["description"] = variant["description"]
        if variant.get("visual_rules"):
            effective["visual_rules"] = variant["visual_rules"]
        if variant.get("reference_url"):
            effective["reference_url"] = variant["reference_url"]
        effective["scene_variant_id"] = variant["id"]
        effective["source_asset_id"] = asset["id"]
        propagated_assets.append(effective)

    propagated["assets"] = propagated_assets
    return propagated
