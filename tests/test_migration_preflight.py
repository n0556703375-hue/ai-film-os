import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database.migration_preflight import EXPECTED_TABLES, audit_sqlite_source
from app.database.postgres_schema import POSTGRES_SCHEMA_SQL


class TrackingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.close_calls = 0

    def cursor(self):
        return self.connection.cursor()

    def close(self):
        self.close_calls += 1
        self.connection.close()


class MigrationPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "film_os.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_contract_tables(self, connection):
        for table in EXPECTED_TABLES:
            connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        connection.commit()

    def test_complete_source_reports_counts_without_row_contents(self):
        connection = sqlite3.connect(self.database_path)
        self._create_contract_tables(connection)
        connection.execute("INSERT INTO projects (id) VALUES (1)")
        connection.commit()
        tracking = TrackingConnection(connection)

        result = audit_sqlite_source(
            self.database_path,
            connect=lambda: tracking,
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["row_counts"]["projects"], 1)
        self.assertEqual(result["missing_tables"], [])
        self.assertEqual(result["foreign_key_violations"], 0)
        self.assertTrue(result["read_only"])
        self.assertNotIn("film_os.db", str(result))
        self.assertEqual(tracking.close_calls, 1)

    def test_missing_contract_table_blocks_migration(self):
        connection = sqlite3.connect(self.database_path)
        for table in EXPECTED_TABLES:
            if table != "media_jobs":
                connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        connection.commit()

        result = audit_sqlite_source(
            self.database_path,
            connect=lambda: connection,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["missing_tables"], ["media_jobs"])

    def test_foreign_key_violation_blocks_migration(self):
        connection = sqlite3.connect(self.database_path)
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE scenes ("
            "id INTEGER PRIMARY KEY, "
            "project_id INTEGER REFERENCES projects(id))"
        )
        for table in EXPECTED_TABLES:
            if table not in {"projects", "scenes"}:
                connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        connection.execute("INSERT INTO scenes (id, project_id) VALUES (1, 999)")
        connection.commit()

        result = audit_sqlite_source(
            self.database_path,
            connect=lambda: connection,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["foreign_key_violations"], 1)

    def test_contract_table_parser_matches_postgres_schema(self):
        self.assertEqual(len(EXPECTED_TABLES), 11)
        for table in EXPECTED_TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", POSTGRES_SCHEMA_SQL)


if __name__ == "__main__":
    unittest.main()
