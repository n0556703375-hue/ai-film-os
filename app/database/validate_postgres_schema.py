"""Rollback-only PostgreSQL schema validation for temporary environments."""

import argparse
import os
import re
from collections.abc import Callable, Mapping
from typing import Any

from app.database.backend import PostgreSQLBackend
from app.database.postgres_schema import POSTGRES_SCHEMA_SQL

_TABLE_PATTERN = re.compile(
    r"CREATE TABLE IF NOT EXISTS\s+([a-z_]+)",
    flags=re.IGNORECASE,
)
EXPECTED_TABLES = frozenset(_TABLE_PATTERN.findall(POSTGRES_SCHEMA_SQL))


def _schema_statements() -> tuple[str, ...]:
    """Return executable DDL statements without relying on multi-command execution."""

    return tuple(
        statement.strip()
        for statement in POSTGRES_SCHEMA_SQL.split(";")
        if statement.strip()
    )


def _table_name(row: Any) -> str:
    """Read a table name from psycopg dictionary rows or test tuple rows."""

    if isinstance(row, Mapping):
        return str(row["table_name"])
    return str(row[0])


def validate_postgres_startup_connection(connection: Any) -> None:
    """Verify the runtime schema contract without mutating or closing the connection."""

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                """
            )
            actual_tables = {_table_name(row) for row in cursor.fetchall()}
    except Exception:
        raise RuntimeError("PostgreSQL startup schema validation failed.") from None

    if EXPECTED_TABLES - actual_tables:
        raise RuntimeError(
            "PostgreSQL startup schema validation failed: expected tables are missing."
        )


def validate_postgres_schema(
    database_url: str,
    *,
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Apply and inspect the schema inside a transaction that is always rolled back."""

    backend = PostgreSQLBackend(database_url=database_url)
    connection = connect() if connect is not None else backend.connect()

    try:
        with connection.cursor() as cursor:
            for statement in _schema_statements():
                cursor.execute(statement)
        validate_postgres_startup_connection(connection)

        return {
            "status": "valid",
            "table_count": len(EXPECTED_TABLES),
            "rolled_back": True,
        }
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("PostgreSQL schema validation failed.") from None
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate PostgreSQL DDL and roll back every change."
    )
    parser.add_argument(
        "--confirm-rollback-only",
        action="store_true",
        help="Required acknowledgement that this command never commits schema changes.",
    )
    args = parser.parse_args()

    if not args.confirm_rollback_only:
        parser.error("--confirm-rollback-only is required")

    database_url = os.getenv("POSTGRES_SCHEMA_VALIDATION_URL", "").strip()
    if not database_url:
        raise RuntimeError("POSTGRES_SCHEMA_VALIDATION_URL is required.")

    result = validate_postgres_schema(database_url)
    print(
        f"PostgreSQL schema validation passed for {result['table_count']} tables; "
        "all changes were rolled back."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
