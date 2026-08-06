import re
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


# Full definition of the target media_results table. Kept in sync with
# schema.py's CREATE TABLE. Used to rebuild a legacy table whose media_type
# CHECK does not yet allow 'audio'. __TABLE__ is substituted for the (possibly
# temporary) table name; str.format is avoided because the DDL contains braces.
_MEDIA_RESULTS_DDL = """
CREATE TABLE __TABLE__ (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shot_id INTEGER NOT NULL,
    media_type TEXT NOT NULL CHECK(media_type IN ('image', 'video', 'audio')),
    version INTEGER NOT NULL,
    url TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    prompt_version_id INTEGER,
    status TEXT NOT NULL DEFAULT 'טיוטה',
    notes TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(shot_id, media_type, version),
    FOREIGN KEY(shot_id) REFERENCES shots(id) ON DELETE CASCADE,
    FOREIGN KEY(prompt_version_id) REFERENCES prompt_versions(id) ON DELETE SET NULL
)
"""

# Every column, copied explicitly so the migration preserves ids, versions,
# urls, provider/model, status, notes, metadata and timestamps exactly.
_MEDIA_RESULTS_COLUMNS = (
    "id, shot_id, media_type, version, url, provider, model, "
    "prompt_version_id, status, notes, metadata_json, created_at"
)

_MEDIA_TYPE_CHECK_PATTERN = re.compile(
    r"CHECK\s*\(\s*media_type\s+IN\s*\((?P<values>[^)]*)\)\s*\)",
    flags=re.IGNORECASE,
)
_QUOTED_SQL_VALUE_PATTERN = re.compile(r"'([^']*)'")
_EXPECTED_MEDIA_TYPES = frozenset({"image", "video", "audio"})


def _media_type_check_allows_audio(conn: sqlite3.Connection) -> bool:
    """True when media_results is absent or has the exact target CHECK."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='media_results'"
    ).fetchone()
    if not row or not row[0]:
        return True

    match = _MEDIA_TYPE_CHECK_PATTERN.search(row[0])
    if not match:
        return False

    tokens = [token.strip() for token in match.group("values").split(",")]
    values = []
    for token in tokens:
        quoted = _QUOTED_SQL_VALUE_PATTERN.fullmatch(token)
        if not quoted:
            return False
        values.append(quoted.group(1))
    return len(values) == len(_EXPECTED_MEDIA_TYPES) and set(values) == _EXPECTED_MEDIA_TYPES


def _migrate_media_results_media_type(conn: sqlite3.Connection) -> None:
    """Rebuild media_results so media_type allows image/video/audio.

    Changing a CHECK constraint in SQLite requires recreating the table. This
    follows SQLite's documented table-rebuild procedure:

      * It is idempotent — a table that already allows 'audio' is left alone.
      * foreign_keys is turned OFF for the rebuild. Otherwise DROP TABLE would
        perform an implicit DELETE of every media_results row, firing
        approval_events' ON DELETE SET NULL and destroying approval references.
        Since ids are preserved, references stay valid once the new table is in
        place. PRAGMA foreign_keys is a no-op inside a transaction, so the
        migration refuses to commit or roll back a caller-owned transaction.
      * The rebuild runs inside an explicit transaction. Any failure rolls back,
        leaving the original table intact — never a half-rebuilt table.
      * PRAGMA foreign_key_check runs before commit; any row it returns aborts
        the migration (rollback) rather than committing broken references.
      * The AUTOINCREMENT high-water mark is preserved so ids are never reused.

    PRAGMA ignore_check_constraints is never used; unknown media types remain
    rejected throughout.
    """
    if _media_type_check_allows_audio(conn):
        return

    if conn.in_transaction:
        raise RuntimeError(
            "media_results audio migration requires no active transaction."
        )

    foreign_keys_row = conn.execute("PRAGMA foreign_keys").fetchone()
    foreign_keys_enabled = bool(foreign_keys_row[0]) if foreign_keys_row else False

    seq_row = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name='media_results'"
    ).fetchone()
    previous_seq = seq_row[0] if seq_row else None

    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN")
        conn.execute(_MEDIA_RESULTS_DDL.replace("__TABLE__", "_media_results_audio_migration"))
        conn.execute(
            f"INSERT INTO _media_results_audio_migration ({_MEDIA_RESULTS_COLUMNS}) "
            f"SELECT {_MEDIA_RESULTS_COLUMNS} FROM media_results"
        )
        conn.execute("DROP TABLE media_results")
        conn.execute(
            "ALTER TABLE _media_results_audio_migration RENAME TO media_results"
        )
        if previous_seq is not None:
            conn.execute("DELETE FROM sqlite_sequence WHERE name='media_results'")
            conn.execute(
                "INSERT INTO sqlite_sequence(name, seq) VALUES('media_results', ?)",
                (previous_seq,),
            )
        fk_problems = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_problems:
            raise RuntimeError(
                "media_results audio migration produced "
                f"{len(fk_problems)} foreign-key violation(s); rolled back."
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute(
            "PRAGMA foreign_keys=" + ("ON" if foreign_keys_enabled else "OFF")
        )


def migrate_database(conn: sqlite3.Connection) -> None:
    _migrate_media_results_media_type(conn)
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
