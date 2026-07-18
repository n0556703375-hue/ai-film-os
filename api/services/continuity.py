def check_shot_continuity(shot: dict) -> list[dict]:
    issues = []
    assets = shot.get("assets", [])

    if not any(a["asset_type"] == "לוקיישן" for a in assets):
        issues.append({
            "severity": "high",
            "category": "missing_location",
            "message": "לא שויך לוקיישן לשוט."
        })

    if not any(a["asset_type"] == "דמות" for a in assets):
        issues.append({
            "severity": "medium",
            "category": "missing_character",
            "message": "לא שויכה דמות לשוט. ייתכן שזה תקין בשוט Establishing."
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

    return issues
