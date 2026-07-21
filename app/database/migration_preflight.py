"""Read-only source audit before any SQLite-to-PostgreSQL migration.

The command reports only table counts and integrity status. It never emits row
contents, database paths, connection URLs, or credentials.
"""

import argparse
import json
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.database.postgres_schema import POSTGRES_SCHEMA_SQL


def _expected_tables() -> tuple[str, ...]:
    marker = "CREATE TABLE IF NOT EXISTS "
    tables: list[str] = []
    for statement in POSTGRES_SCHEMA_SQL.split(";"):
        normalized = statement.strip()
        if normalized.upper().startswith(marker):
            tables.append(normalized[len(marker) :].split("(", 1)[0].strip())
    return tuple(tables)


EXPECTED_TABLES = _expected_tables()


def audit_sqlite_source(
    database_path: Path,
    *,
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Inspect migration readiness without changing the SQLite database."""

    connection = connect() if connect is not None else sqlite3.connect(database_path)
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        actual_tables = {row[0] for row in cursor.fetchall()}

        missing_tables = sorted(set(EXPECTED_TABLES) - actual_tables)
        unexpected_tables = sorted(actual_tables - set(EXPECTED_TABLES))
        row_counts: dict[str, int] = {}
        for table in EXPECTED_TABLES:
            if table not in actual_tables:
                continue
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            row_counts[table] = int(cursor.fetchone()[0])

        cursor.execute("PRAGMA foreign_key_check")
        foreign_key_violations = len(cursor.fetchall())

        status = (
            "ready"
            if not missing_tables and foreign_key_violations == 0
            else "blocked"
        )
        return {
            "status": status,
            "table_count": len(actual_tables),
            "row_counts": row_counts,
            "missing_tables": missing_tables,
            "unexpected_tables": unexpected_tables,
            "foreign_key_violations": foreign_key_violations,
            "read_only": True,
        }
    except Exception:
        raise RuntimeError("SQLite migration preflight failed.") from None
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit SQLite migration readiness without modifying data."
    )
    parser.add_argument(
        "--confirm-read-only",
        action="store_true",
        help="Required acknowledgement that this command performs an audit only.",
    )
    args = parser.parse_args()
    if not args.confirm_read_only:
        parser.error("--confirm-read-only is required")

    database_path = Path(os.getenv("FILM_OS_DB", "film_os.db"))
    result = audit_sqlite_source(database_path)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
