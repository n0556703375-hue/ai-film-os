import unittest
from pathlib import Path

from app.database.backend import build_database_backend


class PostgreSQLRuntimeActivationGuardTests(unittest.TestCase):
    def test_runtime_backend_factory_fails_closed_for_postgresql(self):
        database_url = "postgresql://runtime-user:runtime-password@db.example/film_os"

        with self.assertRaisesRegex(
            RuntimeError,
            "PostgreSQL is configured but production activation is not enabled yet",
        ) as raised:
            build_database_backend(Path("unused.sqlite3"), database_url)

        message = str(raised.exception)
        self.assertNotIn(database_url, message)
        self.assertNotIn("runtime-user", message)
        self.assertNotIn("runtime-password", message)

    def test_sqlite_remains_the_runtime_default_without_database_url(self):
        backend = build_database_backend(Path("film_os.sqlite3"), "")

        self.assertEqual("sqlite", backend.name)


if __name__ == "__main__":
    unittest.main()
