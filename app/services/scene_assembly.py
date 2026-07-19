from __future__ import annotations

from app.repositories import scenes, shots


APPROVED = "מאושר"


def _approved_media(shot: dict, media_type: str) -> dict | None:
    candidates = [
        item
        for item in shot.get("media_results", [])
        if item.get("media_type") == media_type and item.get("status") == APPROVED
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.get("version") or 0, item.get("id") or 0))


def build_scene_preview_manifest(scene_id: int) -> dict | None:
    scene = scenes.get_scene(scene_id)
    if not scene:
        return None

    timeline = []
    total_duration = 0.0
    missing_video_shots = []

    ordered = sorted(
        scene.get("shots", []),
        key=lambda item: (item.get("shot_number") or 0, item.get("id") or 0),
    )
    for summary in ordered:
        shot = shots.get_shot(summary["id"])
        duration = float(shot.get("duration_seconds") or 0)
        total_duration += duration
        approved_video = _approved_media(shot, "video")
        approved_image = _approved_media(shot, "image")
        if not approved_video:
            missing_video_shots.append(shot["id"])

        timeline.append({
            "shot_id": shot["id"],
            "shot_number": shot.get("shot_number"),
            "title": shot.get("title") or f"שוט {shot.get('shot_number')}",
            "status": shot.get("status"),
            "duration_seconds": duration,
            "video_url": approved_video.get("url") if approved_video else None,
            "image_url": approved_image.get("url") if approved_image else None,
            "audio_notes": shot.get("audio") or "",
            "dialogue": shot.get("dialogue") or "",
            "has_audio_notes": bool((shot.get("audio") or "").strip()),
            "has_dialogue": bool((shot.get("dialogue") or "").strip()),
            "ready_for_preview": approved_video is not None and duration > 0,
        })

    return {
        "scene_id": scene["id"],
        "scene_number": scene.get("scene_number"),
        "title": scene.get("title"),
        "shot_count": len(timeline),
        "duration_seconds": round(total_duration, 3),
        "ready_for_preview": bool(timeline) and not missing_video_shots and all(
            item["duration_seconds"] > 0 for item in timeline
        ),
        "missing_video_shot_ids": missing_video_shots,
        "timeline": timeline,
    }
