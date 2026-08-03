import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database.connection import migrate_database
from app.database.postgres_schema import POSTGRES_SCHEMA_SQL
from app.database.schema import SCHEMA_SQL


_TABLE_PATTERN = re.compile(
    r"CREATE TABLE IF NOT EXISTS\s+([a-z_]+)",
    flags=re.IGNORECASE,
)


def _effective_sqlite_schema() -> dict[str, set[str]]:
    """Build the schema the app actually runs with: SCHEMA_SQL plus every
    column/table migrate_database adds at startup. Comparing against just the
    SCHEMA_SQL constant misses everything added incrementally, which is how the
    PostgreSQL contract silently fell behind (missing scene_asset_variants and
    several shot/scene/continuity/prompt-version columns)."""
    with tempfile.TemporaryDirectory() as directory:
        connection = sqlite3.connect(Path(directory) / "schema_probe.db")
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript(SCHEMA_SQL)
            migrate_database(connection)
            connection.commit()
            tables: dict[str, set[str]] = {}
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ):
                table = row["name"]
                tables[table] = {
                    column["name"]
                    for column in connection.execute(f"PRAGMA table_info({table})")
                }
            return tables
        finally:
            connection.close()


def _postgres_schema_columns() -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    for statement in POSTGRES_SCHEMA_SQL.split(";"):
        statement = statement.strip()
        match = re.match(
            r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*)\)", statement, re.DOTALL
        )
        if not match:
            continue
        table, body = match.group(1), match.group(2)
        columns = set()
        for line in body.split(",\n"):
            line = line.strip()
            if not line or line.upper().startswith(
                ("FOREIGN KEY", "UNIQUE", "PRIMARY KEY", "CHECK")
            ):
                continue
            columns.add(line.split()[0].strip('"'))
        tables[table] = columns
    return tables


class PostgreSQLSchemaContractTests(unittest.TestCase):
    def test_postgres_contract_covers_the_base_sqlite_schema_tables(self):
        sqlite_tables = set(_TABLE_PATTERN.findall(SCHEMA_SQL))
        postgres_tables = set(_TABLE_PATTERN.findall(POSTGRES_SCHEMA_SQL))

        self.assertTrue(sqlite_tables.issubset(postgres_tables))
        self.assertEqual(len(sqlite_tables), 11)

    def test_postgres_contract_covers_the_full_effective_runtime_schema(self):
        """Covers tables/columns added by migrate_database, not just SCHEMA_SQL."""
        sqlite_schema = _effective_sqlite_schema()
        postgres_schema = _postgres_schema_columns()

        self.assertEqual(set(postgres_schema), set(sqlite_schema))
        for table, sqlite_columns in sqlite_schema.items():
            with self.subTest(table=table):
                self.assertEqual(postgres_schema[table], sqlite_columns)

    def test_postgres_contract_excludes_sqlite_only_ddl(self):
        normalized = POSTGRES_SCHEMA_SQL.upper()

        self.assertNotIn("AUTOINCREMENT", normalized)
        self.assertNotIn("PRAGMA", normalized)
        self.assertNotIn("INTEGER PRIMARY KEY", normalized)
        self.assertIn("BIGSERIAL PRIMARY KEY", normalized)
        self.assertIn("TIMESTAMPTZ", normalized)
        self.assertIn("DOUBLE PRECISION", normalized)

    def test_postgres_contract_preserves_critical_constraints(self):
        normalized = " ".join(POSTGRES_SCHEMA_SQL.split())

        self.assertIn("UNIQUE(shot_id, media_type, version)", normalized)
        self.assertIn("idempotency_key TEXT NOT NULL UNIQUE", normalized)
        self.assertIn("CHECK(media_type IN ('image', 'video'))", normalized)
        self.assertIn("ON DELETE CASCADE", normalized)
        self.assertIn("ON DELETE SET NULL", normalized)


if __name__ == "__main__":
    unittest.main()
