import unittest

from app.database.validate_postgres_schema import (
    EXPECTED_TABLES,
    validate_postgres_schema,
    validate_postgres_startup_connection,
)


class FakeCursor:
    def __init__(self, tables=None, error=None, *, dictionary_rows=True):
        self.tables = tables or set()
        self.error = error
        self.dictionary_rows = dictionary_rows
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
        if self.dictionary_rows:
            return [{"table_name": table} for table in self.tables]
        return [(table,) for table in self.tables]


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.rollback_calls = 0
        self.close_calls = 0
        self.commit_calls = 0

    def cursor(self):
        return self._cursor

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.close_calls += 1

    def commit(self):
        self.commit_calls += 1


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
        self.assertGreater(len(cursor.executed), 2)

    def test_tuple_rows_remain_supported_for_test_connections(self):
        cursor = FakeCursor(tables=EXPECTED_TABLES, dictionary_rows=False)
        connection = FakeConnection(cursor)

        result = validate_postgres_schema(
            "postgresql://user:secret@example.test/film_os_test",
            connect=lambda: connection,
        )

        self.assertEqual(result["status"], "valid")
        self.assertEqual(connection.rollback_calls, 1)
        self.assertEqual(connection.close_calls, 1)

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

    def test_startup_validation_is_read_only_and_leaves_connection_open(self):
        cursor = FakeCursor(tables=EXPECTED_TABLES)
        connection = FakeConnection(cursor)

        validate_postgres_startup_connection(connection)

        self.assertEqual(len(cursor.executed), 1)
        self.assertIn("information_schema.tables", cursor.executed[0])
        self.assertEqual(connection.commit_calls, 0)
        self.assertEqual(connection.rollback_calls, 0)
        self.assertEqual(connection.close_calls, 0)

    def test_startup_validation_fails_closed_without_exposing_provider_error(self):
        cursor = FakeCursor(error=Exception("password=secret"))
        connection = FakeConnection(cursor)

        with self.assertRaisesRegex(RuntimeError, "startup schema validation failed") as error:
            validate_postgres_startup_connection(connection)

        self.assertNotIn("secret", str(error.exception))
        self.assertEqual(connection.commit_calls, 0)
        self.assertEqual(connection.rollback_calls, 0)
        self.assertEqual(connection.close_calls, 0)


if __name__ == "__main__":
    unittest.main()
