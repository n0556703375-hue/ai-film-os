from app.repositories.approvals import decide_media, finalize_shot


def batch_approval(action: str, items: list[dict], project_id: int, notes: str = ""):
    """Apply existing approval rules independently and report every item."""
    results = []
    for item in items:
        shot_id = item["shot_id"]
        media_id = item.get("media_id")
        try:
            pipeline = (
                finalize_shot(shot_id, project_id, notes)
                if action == "finalize"
                else decide_media(shot_id, media_id, action, project_id, notes)
            )
            if pipeline is None:
                results.append({
                    "shot_id": shot_id,
                    "media_id": media_id,
                    "ok": False,
                    "error": "השוט לא נמצא.",
                })
            else:
                results.append({
                    "shot_id": shot_id,
                    "media_id": media_id,
                    "ok": True,
                    "status": pipeline["status"],
                })
        except ValueError as exc:
            results.append({
                "shot_id": shot_id,
                "media_id": media_id,
                "ok": False,
                "error": str(exc),
            })

    succeeded = sum(1 for result in results if result["ok"])
    return {
        "action": action,
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }
