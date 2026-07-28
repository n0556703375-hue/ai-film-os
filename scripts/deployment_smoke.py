#!/usr/bin/env python3
"""Safe deployed-service smoke checks for Milestone B.

Read-only checks run by default. A screenplay import requires both
``--execute-import`` and ``--screenplay-file``. The harness never requests
replacement of existing production data and never prints screenplay text,
credentials, raw HTML, or provider payloads.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class SmokeFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class SmokeConfig:
    base_url: str
    project_id: int
    job_id: int | None = None
    screenplay_file: Path | None = None
    execute_import: bool = False
    timeout_seconds: float = 30.0


def _url(config: SmokeConfig, path: str, query: dict[str, Any] | None = None) -> str:
    base = config.base_url.rstrip("/")
    suffix = f"?{urlencode(query)}" if query else ""
    return f"{base}{path}{suffix}"


def _request_json(
    config: SmokeConfig,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        _url(config, path, query),
        data=body,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
    except HTTPError as exc:
        raise SmokeFailure(f"{method} {path} returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise SmokeFailure(f"{method} {path} could not reach the deployed service") from exc

    if "json" not in content_type.lower():
        raise SmokeFailure(f"{method} {path} returned a non-JSON response")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SmokeFailure(f"{method} {path} returned malformed JSON") from exc


def build_import_payload(config: SmokeConfig) -> dict[str, Any]:
    if not config.execute_import:
        raise SmokeFailure("Screenplay import requires --execute-import")
    if config.screenplay_file is None:
        raise SmokeFailure("Screenplay import requires --screenplay-file")
    screenplay = config.screenplay_file.read_text(encoding="utf-8")
    if len(screenplay.strip()) < 50:
        raise SmokeFailure("Screenplay file is too short for the production import contract")
    return {
        "project_id": config.project_id,
        "screenplay": screenplay,
        "screenplay_fingerprint": "",
        "target_shots_per_minute": 5.0,
        "next_chunk_index": 0,
        "scenes": [],
    }


def _scene_ids_with_shots(snapshot: dict[str, Any]) -> set[int]:
    scene_ids = {int(scene.get("id") or 0) for scene in snapshot.get("scenes") or []}
    result: set[int] = set()
    for shot in snapshot.get("shots") or []:
        scene_id = int(shot.get("scene_id") or 0)
        if scene_id < 1 or scene_id not in scene_ids:
            raise SmokeFailure("Production snapshot contains a shot with an invalid scene relationship")
        result.add(scene_id)
    return result


def _run_resumable_import(
    config: SmokeConfig,
    *,
    existing_shot_scene_ids: set[int] | None = None,
) -> dict[str, Any]:
    state = build_import_payload(config)
    chunk_count = 0
    for _ in range(1000):
        response = _request_json(
            config,
            "/api/import-runs/process-next",
            method="POST",
            payload=state,
        )
        if not isinstance(response, dict):
            raise SmokeFailure("Resumable screenplay breakdown returned an invalid shape")
        state = {
            "project_id": config.project_id,
            "screenplay": state["screenplay"],
            "screenplay_fingerprint": str(response.get("screenplay_fingerprint") or ""),
            "target_shots_per_minute": 5.0,
            "next_chunk_index": int(response.get("next_chunk_index") or 0),
            "scenes": list(response.get("scenes") or []),
        }
        chunk_count = int(response.get("chunk_count") or 0)
        if response.get("completed"):
            break
    else:
        raise SmokeFailure("Resumable screenplay breakdown exceeded the safe chunk limit")

    persisted = _request_json(
        config,
        "/api/import-runs/persist",
        method="POST",
        payload={
            "project_id": config.project_id,
            "completed": True,
            "scenes": state["scenes"],
        },
    )
    if not isinstance(persisted, dict):
        raise SmokeFailure("Screenplay persistence returned an invalid shape")

    imported_scenes = list(persisted.get("imported_scenes") or [])
    existing_shot_scene_ids = existing_shot_scene_ids or set()
    shots_created = 0
    shot_maps_skipped = 0
    for scene in imported_scenes:
        scene_id = int(scene.get("id") or 0)
        if scene_id < 1:
            raise SmokeFailure("Persisted screenplay scene is missing an id")
        if scene_id in existing_shot_scene_ids:
            shot_maps_skipped += 1
            continue
        created = _request_json(
            config,
            f"/api/scenes/{scene_id}/shot-map",
            method="POST",
            payload={
                "shot_count": int(scene.get("recommended_shot_count") or 6),
                "replace_existing": False,
            },
        )
        if not isinstance(created, dict):
            raise SmokeFailure("Shot-map generation returned an invalid shape")
        shots_created += len(created.get("shots") or [])

    return {
        "processed_chunks": int(state["next_chunk_index"]),
        "chunk_count": chunk_count,
        "scenes_created": int(persisted.get("scenes_created") or 0),
        "idempotent_replay": bool(persisted.get("idempotent_replay")),
        "shots_created": shots_created,
        "shot_maps_skipped": shot_maps_skipped,
    }


def _snapshot_counts(snapshot: dict[str, Any]) -> dict[str, int]:
    project = snapshot.get("project") or {}
    project_id = int(project.get("id") or 0)
    scenes = snapshot.get("scenes") or []
    shots = snapshot.get("shots") or []
    if any(int(item.get("project_id") or 0) != project_id for item in scenes):
        raise SmokeFailure("Production snapshot contains a scene from another project")
    if any(int(item.get("project_id") or 0) != project_id for item in shots):
        raise SmokeFailure("Production snapshot contains a shot from another project")
    return {"scenes": len(scenes), "shots": len(shots)}


def run_smoke(config: SmokeConfig) -> dict[str, Any]:
    health = _request_json(config, "/health")
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise SmokeFailure("Health check did not report ok")

    readiness = _request_json(config, "/ready")
    if not isinstance(readiness, dict) or readiness.get("status") != "ready":
        raise SmokeFailure("Readiness check did not report ready")

    snapshot_path = f"/api/projects/{config.project_id}/production-snapshot"
    before = _request_json(config, snapshot_path)
    if not isinstance(before, dict):
        raise SmokeFailure("Production snapshot response has an invalid shape")
    before_counts = _snapshot_counts(before)
    existing_shot_scene_ids = _scene_ids_with_shots(before)

    result: dict[str, Any] = {
        "health": "ok",
        "readiness": "ready",
        "project_id": config.project_id,
        "before": before_counts,
        "import_executed": False,
    }

    if config.job_id is not None:
        status = _request_json(config, f"/api/video-generation/jobs/{config.job_id}/status")
        if not isinstance(status, dict) or int(status.get("job_id") or 0) != config.job_id:
            raise SmokeFailure("Video job polling returned an unexpected job")
        result["video_job"] = {
            "job_id": config.job_id,
            "status": status.get("status"),
            "terminal": bool(status.get("terminal")),
        }

    if config.execute_import:
        imported = _run_resumable_import(
            config,
            existing_shot_scene_ids=existing_shot_scene_ids,
        )
        after = _request_json(config, snapshot_path)
        if not isinstance(after, dict):
            raise SmokeFailure("Post-import production snapshot has an invalid shape")
        after_counts = _snapshot_counts(after)
        if after_counts["scenes"] < before_counts["scenes"] or after_counts["shots"] < before_counts["shots"]:
            raise SmokeFailure("Production counts decreased after non-replacing import")
        result.update({"import_executed": True, **imported, "after": after_counts})

    return result


def parse_args(argv: list[str] | None = None) -> SmokeConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--job-id", type=int)
    parser.add_argument("--screenplay-file", type=Path)
    parser.add_argument("--execute-import", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    if args.project_id < 1:
        parser.error("--project-id must be positive")
    if args.job_id is not None and args.job_id < 1:
        parser.error("--job-id must be positive")
    if args.execute_import and args.screenplay_file is None:
        parser.error("--execute-import requires --screenplay-file")
    return SmokeConfig(
        base_url=args.base_url,
        project_id=args.project_id,
        job_id=args.job_id,
        screenplay_file=args.screenplay_file,
        execute_import=args.execute_import,
        timeout_seconds=args.timeout_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        result = run_smoke(parse_args(argv))
    except (SmokeFailure, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
