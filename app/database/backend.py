import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


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


def build_database_backend(database_path: Path) -> DatabaseBackend:
    """Build the configured backend while SQLite remains the safe default.

    PostgreSQL support will be added behind this boundary in a separate,
    focused change. This function deliberately performs no environment logging
    and does not alter existing database selection behavior.
    """

    return SQLiteBackend(database_path=database_path)
