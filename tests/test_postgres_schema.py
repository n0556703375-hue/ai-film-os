import re
import unittest

from app.database.postgres_schema import POSTGRES_SCHEMA_SQL
from app.database.schema import SCHEMA_SQL


_TABLE_PATTERN = re.compile(
    r"CREATE TABLE IF NOT EXISTS\s+([a-z_]+)",
    flags=re.IGNORECASE,
)


class PostgreSQLSchemaContractTests(unittest.TestCase):
    def test_postgres_contract_covers_every_sqlite_table(self):
        sqlite_tables = set(_TABLE_PATTERN.findall(SCHEMA_SQL))
        postgres_tables = set(_TABLE_PATTERN.findall(POSTGRES_SCHEMA_SQL))

        self.assertEqual(postgres_tables, sqlite_tables)
        self.assertEqual(len(postgres_tables), 11)

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
