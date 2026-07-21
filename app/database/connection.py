import sqlite3
from contextlib import closing

from app.core.config import settings
from app.database.backend import build_database_backend
from app.database.schema import SCHEMA_SQL
from app.database.seed import seed_database


def get_connection() -> sqlite3.Connection:
    return build_database_backend(
        settings.database_path,
        settings.database_url,
    ).connect()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _add_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    for name, definition in columns.items():
        if not _column_exists(conn, table, name):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def migrate_database(conn: sqlite3.Connection) -> None:
    _add_columns(conn, "shots", {
        "shot_type": "TEXT NOT NULL DEFAULT 'רגיל'",
        "duration_seconds": "REAL",
        "camera_angle": "TEXT NOT NULL DEFAULT ''",
        "composition": "TEXT NOT NULL DEFAULT ''",
        "action": "TEXT NOT NULL DEFAULT ''",
        "color_palette": "TEXT NOT NULL DEFAULT ''",
        "audio": "TEXT NOT NULL DEFAULT ''",
        "negative_prompt": "TEXT NOT NULL DEFAULT ''",
    })
    _add_columns(conn, "scenes", {
        "status": "TEXT NOT NULL DEFAULT 'מתוכנן'",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    })
    _add_columns(conn, "assets", {
        "lock_status": "TEXT NOT NULL DEFAULT 'draft'",
        "master_reference_id": "INTEGER",
        "locked_at": "TEXT",
    })
    _add_columns(conn, "asset_reference_images", {
        "approved": "INTEGER NOT NULL DEFAULT 0",
    })
    _add_columns(conn, "prompt_versions", {
        "negative_prompt": "TEXT NOT NULL DEFAULT ''",
        "source": "TEXT NOT NULL DEFAULT 'manual'",
    })
    _add_columns(conn, "continuity_issues", {
        "status": "TEXT NOT NULL DEFAULT 'פתוח'",
        "expected": "TEXT NOT NULL DEFAULT ''",
        "observed": "TEXT NOT NULL DEFAULT ''",
        "resolution": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    })
    _add_columns(conn, "media_jobs", {
        "estimated_cost_usd": "REAL NOT NULL DEFAULT 0",
        "actual_cost_usd": "REAL NOT NULL DEFAULT 0",
    })
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scene_asset_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scene_id INTEGER NOT NULL,
            asset_id INTEGER NOT NULL,
            state_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            reference_url TEXT NOT NULL DEFAULT '',
            visual_rules TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(scene_id, asset_id),
            FOREIGN KEY(scene_id) REFERENCES scenes(id) ON DELETE CASCADE,
            FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        UPDATE continuity_issues
        SET status=CASE WHEN resolved=1 THEN 'נפתר' ELSE 'פתוח' END
        WHERE status='' OR status IS NULL
    """)


def init_db() -> None:
    with closing(get_connection()) as conn:
        conn.executescript(SCHEMA_SQL)
        migrate_database(conn)
        seed_database(conn)
        conn.commit()
