#!/usr/bin/env python3
"""Run the deployed screenplay-import smoke twice and verify idempotency.

This wrapper preserves the safety contract of ``deployment_smoke.py``: it
requires the explicit import flag, never requests replacement, and emits only
structured counts and status fields.
"""

from __future__ import annotations

import json
import sys

from scripts.deployment_smoke import SmokeFailure, parse_args, run_smoke


def run_idempotency_smoke(argv: list[str] | None = None) -> dict[str, object]:
    config = parse_args(argv)
    if not config.execute_import:
        raise SmokeFailure("Idempotency verification requires --execute-import")

    first = run_smoke(config)
    second = run_smoke(config)

    first_after = first.get("after")
    second_before = second.get("before")
    second_after = second.get("after")
    if not isinstance(first_after, dict) or not isinstance(second_before, dict) or not isinstance(second_after, dict):
        raise SmokeFailure("Idempotency verification requires import snapshots from both runs")
    if second_before != first_after or second_after != first_after:
        raise SmokeFailure("Production scene or shot counts changed during idempotency verification")
    if not second.get("idempotent_replay"):
        raise SmokeFailure("Second screenplay import was not reported as an idempotent replay")
    if int(second.get("shots_created") or 0) != 0:
        raise SmokeFailure("Second screenplay import created additional shots")

    return {
        "ok": True,
        "project_id": config.project_id,
        "first": {
            "idempotent_replay": bool(first.get("idempotent_replay")),
            "shots_created": int(first.get("shots_created") or 0),
            "after": first_after,
        },
        "second": {
            "idempotent_replay": True,
            "shots_created": 0,
            "shot_maps_skipped": int(second.get("shot_maps_skipped") or 0),
            "after": second_after,
        },
    }


def main(argv: list[str] | None = None) -> int:
    try:
        result = run_idempotency_smoke(argv)
    except (SmokeFailure, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
