#!/usr/bin/env python3
"""Verify deployed screenplay import idempotency without replacing data.

The command deliberately runs the existing safe deployment import smoke twice
against the same project and screenplay. It succeeds only when the second run
is reported as an idempotent replay, creates no new shot maps, and leaves scene
and shot totals unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.deployment_smoke import SmokeConfig, SmokeFailure, run_smoke


def verify_import_idempotency(config: SmokeConfig) -> dict[str, object]:
    if not config.execute_import:
        raise SmokeFailure("Idempotency verification requires --execute-import")
    if config.screenplay_file is None:
        raise SmokeFailure("Idempotency verification requires --screenplay-file")

    first = run_smoke(config)
    second = run_smoke(config)

    if not first.get("import_executed") or not second.get("import_executed"):
        raise SmokeFailure("Both deployment smoke runs must execute the screenplay import")
    if not second.get("idempotent_replay"):
        raise SmokeFailure("Second screenplay import was not reported as an idempotent replay")
    if int(second.get("shots_created") or 0) != 0:
        raise SmokeFailure("Second screenplay import created new shots")

    first_after = first.get("after")
    second_before = second.get("before")
    second_after = second.get("after")
    if not isinstance(first_after, dict) or not isinstance(second_before, dict) or not isinstance(second_after, dict):
        raise SmokeFailure("Deployment smoke results are missing production count snapshots")
    if first_after != second_before or second_before != second_after:
        raise SmokeFailure("Scene or shot totals changed during the idempotent replay")

    return {
        "project_id": config.project_id,
        "idempotent_replay": True,
        "counts": second_after,
        "first": {
            "scenes_created": int(first.get("scenes_created") or 0),
            "shots_created": int(first.get("shots_created") or 0),
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
