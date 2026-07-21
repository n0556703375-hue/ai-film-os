import unittest

from app.database.validate_postgres_schema import (
    EXPECTED_TABLES,
    validate_postgres_schema,
)


class FakeCursor:
    def __init__(self, tables=None, error=None):
        self.tables = tables or set()
        self.error = error
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement):
        self.executed.append(statement)
        if self.error is not None:
            raise self.error

    def fetchall(self):
        return [(table,) for table in self.tables]


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.rollback_calls = 0
        self.close_calls = 0

    def cursor(self):
        return self._cursor

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.close_calls += 1


class PostgreSQLSchemaValidationTests(unittest.TestCase):
    def test_valid_schema_is_inspected_and_always_rolled_back(self):
        cursor = FakeCursor(tables=EXPECTED_TABLES)
        connection = FakeConnection(cursor)

        result = validate_postgres_schema(
            "postgresql://user:secret@example.test/film_os_test",
            connect=lambda: connection,
        )

        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["table_count"], len(EXPECTED_TABLES))
        self.assertTrue(result["rolled_back"])
        self.assertEqual(connection.rollback_calls, 1)
        self.assertEqual(connection.close_calls, 1)
        self.assertEqual(len(cursor.executed), 2)

    def test_missing_table_fails_without_persisting_changes(self):
        cursor = FakeCursor(tables=EXPECTED_TABLES - {"media_jobs"})
        connection = FakeConnection(cursor)

        with self.assertRaisesRegex(RuntimeError, "expected tables are missing"):
            validate_postgres_schema(
                "postgresql://user:secret@example.test/film_os_test",
                connect=lambda: connection,
            )

        self.assertEqual(connection.rollback_calls, 1)
        self.assertEqual(connection.close_calls, 1)

    def test_provider_errors_are_redacted_and_rolled_back(self):
        cursor = FakeCursor(error=Exception("password=secret"))
        connection = FakeConnection(cursor)

        with self.assertRaisesRegex(RuntimeError, "schema validation failed") as error:
            validate_postgres_schema(
                "postgresql://user:secret@example.test/film_os_test",
                connect=lambda: connection,
            )

        self.assertNotIn("secret", str(error.exception))
        self.assertEqual(connection.rollback_calls, 1)
        self.assertEqual(connection.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
