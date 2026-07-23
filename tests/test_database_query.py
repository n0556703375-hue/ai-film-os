import sqlite3
import unittest
from unittest.mock import Mock

from app.database.query import adapt_qmark_sql, execute_query


class DatabaseQueryTests(unittest.TestCase):
    def test_sqlite_keeps_qmark_placeholders(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)

        sql = "SELECT ? AS value"

        self.assertEqual(adapt_qmark_sql(sql, connection), sql)
        self.assertEqual(execute_query(connection, sql, (7,)).fetchone()[0], 7)

    def test_postgresql_style_connection_uses_percent_s_placeholders(self):
        connection = Mock()
        cursor = object()
        connection.execute.return_value = cursor

        result = execute_query(
            connection,
            "SELECT * FROM projects WHERE id=? AND name=?",
            (3, "Demo"),
        )

        self.assertIs(result, cursor)
        connection.execute.assert_called_once_with(
            "SELECT * FROM projects WHERE id=%s AND name=%s",
            (3, "Demo"),
        )

    def test_literal_question_marks_are_not_rewritten(self):
        connection = Mock()
        sql = "SELECT '?' AS marker, 'it''s ?' AS text FROM projects WHERE id=?"

        self.assertEqual(
            adapt_qmark_sql(sql, connection),
            "SELECT '?' AS marker, 'it''s ?' AS text FROM projects WHERE id=%s",
        )


if __name__ == "__main__":
    unittest.main()
