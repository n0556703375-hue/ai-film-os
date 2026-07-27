from __future__ import annotations

from typing import Any

from app.repositories import shots


def _names(assets: list[dict], asset_type: str) -> set[str]:
    return {
        asset["name"]
        for asset in assets
        if asset["asset_type"] == asset_type
    }


def check_shot_continuity(shot: dict) -> list[dict]:
    issues = []
    assets = shot.get("assets", [])
    shot_type = shot.get("shot_type", "רגיל")
    previous = shot.get("previous_shot")

    locations = _names(assets, "לוקיישן")
    characters = _names(assets, "דמות")
    props = _names(assets, "אביזר")
    wardrobe = _names(assets, "לבוש")

    if not locations:
        issues.append({"severity": "high", "category": "missing_location", "message": "לא שויך לוקיישן לשוט."})
    if not characters and shot_type not in {"Establishing", "Insert", "Transition"}:
        issues.append({"severity": "medium", "category": "missing_character", "message": "לא שויכה דמות לשוט."})

    unapproved = [a["name"] for a in assets if not a["approved"]]
    if unapproved:
        issues.append({"severity": "medium", "category": "unapproved_assets", "message": "נכסים לא מאושרים: " + ", ".join(unapproved)})
    if not shot.get("lighting"):
        issues.append({"severity": "low", "category": "missing_lighting", "message": "לא הוגדרה תאורה לשוט."})
    if not previous:
        return issues

    previous_assets = previous.get("assets", [])
    prev_locations = _names(previous_assets, "לוקיישן")
    prev_characters = _names(previous_assets, "דמות")
    prev_props = _names(previous_assets, "אביזר")
    prev_wardrobe = _names(previous_assets, "לבוש")

    if prev_locations and locations and prev_locations != locations:
        issues.append({
            "severity": "high", "category": "location_change",
            "message": f"שינוי לוקיישן לעומת שוט {previous['shot_number']}: {', '.join(sorted(prev_locations))} → {', '.join(sorted(locations))}. יש לוודא שהמעבר מכוון.",
        })
    missing_characters = prev_characters - characters
    if missing_characters and shot_type not in {"Insert", "POV", "Transition"}:
        issues.append({"severity": "medium", "category": "character_disappeared", "message": "דמויות שהופיעו בשוט הקודם אינן משויכות כעת: " + ", ".join(sorted(missing_characters))})
    missing_props = prev_props - props
    if missing_props:
        issues.append({"severity": "medium", "category": "prop_disappeared", "message": "אביזרים מהשוט הקודם נעלמו: " + ", ".join(sorted(missing_props))})
    if prev_wardrobe and wardrobe and prev_wardrobe != wardrobe:
        issues.append({"severity": "high", "category": "wardrobe_change", "message": "הלבוש שונה מהשוט הקודם. יש לוודא שהשינוי מכוון."})

    previous_lighting = (previous.get("lighting") or "").strip()
    current_lighting = (shot.get("lighting") or "").strip()
    if previous_lighting and current_lighting and previous_lighting != current_lighting:
        issues.append({"severity": "low", "category": "lighting_change", "message": "הגדרת התאורה שונה מהשוט הקודם."})
    return issues


TRACKED_FIELDS = (
    ("lighting", "תאורה"),
    ("mood", "אווירה"),
    ("camera_angle", "זווית מצלמה"),
    ("composition", "קומפוזיציה"),
    ("color_palette", "פלטת צבעים"),
    ("movement", "תנועת מצלמה"),
)

EYELINE_MARKERS = {
    "left": ("eyeline left", "looking left", "looks left", "מבט שמאלה", "מביטה שמאלה"),
    "right": ("eyeline right", "looking right", "looks right", "מבט ימינה", "מביטה ימינה"),
}

SCREEN_DIRECTION_MARKERS = {
    "left": ("moves left", "moving left", "travels left", "enters from right", "יוצאת שמאלה", "נעה שמאלה", "נכנסת מימין"),
    "right": ("moves right", "moving right", "travels right", "enters from left", "יוצאת ימינה", "נעה ימינה", "נכנסת משמאל"),
}


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _direction_marker(values: tuple[Any, ...], markers: dict[str, tuple[str, ...]]) -> str | None:
    text = " ".join(_normalized(value) for value in values if value)
    if not text:
        return None
    matches = [direction for direction, phrases in markers.items() if any(phrase in text for phrase in phrases)]
    return matches[0] if len(matches) == 1 else None


