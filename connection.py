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

def init_db() -> None:
    with closing(get_connection()) as conn:
        conn.executescript(SCHEMA_SQL)
        seed_database(conn)
        conn.commit()
