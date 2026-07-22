import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database.migration_preflight import EXPECTED_TABLES
from app.database.sqlite_backup_verification import verify_sqlite_backup


class SQLiteBackupVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.source_path = root / "source.db"
        self.backup_path = root / "backup.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_contract_database(self, path: Path, project_rows: int = 1) -> None:
        connection = sqlite3.connect(path)
        try:
            for table in EXPECTED_TABLES:
                connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
            connection.executemany(
                "INSERT INTO projects (id) VALUES (?)",
                [(index + 1,) for index in range(project_rows)],
            )
            connection.commit()
        finally:
            connection.close()

    def test_matching_backup_is_verified_without_exposing_paths(self):
        self._create_contract_database(self.source_path)
        self._create_contract_database(self.backup_path)

        result = verify_sqlite_backup(self.source_path, self.backup_path)

        self.assertEqual(result["status"], "verified")
        self.assertTrue(result["source_ready"])
        self.assertTrue(result["backup_ready"])
        self.assertTrue(result["row_counts_match"])
        self.assertTrue(result["read_only"])
        self.assertNotIn(str(self.source_path), str(result))
        self.assertNotIn(str(self.backup_path), str(result))

    def test_row_count_difference_blocks_cutover(self):
        self._create_contract_database(self.source_path, project_rows=2)
        self._create_contract_database(self.backup_path, project_rows=1)

        result = verify_sqlite_backup(self.source_path, self.backup_path)

        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["row_counts_match"])

    def test_incomplete_backup_blocks_cutover(self):
        self._create_contract_database(self.source_path)
        connection = sqlite3.connect(self.backup_path)
        connection.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY)")
        connection.commit()
        connection.close()

        result = verify_sqlite_backup(self.source_path, self.backup_path)

        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["backup_ready"])

    def test_source_and_backup_must_be_different_files(self):
        self._create_contract_database(self.source_path)

        with self.assertRaisesRegex(RuntimeError, "different files"):
            verify_sqlite_backup(self.source_path, self.source_path)


if __name__ == "__main__":
    unittest.main()
