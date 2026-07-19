import sqlite3
from contextlib import closing
from app.core.config import settings
from app.database.schema import SCHEMA_SQL
from app.database.seed import seed_database

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)

def migrate_database(conn: sqlite3.Connection) -> None:
    if not _column_exists(conn, "shots", "shot_type"):
        conn.execute(
            "ALTER TABLE shots ADD COLUMN shot_type TEXT NOT NULL DEFAULT 'רגיל'"
        )

def init_db() -> None:
    with closing(get_connection()) as conn:
        conn.executescript(SCHEMA_SQL)
        migrate_database(conn)
        seed_database(conn)
        conn.commit()
