"""Rollback-only SQLite-to-PostgreSQL import validation.

This command copies rows only inside a PostgreSQL transaction, validates table
counts and constraints, and always rolls back. It never prints row contents,
paths, URLs, credentials, or provider error details.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.database.migration_preflight import EXPECTED_TABLES, audit_sqlite_source
from app.database.postgres_schema import POSTGRES_SCHEMA_SQL

TABLE_ORDER = (
    "projects",
    "scenes",
    "shots",
    "assets",
    "shot_assets",
    "asset_reference_images",
    "continuity_issues",
    "prompt_versions",
    "media_results",
    "approval_events",
    "media_jobs",
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise RuntimeError("Migration contract contains an invalid identifier.")
    return f'"{value}"'


def _validate_contract() -> None:
    if set(TABLE_ORDER) != set(EXPECTED_TABLES):
        raise RuntimeError("Migration table order does not match the schema contract.")


def _default_postgres_connect(database_url: str) -> Any:
    try:
        import psycopg
    except ImportError:
        raise RuntimeError("PostgreSQL driver is not installed.") from None
    return psycopg.connect(database_url)


def dry_run_sqlite_to_postgres(
    sqlite_path: Path,
    postgres_url: str,
    *,
    sqlite_connect: Callable[[], Any] | None = None,
    postgres_connect: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Validate a complete import and always roll the target transaction back."""

    _validate_contract()
    parsed = urlparse(postgres_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise RuntimeError("A valid PostgreSQL validation URL is required.")

    preflight = audit_sqlite_source(sqlite_path, connect=sqlite_connect)
    if preflight["status"] != "ready":
        return {
            "status": "blocked",
            "reason": "source_preflight_failed",
            "source_row_counts": preflight["row_counts"],
            "rolled_back": True,
        }

    source = sqlite_connect() if sqlite_connect is not None else sqlite3.connect(sqlite_path)
    target = None
    try:
        connector = postgres_connect or _default_postgres_connect
        target = connector(postgres_url)
        cursor = target.cursor()
        cursor.execute(
            "SELECT tablename FROM pg_catalog.pg_tables "
            "WHERE schemaname = current_schema()"
        )
        if cursor.fetchall():
            raise RuntimeError("PostgreSQL validation target must be empty.")

        cursor.execute(POSTGRES_SCHEMA_SQL)

        for table in TABLE_ORDER:
            quoted_table = _quote_identifier(table)
            cursor.execute(f"SELECT COUNT(*) FROM {quoted_table}")
            if int(cursor.fetchone()[0]) != 0:
                raise RuntimeError("PostgreSQL validation target must be empty.")

        transferred: dict[str, int] = {}
        source_cursor = source.cursor()
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
            target_counts[table] = int(cursor.fetchone()[0])

        if target_counts != preflight["row_counts"] or target_counts != transferred:
            raise RuntimeError("PostgreSQL dry-run row counts do not match the source.")

        return {
            "status": "validated",
            "table_count": len(TABLE_ORDER),
            "row_counts": target_counts,
            "constraints_validated": True,
            "rolled_back": True,
        }
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("PostgreSQL import dry run failed.") from None
    finally:
        source.close()
        if target is not None:
            try:
                target.rollback()
            finally:
                target.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate SQLite-to-PostgreSQL import and always roll it back."
    )
    parser.add_argument(
        "--confirm-rollback-only",
        action="store_true",
        help="Required acknowledgement that no imported rows will be committed.",
    )
    args = parser.parse_args()
    if not args.confirm_rollback_only:
        parser.error("--confirm-rollback-only is required")

    postgres_url = os.getenv("POSTGRES_IMPORT_VALIDATION_URL", "")
    sqlite_path = Path(os.getenv("FILM_OS_DB", "film_os.db"))
    result = dry_run_sqlite_to_postgres(sqlite_path, postgres_url)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "validated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
