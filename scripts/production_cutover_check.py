#!/usr/bin/env python3
"""Read-only production cutover readiness check.

Reports PASS/FAIL for each prerequisite needed to safely run the PostgreSQL
cutover tooling (migration_preflight, sqlite_backup_verification,
cutover_readiness, postgres_import_commit). This script never mutates data,
never writes to production, and never performs a migration itself - it only
inspects local environment state, file presence, database connectivity, and
the deployed health endpoint.

It never prints a database URL, DSN, or provider error detail, matching the
same no-credential-leak discipline as the rest of the migration tooling.

Usage (run from the repository root, same as the other app.database.* CLIs):
    PYTHONPATH=. python3 scripts/production_cutover_check.py [--base-url URL]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def check_required_environment_variables(env: dict[str, str]) -> CheckResult:
    required = ("FILM_OS_DB", "FILM_OS_BACKUP_DB")
    missing = [name for name in required if not env.get(name, "").strip()]
    if missing:
        return CheckResult(
            "required_environment_variables",
            False,
            f"missing: {', '.join(missing)}",
        )
    return CheckResult("required_environment_variables", True, "FILM_OS_DB and FILM_OS_BACKUP_DB are set")


def check_enable_postgresql_state(enable_postgresql: bool) -> CheckResult:
    return CheckResult(
        "enable_postgresql_state",
        True,
        f"ENABLE_POSTGRESQL={'true' if enable_postgresql else 'false'}",
    )


def check_database_url_presence(database_url: str) -> CheckResult:
    normalized = database_url.strip()
    if not normalized:
        return CheckResult("database_url_presence", False, "DATABASE_URL is not set")
    scheme = urlparse(normalized).scheme.lower()
    if scheme not in {"postgres", "postgresql"}:
        return CheckResult("database_url_presence", False, "DATABASE_URL is set but not a PostgreSQL URL")
    return CheckResult("database_url_presence", True, "DATABASE_URL is set to a PostgreSQL URL")


def check_postgresql_connectivity(
    database_url: str,
    *,
    connect: Callable[[str], Any] | None = None,
) -> CheckResult:
    normalized = database_url.strip()
    if not normalized:
        return CheckResult("postgresql_connectivity", False, "cannot connect: DATABASE_URL is not set")

    connector = connect
    if connector is None:
        def connector(url: str) -> Any:
            import psycopg

            return psycopg.connect(url, connect_timeout=5)

    try:
        connection = connector(normalized)
        try:
            connection.execute("SELECT 1")
        finally:
            connection.close()
    except Exception:
        # Never surface the provider exception: it can include the DSN.
        return CheckResult("postgresql_connectivity", False, "connection attempt failed")
    return CheckResult("postgresql_connectivity", True, "connected and executed a read-only probe query")


def check_sqlite_file_exists(database_path: Path) -> CheckResult:
    if not database_path.is_file():
        return CheckResult("sqlite_file_exists", False, "SQLite source file does not exist")
    return CheckResult("sqlite_file_exists", True, "SQLite source file exists")


def check_backup_exists(backup_path: Path | None) -> CheckResult:
    if backup_path is None or not str(backup_path).strip():
        return CheckResult("backup_exists", False, "FILM_OS_BACKUP_DB is not set")
    if not backup_path.is_file():
        return CheckResult("backup_exists", False, "backup file does not exist")
    return CheckResult("backup_exists", True, "backup file exists")


def check_health_endpoint(
    base_url: str | None,
    *,
    request: Callable[[str], dict[str, Any]] | None = None,
) -> CheckResult:
    if not base_url:
        return CheckResult("health_endpoint", False, "no --base-url provided")

    requester = request
    if requester is None:
        def requester(url: str) -> dict[str, Any]:
            with urlopen(url, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))

    url = base_url.rstrip("/") + "/health"
    try:
        payload = requester(url)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return CheckResult("health_endpoint", False, "health endpoint did not respond with a valid response")

    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return CheckResult("health_endpoint", False, "health endpoint did not report status ok")
    return CheckResult("health_endpoint", True, "health endpoint reported status ok")


def run_all_checks(
    *,
    env: dict[str, str],
    database_path: Path,
    enable_postgresql: bool,
    database_url: str,
    backup_path: Path | None,
    base_url: str | None,
    connect: Callable[[str], Any] | None = None,
    request: Callable[[str], dict[str, Any]] | None = None,
) -> list[CheckResult]:
    """Run every prerequisite check. Purely read-only; never mutates state."""
    return [
        check_required_environment_variables(env),
        check_enable_postgresql_state(enable_postgresql),
        check_database_url_presence(database_url),
        check_postgresql_connectivity(database_url, connect=connect),
        check_sqlite_file_exists(database_path),
        check_backup_exists(backup_path),
        check_health_endpoint(base_url, request=request),
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=None,
        help="Deployed service base URL to check /health against (optional).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    from app.core.config import settings

    backup_env = os.environ.get("FILM_OS_BACKUP_DB", "").strip()
    results = run_all_checks(
        env=dict(os.environ),
        database_path=settings.database_path,
        enable_postgresql=settings.enable_postgresql,
        database_url=settings.database_url,
        backup_path=Path(backup_env) if backup_env else None,
        base_url=args.base_url,
    )

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")

    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
