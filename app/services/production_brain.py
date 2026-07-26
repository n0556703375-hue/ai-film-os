"""Read-only Production Brain v1.

The first version is intentionally deterministic and side-effect free. It turns a
project snapshot into operator-facing blockers and safe next actions. No provider
calls, generation requests, approvals, or data mutations happen here.
"""

from __future__ import annotations

from typing import Any


READY_FOR_IMAGE_STATUSES = {"מתוכנן", "פרומפט מוכן", "planned", "prompt_ready"}
BLOCKED_STATUSES = {"חסום", "blocked"}


def _asset_is_locked(asset: dict[str, Any]) -> bool:
    return asset.get("lock_status") == "locked" and bool(asset.get("master_reference_id"))


def _shot_assets(shot: dict[str, Any], assets_by_id: dict[int, dict[str, Any]]):
    asset_ids = shot.get("asset_ids") or []
    return [assets_by_id[asset_id] for asset_id in asset_ids if asset_id in assets_by_id]


def evaluate_production_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic production blockers and safe recommendations.

    Expected snapshot keys are ``project``, ``assets`` and ``shots``. Unknown fields
    are ignored so the contract can grow additively.
    """
    project = dict(snapshot.get("project") or {})
    assets = [dict(item) for item in (snapshot.get("assets") or [])]
    shots = [dict(item) for item in (snapshot.get("shots") or [])]
    assets_by_id = {item.get("id"): item for item in assets if item.get("id") is not None}

    blockers: list[dict[str, Any]] = []
    ready_actions: list[dict[str, Any]] = []

    for asset in assets:
        if asset.get("asset_type") not in {"דמות", "character"}:
            continue
        if not _asset_is_locked(asset):
            blockers.append({
                "type": "missing_character_lock",
                "asset_id": asset.get("id"),
                "message": f"לדמות {asset.get('name') or asset.get('id')} אין רפרנס מאסטר נעול.",
                "blocks": ["shot_image_generation"],
            })

    for shot in shots:
        status = shot.get("status") or "planned"
        if status in BLOCKED_STATUSES:
            blockers.append({
                "type": "shot_blocked",
                "shot_id": shot.get("id"),
                "message": "השוט מסומן כחסום ודורש טיפול לפני המשך הפקה.",
                "blocks": ["shot_image_generation", "video_generation"],
            })
            continue

        linked_assets = _shot_assets(shot, assets_by_id)
        unlocked = [asset for asset in linked_assets if not _asset_is_locked(asset)]
        if unlocked:
            blockers.append({
                "type": "shot_missing_locked_references",
                "shot_id": shot.get("id"),
                "asset_ids": [asset.get("id") for asset in unlocked],
                "message": "לשוט חסרים רפרנסים נעולים לכל הנכסים המקושרים.",
                "blocks": ["shot_image_generation"],
            })
            continue

        if status in READY_FOR_IMAGE_STATUSES and not shot.get("approved_image_id"):
            ready_actions.append({
                "type": "generate_shot_image",
                "shot_id": shot.get("id"),
                "requires_confirmation": True,
            })

    return {
        "project_id": project.get("id"),
        "project_status": "blocked" if blockers else "ready",
        "blockers": blockers,
        "ready_actions": ready_actions,
        "read_only": True,
    }
