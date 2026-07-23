import unittest
from unittest.mock import Mock

from app.database.startup import build_database_startup_adapter


class DatabaseStartupAdapterTests(unittest.TestCase):
    def test_sqlite_startup_runs_schema_migrations_seed_and_commit_in_order(self):
        calls = []
        conn = Mock()
        conn.executescript.side_effect = lambda sql: calls.append(("schema", sql))
        conn.commit.side_effect = lambda: calls.append(("commit", None))

        def migrate(connection):
            self.assertIs(conn, connection)
            calls.append(("migrate", None))

        def seed(connection):
            self.assertIs(conn, connection)
            calls.append(("seed", None))

        startup = build_database_startup_adapter(
            "sqlite",
            schema_sql="CREATE TABLE example (id INTEGER);",
            migrate=migrate,
            seed=seed,
        )

        startup.initialize(conn)

        self.assertEqual(
            [
                ("schema", "CREATE TABLE example (id INTEGER);"),
                ("migrate", None),
                ("seed", None),
                ("commit", None),
            ],
            calls,
        )

    def test_postgresql_startup_remains_fail_closed(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "PostgreSQL startup initialization is not enabled yet",
        ):
            build_database_startup_adapter(
                "postgresql",
                schema_sql="secret-schema",
                migrate=Mock(),
                seed=Mock(),
            )

    def test_unknown_backend_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported database backend"):
            build_database_startup_adapter(
                "unknown",
                schema_sql="",
                migrate=Mock(),
                seed=Mock(),
            )


if __name__ == "__main__":
    unittest.main()
