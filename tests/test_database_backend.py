import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database.backend import SQLiteBackend, build_database_backend


class DatabaseBackendTests(unittest.TestCase):
    def test_factory_preserves_sqlite_as_default_backend(self):
        backend = build_database_backend(Path("film_os.db"))

        self.assertIsInstance(backend, SQLiteBackend)
        self.assertEqual(backend.name, "sqlite")
        self.assertEqual(backend.database_path, Path("film_os.db"))

    def test_factory_rejects_postgresql_until_backend_is_implemented(self):
        database_url = "postgresql://user:secret@example.test/film_os"

        with self.assertRaisesRegex(RuntimeError, "PostgreSQL backend is not implemented") as error:
            build_database_backend(Path("film_os.db"), database_url)

        self.assertNotIn(database_url, str(error.exception))
        self.assertNotIn("secret", str(error.exception))

    def test_factory_rejects_unknown_database_url_scheme(self):
        with self.assertRaisesRegex(ValueError, "Unsupported database URL scheme: mysql"):
            build_database_backend(Path("film_os.db"), "mysql://example.test/film_os")

    def test_sqlite_connection_enables_foreign_keys_and_row_access(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = SQLiteBackend(Path(directory) / "test.db")
            conn = backend.connect()
            self.addCleanup(conn.close)

            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO sample(value) VALUES (?)", ("ok",))
            row = conn.execute("SELECT id, value FROM sample").fetchone()

            self.assertIsInstance(row, sqlite3.Row)
            self.assertEqual(row["value"], "ok")


if __name__ == "__main__":
    unittest.main()
