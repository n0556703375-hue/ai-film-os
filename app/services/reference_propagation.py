"""Deterministic reference selection for shot generation.

This module is intentionally storage- and provider-agnostic. It applies the
Location and Wardrobe Lock propagation rules to already-loaded asset records
without mutating them or performing any external calls.
"""

from __future__ import annotations

from typing import Any


SCENE_VARIANT_ASSET_TYPES = {"לוקיישן", "לבוש", "location", "wardrobe"}


def _clean_urls(values: list[Any]) -> list[str]:
    urls: list[str] = []
    for value in values:
        url = str(value or "").strip()
        if url and url not in urls:
            urls.append(url)
    return urls


def select_generation_references(asset: dict[str, Any]) -> list[str]:
    """Return ordered, deduplicated reference URLs for one shot asset.

    Character identity remains governed exclusively by the approved locked
    master references already exposed through ``reference_images``. Location
    and wardrobe assets may prepend a scene-level state reference while keeping
    the locked/master fallback behind it.
    """
    master_urls = _clean_urls(
        [*(asset.get("reference_images") or []), asset.get("reference_url")]
    )

    if asset.get("asset_type") not in SCENE_VARIANT_ASSET_TYPES:
        return master_urls

    variant = asset.get("scene_variant") or {}
    variant_url = str(variant.get("reference_url") or "").strip()
    if not variant_url:
        return master_urls

    return _clean_urls([variant_url, *master_urls])


def apply_scene_reference_propagation(
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return copied assets with generation-ready references attached."""
    propagated: list[dict[str, Any]] = []
    for source in assets:
        asset = dict(source)
        asset["generation_reference_images"] = select_generation_references(asset)
        propagated.append(asset)
    return propagated
