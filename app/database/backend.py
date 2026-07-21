import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse


class DatabaseBackend(Protocol):
    """Minimal connection boundary for database-specific implementations."""

    name: str

    def connect(self) -> sqlite3.Connection:
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


def build_database_backend(
    database_path: Path,
    database_url: str = "",
) -> DatabaseBackend:
    """Build the configured backend while SQLite remains the safe default.

    A configured PostgreSQL URL is recognized but rejected until the concrete
    backend and compatible migrations are implemented. The URL is never
    included in the error message, preventing accidental credential exposure.
    """

    normalized_url = database_url.strip()
    if not normalized_url:
        return SQLiteBackend(database_path=database_path)

    scheme = urlparse(normalized_url).scheme.lower()
    if scheme in {"postgres", "postgresql"}:
        raise RuntimeError(
            "PostgreSQL is configured but the PostgreSQL backend is not implemented yet."
        )

    raise ValueError(f"Unsupported database URL scheme: {scheme or '<missing>'}.")
