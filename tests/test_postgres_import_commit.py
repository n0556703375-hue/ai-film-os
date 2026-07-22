import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database.migration_preflight import EXPECTED_TABLES
from app.database.postgres_import_commit import (
    CONFIRMATION_PHRASE,
    import_sqlite_to_postgres,
)
from app.database.postgres_import_dry_run import TABLE_ORDER


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
        self.commit_calls = 0
        self.rollback_calls = 0
        self.close_calls = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.close_calls += 1


class PersistentPostgresImportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.source_path = Path(self.temp_dir.name) / "source.db"
        self.backup_path = Path(self.temp_dir.name) / "backup.db"
        self._create_contract_database(self.source_path)
        source = sqlite3.connect(self.source_path)
        backup = sqlite3.connect(self.backup_path)
        try:
            source.backup(backup)
        finally:
            source.close()
            backup.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_contract_database(self, path: Path):
        connection = sqlite3.connect(path)
        try:
            for table in EXPECTED_TABLES:
                connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
            connection.execute("INSERT INTO projects (id) VALUES (1)")
            connection.commit()
        finally:
            connection.close()

    def _source_connect(self):
        return sqlite3.connect(self.source_path)

    def _backup_connect(self):
        return sqlite3.connect(self.backup_path)

    def test_verified_import_commits_once_and_does_not_switch_configuration(self):
        target = FakePostgresConnection()

        result = import_sqlite_to_postgres(
            self.source_path,
            self.backup_path,
            "postgresql://isolated-host/film_os",
            confirmation=CONFIRMATION_PHRASE,
            source_connect=self._source_connect,
            backup_connect=self._backup_connect,
            postgres_connect=lambda _url: target,
        )

        self.assertEqual(result["status"], "imported")
        self.assertTrue(result["backup_verified"])
        self.assertTrue(result["constraints_validated"])
        self.assertTrue(result["committed"])
        self.assertFalse(result["production_configuration_changed"])
        self.assertEqual(result["row_counts"]["projects"], 1)
        self.assertEqual(target.commit_calls, 1)
        self.assertEqual(target.rollback_calls, 0)
        self.assertEqual(target.close_calls, 1)

    def test_wrong_confirmation_blocks_before_postgres_connection(self):
        connection_attempted = False

        def connect(_url):
            nonlocal connection_attempted
            connection_attempted = True
            return FakePostgresConnection()

        with self.assertRaisesRegex(RuntimeError, "confirmation"):
            import_sqlite_to_postgres(
                self.source_path,
                self.backup_path,
                "postgresql://isolated-host/film_os",
                confirmation="yes",
                postgres_connect=connect,
            )

        self.assertFalse(connection_attempted)

    def test_changed_backup_blocks_before_postgres_connection(self):
        backup = sqlite3.connect(self.backup_path)
        try:
            backup.execute("UPDATE projects SET id = 2")
            backup.commit()
        finally:
            backup.close()

        connection_attempted = False

        def connect(_url):
            nonlocal connection_attempted
            connection_attempted = True
            return FakePostgresConnection()

        result = import_sqlite_to_postgres(
            self.source_path,
            self.backup_path,
            "postgresql://isolated-host/film_os",
            confirmation=CONFIRMATION_PHRASE,
            postgres_connect=connect,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "backup_verification_failed")
        self.assertFalse(result["committed"])
        self.assertFalse(connection_attempted)

    def test_nonempty_target_rolls_back_and_never_commits(self):
        target = FakePostgresConnection()
        target.cursor_instance.existing_tables = ["unrelated_table"]

        with self.assertRaisesRegex(RuntimeError, "empty and isolated"):
            import_sqlite_to_postgres(
                self.source_path,
                self.backup_path,
                "postgresql://isolated-host/film_os",
                confirmation=CONFIRMATION_PHRASE,
                source_connect=self._source_connect,
                backup_connect=self._backup_connect,
                postgres_connect=lambda _url: target,
            )

        self.assertEqual(target.commit_calls, 0)
        self.assertEqual(target.rollback_calls, 1)
        self.assertEqual(target.close_calls, 1)

    def test_invalid_url_does_not_echo_credentials(self):
        secret_url = "sqlite://user:super-secret@host/database"

        with self.assertRaises(RuntimeError) as error:
            import_sqlite_to_postgres(
                self.source_path,
                self.backup_path,
                secret_url,
                confirmation=CONFIRMATION_PHRASE,
            )

        self.assertNotIn("super-secret", str(error.exception))
        self.assertNotIn(secret_url, str(error.exception))


if __name__ == "__main__":
    unittest.main()
