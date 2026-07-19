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
        issues.append({
            "severity": "high",
            "category": "missing_location",
            "message": "לא שויך לוקיישן לשוט."
        })

    if not characters and shot_type not in {"Establishing", "Insert", "Transition"}:
        issues.append({
            "severity": "medium",
            "category": "missing_character",
            "message": "לא שויכה דמות לשוט."
        })

    unapproved = [a["name"] for a in assets if not a["approved"]]
    if unapproved:
        issues.append({
            "severity": "medium",
            "category": "unapproved_assets",
            "message": "נכסים לא מאושרים: " + ", ".join(unapproved)
        })

    if not shot.get("lighting"):
        issues.append({
            "severity": "low",
            "category": "missing_lighting",
            "message": "לא הוגדרה תאורה לשוט."
        })

    if not previous:
        return issues

    previous_assets = previous.get("assets", [])
    prev_locations = _names(previous_assets, "לוקיישן")
    prev_characters = _names(previous_assets, "דמות")
    prev_props = _names(previous_assets, "אביזר")
    prev_wardrobe = _names(previous_assets, "לבוש")

    if prev_locations and locations and prev_locations != locations:
        issues.append({
            "severity": "high",
            "category": "location_change",
            "message": (
                f"שינוי לוקיישן לעומת שוט {previous['shot_number']}: "
                f"{', '.join(sorted(prev_locations))} → {', '.join(sorted(locations))}. "
                "יש לוודא שהמעבר מכוון."
            )
        })

    missing_characters = prev_characters - characters
    if missing_characters and shot_type not in {"Insert", "POV", "Transition"}:
        issues.append({
            "severity": "medium",
            "category": "character_disappeared",
            "message": (
                "דמויות שהופיעו בשוט הקודם אינן משויכות כעת: "
                + ", ".join(sorted(missing_characters))
            )
        })

    missing_props = prev_props - props
    if missing_props:
        issues.append({
            "severity": "medium",
            "category": "prop_disappeared",
            "message": (
                "אביזרים מהשוט הקודם נעלמו: "
                + ", ".join(sorted(missing_props))
            )
        })

    if prev_wardrobe and wardrobe and prev_wardrobe != wardrobe:
        issues.append({
            "severity": "high",
            "category": "wardrobe_change",
            "message": "הלבוש שונה מהשוט הקודם. יש לוודא שהשינוי מכוון."
        })

    previous_lighting = (previous.get("lighting") or "").strip()
    current_lighting = (shot.get("lighting") or "").strip()
    if previous_lighting and current_lighting and previous_lighting != current_lighting:
        issues.append({
            "severity": "low",
            "category": "lighting_change",
            "message": "הגדרת התאורה שונה מהשוט הקודם."
        })

    return issues
