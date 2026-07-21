from __future__ import annotations

import argparse
import json
import os
import socket
from typing import Any

from app.services.identity_worker_runner import process_next_identity_assessment


DEFAULT_MAX_TASKS = 1
MAX_TASKS_LIMIT = 25


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Process a bounded number of pending identity assessments."
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=DEFAULT_MAX_TASKS,
        help=f"Maximum tasks to process in this run (1-{MAX_TASKS_LIMIT}).",
    )
    parser.add_argument(
        "--worker-id",
        default=os.getenv("IDENTITY_WORKER_ID", "").strip(),
        help="Worker identifier. Defaults to IDENTITY_WORKER_ID.",
    )
    return parser


def resolve_worker_id(value: str) -> str:
    worker_id = value.strip()
    if worker_id:
        return worker_id
    return f"identity-worker-{socket.gethostname()}-{os.getpid()}"


def run(*, max_tasks: int, worker_id: str) -> dict[str, Any]:
    if not 1 <= max_tasks <= MAX_TASKS_LIMIT:
        raise ValueError(f"max_tasks must be between 1 and {MAX_TASKS_LIMIT}.")

    processed: list[dict[str, Any]] = []
    for _ in range(max_tasks):
        result = process_next_identity_assessment(worker_id=worker_id)
        if not result.get("processed"):
            break
        processed.append(result)

    return {
        "worker_id": worker_id,
        "processed_count": len(processed),
        "max_tasks": max_tasks,
        "results": processed,
    }


def main() -> int:
    args = build_parser().parse_args()
    worker_id = resolve_worker_id(args.worker_id)
    try:
        summary = run(max_tasks=args.max_tasks, worker_id=worker_id)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps({"ok": True, **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
