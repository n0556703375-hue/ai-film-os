import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse


class DatabaseBackend(Protocol):
    """Minimal connection boundary for database-specific implementations."""

    name: str

    def connect(self) -> Any:
        """Return a new configured database connection."""


@dataclass(frozen=True)
class SQLiteBackend:
    database_path: Path
    name: str = "sqlite"

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


@dataclass(frozen=True)
class PostgreSQLBackend:
    """Provider adapter for a future PostgreSQL activation.

    The adapter is intentionally not selected by the backend factory yet. This
    keeps production fail-closed until PostgreSQL-compatible schema migrations
    and data verification are implemented.
    """

    database_url: str
    name: str = "postgresql"

    def __post_init__(self) -> None:
        scheme = urlparse(self.database_url.strip()).scheme.lower()
        if scheme not in {"postgres", "postgresql"}:
            raise ValueError("PostgreSQL backend requires a PostgreSQL database URL.")

    def connect(self) -> Any:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise RuntimeError(
                "PostgreSQL driver is unavailable; install psycopg before activation."
            ) from None

        try:
            return psycopg.connect(self.database_url, row_factory=dict_row)
        except Exception:
            # Do not surface provider exceptions because they can include a DSN
            # containing credentials.
            raise RuntimeError("PostgreSQL connection failed.") from None


def build_database_backend(
    database_path: Path,
    database_url: str = "",
) -> DatabaseBackend:
    """Build the configured backend while SQLite remains the safe default.

    A configured PostgreSQL URL is recognized but rejected until compatible
    migrations and verified production cutover tooling are implemented. The URL
    is never included in the error message, preventing credential exposure.
    """

    normalized_url = database_url.strip()
    if not normalized_url:
        return SQLiteBackend(database_path=database_path)

    scheme = urlparse(normalized_url).scheme.lower()
    if scheme in {"postgres", "postgresql"}:
        raise RuntimeError(
            "PostgreSQL is configured but production activation is not enabled yet."
        )

    raise ValueError(f"Unsupported database URL scheme: {scheme or '<missing>'}.")
