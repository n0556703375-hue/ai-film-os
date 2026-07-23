import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Protocol


class DatabaseStartupAdapter(Protocol):
    """Backend-specific database initialization boundary."""

    name: str

    def initialize(self, conn: Any) -> None:
        """Initialize or validate a connected database for application startup."""


@dataclass(frozen=True)
class SQLiteStartupAdapter:
    schema_sql: str
    migrate: Callable[[sqlite3.Connection], None]
    seed: Callable[[sqlite3.Connection], None]
    name: str = "sqlite"

    def initialize(self, conn: sqlite3.Connection) -> None:
        try:
            conn.executescript(self.schema_sql)
            self.migrate(conn)
            self.seed(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


@dataclass(frozen=True)
class PostgreSQLStartupAdapter:
    """Validate PostgreSQL startup readiness without mutating runtime data."""

    validate: Callable[[Any], None]
    name: str = "postgresql"

    def initialize(self, conn: Any) -> None:
        self.validate(conn)


def build_database_startup_adapter(
    backend_name: str,
    *,
    schema_sql: str,
    migrate: Callable[[sqlite3.Connection], None],
    seed: Callable[[sqlite3.Connection], None],
    enable_postgresql: bool = False,
    validate_postgresql: Callable[[Any], None] | None = None,
) -> DatabaseStartupAdapter:
    """Build a startup adapter without silently enabling unsupported backends."""

    if backend_name == "sqlite":
        return SQLiteStartupAdapter(
            schema_sql=schema_sql,
            migrate=migrate,
            seed=seed,
        )

    if backend_name == "postgresql":
        if not enable_postgresql:
            raise RuntimeError(
                "PostgreSQL startup initialization is not enabled yet."
            )
        if validate_postgresql is None:
            raise RuntimeError(
                "PostgreSQL startup validation is required before activation."
            )
        return PostgreSQLStartupAdapter(validate=validate_postgresql)

    raise ValueError(f"Unsupported database backend: {backend_name or '<missing>'}.")
