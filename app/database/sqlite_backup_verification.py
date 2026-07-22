"""Read-only verification gate for a SQLite cutover backup.

The command compares migration contract coverage, row counts, content, and
foreign-key integrity between the active SQLite source and a separately created
backup. It never writes either database and never prints filesystem paths, row
contents, or content fingerprints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.database.migration_preflight import EXPECTED_TABLES, audit_sqlite_source


def _read_only_connect(path: Path) -> Any:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def _encode_value(value: Any) -> bytes:
    if value is None:
        return b"null:"
    if isinstance(value, bytes):
        return b"bytes:" + value.hex().encode("ascii")
    return f"{type(value).__name__}:{value}".encode("utf-8")


def _content_fingerprints(
    path: Path,
    *,
    connect: Callable[[], Any] | None = None,
) -> dict[str, str]:
    connection = connect() if connect is not None else _read_only_connect(path)
    try:
        fingerprints: dict[str, str] = {}
        cursor = connection.cursor()
        for table in EXPECTED_TABLES:
            cursor.execute(f'PRAGMA table_info("{table}")')
            columns = [str(row[1]) for row in cursor.fetchall()]
            if not columns:
                raise RuntimeError("SQLite backup table has no columns.")

            quoted_columns = ", ".join(f'"{column}"' for column in columns)
            order_by = ", ".join(f'"{column}"' for column in columns)
            cursor.execute(
                f'SELECT {quoted_columns} FROM "{table}" ORDER BY {order_by}'
            )

            digest = hashlib.sha256()
            digest.update(json.dumps(columns, separators=(",", ":")).encode("utf-8"))
            for row in cursor.fetchall():
                for value in row:
                    encoded = _encode_value(value)
                    digest.update(len(encoded).to_bytes(8, "big"))
                    digest.update(encoded)
            fingerprints[table] = digest.hexdigest()
        return fingerprints
    finally:
        connection.close()


def verify_sqlite_backup(
    source_path: Path,
    backup_path: Path,
    *,
    source_connect: Callable[[], Any] | None = None,
    backup_connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Verify that a separate SQLite backup matches the migration source."""

    if source_path.resolve() == backup_path.resolve():
        raise RuntimeError("SQLite source and backup must be different files.")

    source_factory = source_connect or (lambda: _read_only_connect(source_path))
    backup_factory = backup_connect or (lambda: _read_only_connect(backup_path))

    try:
        source = audit_sqlite_source(source_path, connect=source_factory)
        backup = audit_sqlite_source(backup_path, connect=backup_factory)
        source_fingerprints = _content_fingerprints(
            source_path,
            connect=source_factory,
        )
        backup_fingerprints = _content_fingerprints(
            backup_path,
            connect=backup_factory,
        )
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("SQLite backup verification failed.") from None

    source_ready = source["status"] == "ready"
    backup_ready = backup["status"] == "ready"
    counts_match = source["row_counts"] == backup["row_counts"]
    content_match = source_fingerprints == backup_fingerprints
    verified = source_ready and backup_ready and counts_match and content_match

    return {
        "status": "verified" if verified else "blocked",
        "source_ready": source_ready,
        "backup_ready": backup_ready,
        "row_counts_match": counts_match,
        "content_match": content_match,
        "table_count": len(source["row_counts"]),
        "source_row_counts": source["row_counts"],
        "backup_row_counts": backup["row_counts"],
        "read_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a SQLite backup without modifying either database."
    )
    parser.add_argument(
        "--confirm-read-only",
        action="store_true",
        help="Required acknowledgement that this command performs verification only.",
    )
    args = parser.parse_args()
    if not args.confirm_read_only:
        parser.error("--confirm-read-only is required")

    source_path = Path(os.getenv("FILM_OS_DB", "film_os.db"))
    backup_value = os.getenv("FILM_OS_BACKUP_DB", "")
    if not backup_value:
        raise RuntimeError("FILM_OS_BACKUP_DB is required.")

    result = verify_sqlite_backup(source_path, Path(backup_value))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
