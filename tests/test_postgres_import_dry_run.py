import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database.migration_preflight import EXPECTED_TABLES
from app.database.postgres_import_dry_run import (
    TABLE_ORDER,
    dry_run_sqlite_to_postgres,
)


class FakePostgresCursor:
    def __init__(self):
        self.counts = {table: 0 for table in TABLE_ORDER}
        self.existing_tables = []
        self._row = None
        self._rows = []
        self.constraints_checked = False

    def execute(self, statement, params=None):
        normalized = statement.strip()
        if normalized.startswith("SELECT tablename FROM pg_catalog.pg_tables"):
            self._rows = [(table,) for table in self.existing_tables]
        else:
            count_match = re.fullmatch(
                r'SELECT COUNT\(\*\) FROM "([A-Za-z_][A-Za-z0-9_]*)"',
                normalized,
            )
            if count_match:
                self._row = (self.counts[count_match.group(1)],)
            elif normalized == "SET CONSTRAINTS ALL IMMEDIATE":
                self.constraints_checked = True
        return self

    def executemany(self, statement, rows):
        match = re.match(r'INSERT INTO "([A-Za-z_][A-Za-z0-9_]*)"', statement)
        if not match:
            raise AssertionError(f"Unexpected insert statement: {statement}")
        self.counts[match.group(1)] += len(rows)

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class FakePostgresConnection:
    def __init__(self):
        self.cursor_instance = FakePostgresCursor()
        self.rollback_calls = 0
        self.close_calls = 0

    def cursor(self):
        return self.cursor_instance

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.close_calls += 1


class PostgresImportDryRunTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "film_os.db"
        connection = sqlite3.connect(self.database_path)
        for table in EXPECTED_TABLES:
            connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        connection.execute("INSERT INTO projects (id) VALUES (1)")
        connection.commit()
        connection.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _sqlite_connect(self):
        return sqlite3.connect(self.database_path)

    def test_validates_counts_and_always_rolls_back(self):
        target = FakePostgresConnection()

        result = dry_run_sqlite_to_postgres(
            self.database_path,
            "postgresql://validation-host/film_os",
            sqlite_connect=self._sqlite_connect,
            postgres_connect=lambda _url: target,
        )

        self.assertEqual(result["status"], "validated")
        self.assertEqual(result["row_counts"]["projects"], 1)
        self.assertTrue(result["constraints_validated"])
        self.assertTrue(result["rolled_back"])
        self.assertTrue(target.cursor_instance.constraints_checked)
        self.assertEqual(target.rollback_calls, 1)
        self.assertEqual(target.close_calls, 1)

    def test_nonempty_contract_table_fails_and_rolls_back(self):
        target = FakePostgresConnection()
        target.cursor_instance.counts["projects"] = 1

        with self.assertRaisesRegex(RuntimeError, "must be empty"):
            dry_run_sqlite_to_postgres(
                self.database_path,
                "postgresql://validation-host/film_os",
                sqlite_connect=self._sqlite_connect,
                postgres_connect=lambda _url: target,
            )

        self.assertEqual(target.rollback_calls, 1)
        self.assertEqual(target.close_calls, 1)

    def test_any_preexisting_table_blocks_before_schema_application(self):
        target = FakePostgresConnection()
        target.cursor_instance.existing_tables = ["unrelated_app_table"]

        with self.assertRaisesRegex(RuntimeError, "must be empty"):
            dry_run_sqlite_to_postgres(
                self.database_path,
                "postgresql://validation-host/film_os",
                sqlite_connect=self._sqlite_connect,
                postgres_connect=lambda _url: target,
            )

        self.assertFalse(target.cursor_instance.constraints_checked)
        self.assertEqual(target.rollback_calls, 1)
        self.assertEqual(target.close_calls, 1)

    def test_invalid_url_does_not_echo_credentials(self):
        secret_url = "sqlite://user:super-secret@host/database"

        with self.assertRaises(RuntimeError) as error:
            dry_run_sqlite_to_postgres(
                self.database_path,
                secret_url,
                sqlite_connect=self._sqlite_connect,
            )

        self.assertNotIn("super-secret", str(error.exception))
        self.assertNotIn(secret_url, str(error.exception))

    def test_table_order_covers_contract(self):
        self.assertEqual(set(TABLE_ORDER), set(EXPECTED_TABLES))
        self.assertEqual(TABLE_ORDER[0], "projects")
        self.assertEqual(TABLE_ORDER[-1], "media_jobs")


if __name__ == "__main__":
    unittest.main()
