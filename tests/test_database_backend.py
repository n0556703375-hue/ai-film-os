import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from app.database.backend import (
    PostgreSQLBackend,
    SQLiteBackend,
    build_database_backend,
)


class DatabaseBackendTests(unittest.TestCase):
    def test_factory_preserves_sqlite_as_default_backend(self):
        backend = build_database_backend(Path("film_os.db"))

        self.assertIsInstance(backend, SQLiteBackend)
        self.assertEqual(backend.name, "sqlite")
        self.assertEqual(backend.database_path, Path("film_os.db"))

    def test_factory_keeps_postgresql_activation_fail_closed(self):
        database_url = "postgresql://user:secret@example.test/film_os"

        with self.assertRaisesRegex(RuntimeError, "production activation is not enabled") as error:
            build_database_backend(Path("film_os.db"), database_url)

        self.assertNotIn(database_url, str(error.exception))
        self.assertNotIn("secret", str(error.exception))

    def test_factory_rejects_unknown_database_url_scheme(self):
        with self.assertRaisesRegex(ValueError, "Unsupported database URL scheme: mysql"):
            build_database_backend(Path("film_os.db"), "mysql://example.test/film_os")

    def test_postgresql_adapter_rejects_non_postgresql_url(self):
        with self.assertRaisesRegex(ValueError, "requires a PostgreSQL database URL"):
            PostgreSQLBackend("sqlite:///film_os.db")

    def test_postgresql_adapter_uses_dict_rows_without_logging_url(self):
        database_url = "postgresql://user:secret@example.test/film_os"
        sentinel_connection = object()
        sentinel_row_factory = object()
        calls = []

        psycopg_module = ModuleType("psycopg")
        rows_module = ModuleType("psycopg.rows")
        rows_module.dict_row = sentinel_row_factory

        def fake_connect(url, *, row_factory):
            calls.append((url, row_factory))
            return sentinel_connection

        psycopg_module.connect = fake_connect

        with patch.dict(
            "sys.modules",
            {"psycopg": psycopg_module, "psycopg.rows": rows_module},
        ):
            connection = PostgreSQLBackend(database_url).connect()

        self.assertIs(connection, sentinel_connection)
        self.assertEqual(calls, [(database_url, sentinel_row_factory)])

    def test_postgresql_adapter_redacts_provider_connection_errors(self):
        database_url = "postgresql://user:secret@example.test/film_os"
        psycopg_module = ModuleType("psycopg")
        rows_module = ModuleType("psycopg.rows")
        rows_module.dict_row = object()

        def fake_connect(url, *, row_factory):
            raise RuntimeError(f"could not connect to {url}")

        psycopg_module.connect = fake_connect

        with patch.dict(
            "sys.modules",
            {"psycopg": psycopg_module, "psycopg.rows": rows_module},
        ):
            with self.assertRaisesRegex(RuntimeError, "PostgreSQL connection failed") as error:
                PostgreSQLBackend(database_url).connect()

        self.assertNotIn(database_url, str(error.exception))
        self.assertNotIn("secret", str(error.exception))

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
