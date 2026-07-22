"""Guarded persistent SQLite-to-PostgreSQL import.

This command re-verifies a separate SQLite backup, requires an exact explicit
confirmation phrase, accepts only an empty isolated PostgreSQL target, validates
row counts and constraints, and commits only after every check succeeds. It does
not change runtime or production configuration and never prints paths, URLs,
credentials, provider errors, row contents, or content fingerprints.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.database.postgres_import_dry_run import (
    TABLE_ORDER,
    _quote_identifier,
    _validate_contract,
)
from app.database.postgres_schema import POSTGRES_SCHEMA_SQL
from app.database.sqlite_backup_verification import verify_sqlite_backup

CONFIRMATION_PHRASE = "IMPORT_TO_EMPTY_POSTGRES"


def _default_postgres_connect(database_url: str) -> Any:
    try:
        import psycopg
    except ImportError:
        raise RuntimeError("PostgreSQL driver is not installed.") from None
    return psycopg.connect(database_url)


def import_sqlite_to_postgres(
    sqlite_path: Path,
    backup_path: Path,
    postgres_url: str,
    *,
    confirmation: str,
    source_connect: Callable[[], Any] | None = None,
    backup_connect: Callable[[], Any] | None = None,
    postgres_connect: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Persist a verified import into an empty target and leave config unchanged."""

    if confirmation != CONFIRMATION_PHRASE:
        raise RuntimeError("Exact persistent import confirmation is required.")

    _validate_contract()
    parsed = urlparse(postgres_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise RuntimeError("A valid PostgreSQL import URL is required.")

    backup_evidence = verify_sqlite_backup(
        sqlite_path,
        backup_path,
        source_connect=source_connect,
        backup_connect=backup_connect,
    )
    if backup_evidence["status"] != "verified":
        return {
            "status": "blocked",
            "reason": "backup_verification_failed",
            "production_configuration_changed": False,
            "committed": False,
        }

    source_factory = source_connect or (lambda: sqlite3.connect(sqlite_path))
    source = source_factory()
    target = None
    committed = False
    try:
        connector = postgres_connect or _default_postgres_connect
        target = connector(postgres_url)
        cursor = target.cursor()
        cursor.execute(
            "SELECT tablename FROM pg_catalog.pg_tables "
            "WHERE schemaname = current_schema()"
        )
        if cursor.fetchall():
            raise RuntimeError("PostgreSQL import target must be empty and isolated.")

        cursor.execute(POSTGRES_SCHEMA_SQL)
        source_cursor = source.cursor()
        transferred: dict[str, int] = {}

        for table in TABLE_ORDER:
            quoted_table = _quote_identifier(table)
            source_cursor.execute(f"PRAGMA table_info({quoted_table})")
            columns = [str(row[1]) for row in source_cursor.fetchall()]
            if not columns:
                raise RuntimeError("SQLite source table has no columns.")

            quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
            source_cursor.execute(f"SELECT {quoted_columns} FROM {quoted_table}")
            rows = source_cursor.fetchall()
            if rows:
                placeholders = ", ".join(["%s"] * len(columns))
                cursor.executemany(
                    f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})",
                    rows,
                )
            transferred[table] = len(rows)

        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        target_counts: dict[str, int] = {}
        for table in TABLE_ORDER:
            cursor.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}")
            row = cursor.fetchone()
            value = row["count"] if isinstance(row, dict) else row[0]
            target_counts[table] = int(value)

        expected_counts = backup_evidence["source_row_counts"]
        if target_counts != expected_counts or target_counts != transferred:
            raise RuntimeError("Committed PostgreSQL row counts do not match the source.")

        target.commit()
        committed = True
        return {
            "status": "imported",
            "table_count": len(TABLE_ORDER),
            "row_counts": target_counts,
            "constraints_validated": True,
            "backup_verified": True,
            "committed": True,
            "production_configuration_changed": False,
        }
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("Persistent PostgreSQL import failed.") from None
    finally:
        source.close()
        if target is not None:
            try:
                if not committed:
                    target.rollback()
            finally:
                target.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Persist a verified SQLite import into an empty PostgreSQL target."
    )
    parser.add_argument(
        "--confirm-persistent-import",
        required=True,
        help=f"Must equal {CONFIRMATION_PHRASE}.",
    )
    args = parser.parse_args()

    sqlite_path = Path(os.getenv("FILM_OS_DB", "film_os.db"))
    backup_path = Path(os.getenv("FILM_OS_BACKUP_DB", ""))
    postgres_url = os.getenv("POSTGRES_IMPORT_URL", "")
    result = import_sqlite_to_postgres(
        sqlite_path,
        backup_path,
        postgres_url,
        confirmation=args.confirm_persistent_import,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "imported" else 1


if __name__ == "__main__":
    raise SystemExit(main())
