"""Non-destructive readiness gate for a future PostgreSQL cutover.

This command composes the existing read-only SQLite backup verification and
rollback-only PostgreSQL import validation. It never commits target changes and
never prints filesystem paths, connection URLs, credentials, or row contents.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.database.postgres_import_dry_run import dry_run_sqlite_to_postgres
from app.database.sqlite_backup_verification import verify_sqlite_backup


def assess_cutover_readiness(
    source_path: Path,
    backup_path: Path,
    postgres_url: str,
    *,
    backup_verifier: Callable[[Path, Path], dict[str, Any]] = verify_sqlite_backup,
    import_validator: Callable[[Path, str], dict[str, Any]] = dry_run_sqlite_to_postgres,
) -> dict[str, Any]:
    """Require verified backup evidence and a rollback-only import validation."""

    backup = backup_verifier(source_path, backup_path)
    if backup.get("status") != "verified":
        return {
            "status": "blocked",
            "reason": "backup_verification_failed",
            "backup_verified": False,
            "import_validated": False,
            "persistent_changes": False,
        }

    validation = import_validator(source_path, postgres_url)
    if validation.get("status") != "validated":
        return {
            "status": "blocked",
            "reason": "import_validation_failed",
            "backup_verified": True,
            "import_validated": False,
            "persistent_changes": False,
        }

    backup_counts = backup.get("source_row_counts")
    validation_counts = validation.get("row_counts")
    if backup_counts != validation_counts:
        return {
            "status": "blocked",
            "reason": "validation_evidence_mismatch",
            "backup_verified": True,
            "import_validated": True,
            "persistent_changes": False,
        }

    return {
        "status": "ready",
        "backup_verified": True,
        "import_validated": True,
        "table_count": validation.get("table_count", len(validation_counts or {})),
        "row_counts": validation_counts,
        "constraints_validated": bool(validation.get("constraints_validated")),
        "rollback_confirmed": bool(validation.get("rolled_back")),
        "persistent_changes": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assess PostgreSQL cutover readiness without committing changes."
    )
    parser.add_argument(
        "--confirm-non-destructive",
        action="store_true",
        help="Required acknowledgement that this command performs validation only.",
    )
    args = parser.parse_args()
    if not args.confirm_non_destructive:
        parser.error("--confirm-non-destructive is required")

    backup_value = os.getenv("FILM_OS_BACKUP_DB", "")
    if not backup_value:
        raise RuntimeError("FILM_OS_BACKUP_DB is required.")

    postgres_url = os.getenv("POSTGRES_IMPORT_VALIDATION_URL", "")
    if not postgres_url:
        raise RuntimeError("POSTGRES_IMPORT_VALIDATION_URL is required.")

    source_path = Path(os.getenv("FILM_OS_DB", "film_os.db"))
    result = assess_cutover_readiness(
        source_path,
        Path(backup_value),
        postgres_url,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
