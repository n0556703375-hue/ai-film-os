#!/usr/bin/env python3
"""Verify deployed screenplay import idempotency without replacing data.

The command deliberately runs the existing safe deployment import smoke twice
against the same empty, isolated project and screenplay. It succeeds only when
the first run creates persisted scenes and shots, the second run is reported as
an idempotent replay, creates no new shot maps, and leaves scene and shot totals
unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.deployment_smoke import (
    SmokeConfig,
    SmokeFailure,
    _request_json,
    _snapshot_counts,
    run_smoke,
)


def verify_empty_project(config: SmokeConfig) -> dict[str, int]:
    """Fail before import when the target project already contains production data."""
    snapshot_path = f"/api/projects/{config.project_id}/production-snapshot"
    snapshot = _request_json(config, snapshot_path)
    if not isinstance(snapshot, dict):
        raise SmokeFailure("Production snapshot response has an invalid shape")
    counts = _snapshot_counts(snapshot, expected_project_id=config.project_id)
    if counts["scenes"] != 0 or counts["shots"] != 0:
        raise SmokeFailure(
            "Idempotency smoke requires an empty isolated project; "
            f"found {counts['scenes']} scenes and {counts['shots']} shots"
        )
    return counts


def verify_import_idempotency(config: SmokeConfig) -> dict[str, object]:
    if not config.execute_import:
        raise SmokeFailure("Idempotency verification requires --execute-import")
    if config.screenplay_file is None:
        raise SmokeFailure("Idempotency verification requires --screenplay-file")

    verify_empty_project(config)
    first = run_smoke(config)
    second = run_smoke(config)

    if not first.get("import_executed") or not second.get("import_executed"):
        raise SmokeFailure("Both deployment smoke runs must execute the screenplay import")

    first_after = first.get("after")
    second_before = second.get("before")
    second_after = second.get("after")
    if not isinstance(first_after, dict) or not isinstance(second_before, dict) or not isinstance(second_after, dict):
        raise SmokeFailure("Deployment smoke results are missing production count snapshots")

    first_scenes_created = int(first.get("scenes_created") or 0)
    first_shots_created = int(first.get("shots_created") or 0)
    if first_scenes_created < 1 or first_shots_created < 1:
        raise SmokeFailure("First screenplay import did not create both scenes and shots")
    if int(first_after.get("scenes") or 0) < 1 or int(first_after.get("shots") or 0) < 1:
        raise SmokeFailure("First screenplay import left no persisted scenes or shots")

    if not second.get("idempotent_replay"):
        raise SmokeFailure("Second screenplay import was not reported as an idempotent replay")
    if int(second.get("shots_created") or 0) != 0:
        raise SmokeFailure("Second screenplay import created new shots")
    if first_after != second_before or second_before != second_after:
        raise SmokeFailure("Scene or shot totals changed during the idempotent replay")

    return {
        "project_id": config.project_id,
        "idempotent_replay": True,
        "counts": second_after,
        "first": {
            "scenes_created": first_scenes_created,
            "shots_created": first_shots_created,
        },
        "second": {
            "scenes_created": int(second.get("scenes_created") or 0),
            "shots_created": 0,
            "shot_maps_skipped": int(second.get("shot_maps_skipped") or 0),
        },
    }


def parse_args(argv: list[str] | None = None) -> SmokeConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--screenplay-file", type=Path, required=True)
    parser.add_argument("--execute-import", action="store_true", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    if args.project_id < 1:
        parser.error("--project-id must be positive")
    return SmokeConfig(
        base_url=args.base_url,
        project_id=args.project_id,
        screenplay_file=args.screenplay_file,
        execute_import=args.execute_import,
        timeout_seconds=args.timeout_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        result = verify_import_idempotency(parse_args(argv))
    except (SmokeFailure, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
