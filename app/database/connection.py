import sqlite3
from contextlib import closing

from app.core.config import settings
from app.database.backend import build_database_backend
from app.database.schema import SCHEMA_SQL
from app.database.seed import seed_database
from app.database.startup import build_database_startup_adapter
from app.database.validate_postgres_schema import validate_postgres_startup_connection


def get_database_backend():
    return build_database_backend(
        settings.database_path,
        settings.database_url,
        enable_postgresql=settings.enable_postgresql,
    )


def get_connection() -> sqlite3.Connection:
    return get_database_backend().connect()


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
        "original_heading": "TEXT NOT NULL DEFAULT ''",
        "normalized_heading": "TEXT NOT NULL DEFAULT ''",
        "int_ext": "TEXT NOT NULL DEFAULT ''",
        "location": "TEXT NOT NULL DEFAULT ''",
        "time_of_day": "TEXT NOT NULL DEFAULT ''",
        "raw_scene_text": "TEXT NOT NULL DEFAULT ''",
        "synopsis": "TEXT NOT NULL DEFAULT ''",
        "import_run_id": "INTEGER",
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
        "provider_task_id": "TEXT NOT NULL DEFAULT ''",
    })
    conn.execute("""
        CREATE TABLE IF NOT EXISTS import_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'paste',
            source_filename TEXT NOT NULL DEFAULT '',
            source_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'review_required',
            parser_version TEXT NOT NULL DEFAULT '1',
            screenplay_text TEXT NOT NULL DEFAULT '',
            breakdown_json TEXT NOT NULL DEFAULT '{}',
            warnings_json TEXT NOT NULL DEFAULT '[]',
            scene_count INTEGER NOT NULL DEFAULT 0,
            character_count INTEGER NOT NULL DEFAULT 0,
            location_count INTEGER NOT NULL DEFAULT 0,
            prop_count INTEGER NOT NULL DEFAULT 0,
            error_category TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            approved_at TEXT,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scene_content_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scene_id INTEGER NOT NULL,
            block_order INTEGER NOT NULL,
            block_type TEXT NOT NULL,
            character_name TEXT NOT NULL DEFAULT '',
            parenthetical TEXT NOT NULL DEFAULT '',
            raw_text TEXT NOT NULL DEFAULT '',
            confidence TEXT NOT NULL DEFAULT 'high',
            FOREIGN KEY(scene_id) REFERENCES scenes(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS screenplay_characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            canonical_name TEXT NOT NULL,
            aliases_json TEXT NOT NULL DEFAULT '[]',
            first_appearance_scene_number INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id, canonical_name),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS screenplay_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            canonical_name TEXT NOT NULL,
            aliases_json TEXT NOT NULL DEFAULT '[]',
            first_appearance_scene_number INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id, canonical_name),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scene_characters (
            scene_id INTEGER NOT NULL,
            screenplay_character_id INTEGER NOT NULL,
            PRIMARY KEY(scene_id, screenplay_character_id),
            FOREIGN KEY(scene_id) REFERENCES scenes(id) ON DELETE CASCADE,
            FOREIGN KEY(screenplay_character_id) REFERENCES screenplay_characters(id) ON DELETE CASCADE
        )
    """)
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
    backend = get_database_backend()
    startup = build_database_startup_adapter(
        backend.name,
        schema_sql=SCHEMA_SQL,
        migrate=migrate_database,
        seed=seed_database,
        enable_postgresql=settings.enable_postgresql,
        validate_postgresql=validate_postgres_startup_connection,
    )
    with closing(backend.connect()) as conn:
        startup.initialize(conn)
