import sqlite3
from typing import Any, Iterable


def adapt_qmark_sql(sql: str, connection: Any) -> str:
    """Adapt DB-API qmark placeholders for the active connection.

    SQLite uses ``?`` while psycopg uses ``%s``. Only placeholders outside
    quoted SQL string literals are rewritten, so literal question marks remain
    unchanged.
    """

    if isinstance(connection, sqlite3.Connection):
        return sql

    output: list[str] = []
    in_single_quote = False
    index = 0
    while index < len(sql):
        char = sql[index]
        if char == "'":
            output.append(char)
            if in_single_quote and index + 1 < len(sql) and sql[index + 1] == "'":
                output.append("'")
                index += 2
                continue
            in_single_quote = not in_single_quote
        elif char == "?" and not in_single_quote:
            output.append("%s")
        else:
            output.append(char)
        index += 1

    return "".join(output)


def execute_query(connection: Any, sql: str, params: Iterable[Any] = ()) -> Any:
    """Execute one parameterized statement using the connection's paramstyle."""

    return connection.execute(adapt_qmark_sql(sql, connection), tuple(params))