def _direction_issues(source: dict, target: dict, relation: str) -> list[dict]:
    issues: list[dict] = []
    source_eyeline = _direction_marker(
        (source.get("camera_angle"), source.get("composition"), source.get("action")),
        EYELINE_MARKERS,
    )
    target_eyeline = _direction_marker(
        (target.get("camera_angle"), target.get("composition"), target.get("action")),
        EYELINE_MARKERS,
    )
    if source_eyeline and target_eyeline and source_eyeline != target_eyeline:
        issues.append({
            "severity": "medium",
            "category": "eyeline_direction",
            "message": f"כיוון המבט השתנה בין השוט הנוכחי לשוט {relation}; יש לוודא שרצף המבטים מכוון.",
            "expected": source_eyeline,
            "observed": target_eyeline,
            "neighbor_shot_id": target["id"],
            "neighbor_shot_number": target.get("shot_number"),
            "relation": relation,
        })

    source_direction = _direction_marker(
        (source.get("movement"), source.get("action"), source.get("composition")),
        SCREEN_DIRECTION_MARKERS,
    )
    target_direction = _direction_marker(
        (target.get("movement"), target.get("action"), target.get("composition")),
        SCREEN_DIRECTION_MARKERS,
    )
    if source_direction and target_direction and source_direction != target_direction:
        issues.append({
            "severity": "medium",
            "category": "screen_direction",
            "message": f"כיוון התנועה על המסך התהפך בין השוט הנוכחי לשוט {relation}; יש לבדוק רציפות גאוגרפית וקו פעולה.",
            "expected": source_direction,
            "observed": target_direction,
            "neighbor_shot_id": target["id"],
            "neighbor_shot_number": target.get("shot_number"),
            "relation": relation,
        })
    return issues


def _asset_signature(shot: dict) -> dict[int, tuple[str, str]]:
    return {
        int(asset["id"]): (str(asset.get("asset_type") or "נכס"), str(asset.get("name") or "ללא שם"))
        for asset in shot.get("assets", [])
        if asset.get("id") is not None
    }


def _neighbor_shots(shot: dict) -> tuple[dict | None, dict | None]:
    scene_shots = [candidate for candidate in shots.list_shots(shot["project_id"]) if candidate.get("scene_id") == shot.get("scene_id")]
    scene_shots.sort(key=lambda item: (item.get("shot_number") or 0, item.get("id") or 0))
    index = next((i for i, item in enumerate(scene_shots) if item["id"] == shot["id"]), None)
    if index is None:
        return None, None
    previous = shots.get_shot(scene_shots[index - 1]["id"]) if index > 0 else None
    following = shots.get_shot(scene_shots[index + 1]["id"]) if index + 1 < len(scene_shots) else None
    return previous, following


def _compare_pair(source: dict, target: dict, relation: str) -> list[dict]:
    issues: list[dict] = []
    for field, label in TRACKED_FIELDS:
        before = _normalized(source.get(field))
        after = _normalized(target.get(field))
        if before and after and before != after:
            issues.append({
                "severity": "medium", "category": field,
                "message": f"שינוי {label} בין השוט הנוכחי לשוט {relation}.",
                "expected": source.get(field) or "", "observed": target.get(field) or "",
                "neighbor_shot_id": target["id"], "neighbor_shot_number": target.get("shot_number"), "relation": relation,
            })

    issues.extend(_direction_issues(source, target, relation))

    source_assets = _asset_signature(source)
    target_assets = _asset_signature(target)
    for asset_id in sorted(set(source_assets) - set(target_assets)):
        asset_type, name = source_assets[asset_id]
        issues.append({
            "severity": "high" if asset_type in {"דמות", "לבוש"} else "medium", "category": "asset",
            "message": f"{asset_type} '{name}' חסר בשוט {relation}.", "expected": name, "observed": "לא מקושר",
            "asset_id": asset_id, "neighbor_shot_id": target["id"], "neighbor_shot_number": target.get("shot_number"), "relation": relation,
        })
    for asset_id in sorted(set(target_assets) - set(source_assets)):
        asset_type, name = target_assets[asset_id]
        issues.append({
            "severity": "medium", "category": "asset",
            "message": f"{asset_type} '{name}' מופיע לראשונה בשוט {relation}.", "expected": "לא מקושר", "observed": name,
            "asset_id": asset_id, "neighbor_shot_id": target["id"], "neighbor_shot_number": target.get("shot_number"), "relation": relation,
        })
    return issues


def continuity_preview(shot_id: int) -> dict | None:
    current = shots.get_shot(shot_id)
    if not current:
        return None
    previous, following = _neighbor_shots(current)
    issues: list[dict] = []
    if previous:
        issues.extend(_compare_pair(current, previous, "הקודם"))
    if following:
        issues.extend(_compare_pair(current, following, "הבא"))
    blocking = sum(1 for issue in issues if issue["severity"] in {"critical", "high"})
    return {
        "shot_id": shot_id,
        "previous_shot_id": previous["id"] if previous else None,
        "next_shot_id": following["id"] if following else None,
        "issue_count": len(issues),
        "blocking_issue_count": blocking,
        "can_finalize": blocking == 0,
        "issues": issues,
    }
