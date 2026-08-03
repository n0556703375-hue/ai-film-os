import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.production_cutover_check import (
    check_backup_exists,
    check_database_url_presence,
    check_enable_postgresql_state,
    check_health_endpoint,
    check_postgresql_connectivity,
    check_required_environment_variables,
    check_sqlite_file_exists,
    run_all_checks,
)


class RequiredEnvironmentVariablesTests(unittest.TestCase):
    def test_passes_when_both_vars_are_set(self):
        result = check_required_environment_variables(
            {"FILM_OS_DB": "film_os.db", "FILM_OS_BACKUP_DB": "backup.db"}
        )
        self.assertTrue(result.passed)

    def test_fails_when_a_var_is_missing(self):
        result = check_required_environment_variables({"FILM_OS_DB": "film_os.db"})
        self.assertFalse(result.passed)
        self.assertIn("FILM_OS_BACKUP_DB", result.detail)

    def test_fails_when_both_vars_are_missing(self):
        result = check_required_environment_variables({})
        self.assertFalse(result.passed)
        self.assertIn("FILM_OS_DB", result.detail)
        self.assertIn("FILM_OS_BACKUP_DB", result.detail)


class EnablePostgresqlStateTests(unittest.TestCase):
    def test_reports_true(self):
        result = check_enable_postgresql_state(True)
        self.assertTrue(result.passed)
        self.assertIn("true", result.detail)

    def test_reports_false(self):
        result = check_enable_postgresql_state(False)
        self.assertTrue(result.passed)
        self.assertIn("false", result.detail)


class DatabaseUrlPresenceTests(unittest.TestCase):
    def test_fails_when_unset(self):
        result = check_database_url_presence("")
        self.assertFalse(result.passed)

    def test_fails_for_non_postgres_scheme(self):
        result = check_database_url_presence("sqlite:///film_os.db")
        self.assertFalse(result.passed)

    def test_passes_for_postgres_url(self):
        result = check_database_url_presence("postgresql://user:pass@host/db")
        self.assertTrue(result.passed)

    def test_never_echoes_the_url_value(self):
        secret_url = "postgresql://user:super-secret@host/db"
        result = check_database_url_presence(secret_url)
        self.assertNotIn("super-secret", result.detail)
        self.assertNotIn(secret_url, result.detail)


class PostgresqlConnectivityTests(unittest.TestCase):
    def test_fails_without_database_url(self):
        result = check_postgresql_connectivity("")
        self.assertFalse(result.passed)

    def test_passes_when_connection_succeeds(self):
        connection = Mock()
        result = check_postgresql_connectivity(
            "postgresql://user:pass@host/db",
            connect=lambda url: connection,
        )
        self.assertTrue(result.passed)
        connection.execute.assert_called_once_with("SELECT 1")
        connection.close.assert_called_once_with()

    def test_fails_when_connection_raises_without_leaking_credentials(self):
        secret_url = "postgresql://user:super-secret@host/db"

        def failing_connect(url):
            raise RuntimeError(f"could not connect to {url}")

        result = check_postgresql_connectivity(secret_url, connect=failing_connect)

        self.assertFalse(result.passed)
        self.assertNotIn("super-secret", result.detail)
        self.assertNotIn(secret_url, result.detail)

    def test_closes_connection_even_when_execute_raises(self):
        connection = Mock()
        connection.execute.side_effect = RuntimeError("boom")

        result = check_postgresql_connectivity(
            "postgresql://user:pass@host/db",
            connect=lambda url: connection,
        )

        self.assertFalse(result.passed)
        connection.close.assert_called_once_with()


class SqliteFileExistsTests(unittest.TestCase):
    def test_fails_when_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            result = check_sqlite_file_exists(Path(directory) / "missing.db")
        self.assertFalse(result.passed)

    def test_passes_when_present(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "film_os.db"
            path.write_bytes(b"")
            result = check_sqlite_file_exists(path)
        self.assertTrue(result.passed)


class BackupExistsTests(unittest.TestCase):
    def test_fails_when_not_configured(self):
        result = check_backup_exists(None)
        self.assertFalse(result.passed)

    def test_fails_when_configured_but_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            result = check_backup_exists(Path(directory) / "missing-backup.db")
        self.assertFalse(result.passed)

    def test_passes_when_present(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.db"
            path.write_bytes(b"")
            result = check_backup_exists(path)
        self.assertTrue(result.passed)


class HealthEndpointTests(unittest.TestCase):
    def test_fails_without_base_url(self):
        result = check_health_endpoint(None)
        self.assertFalse(result.passed)

    def test_passes_when_status_ok(self):
        result = check_health_endpoint(
            "https://example.invalid",
            request=lambda url: {"status": "ok", "version": "1.0"},
        )
        self.assertTrue(result.passed)

    def test_fails_when_status_is_not_ok(self):
        result = check_health_endpoint(
            "https://example.invalid",
            request=lambda url: {"status": "degraded"},
        )
        self.assertFalse(result.passed)

    def test_fails_when_request_raises(self):
        def raising_request(url):
            raise OSError("network unreachable")

        result = check_health_endpoint("https://example.invalid", request=raising_request)
        self.assertFalse(result.passed)

    def test_requests_the_health_path(self):
        seen_urls = []

        def request(url):
            seen_urls.append(url)
            return {"status": "ok"}

        check_health_endpoint("https://example.invalid/", request=request)

        self.assertEqual(seen_urls, ["https://example.invalid/health"])


class RunAllChecksTests(unittest.TestCase):
    def test_never_mutates_the_filesystem(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "film_os.db"
            db_path.write_bytes(b"")
            backup_path = Path(directory) / "backup.db"
            backup_path.write_bytes(b"")
            before = sorted(Path(directory).iterdir())

            run_all_checks(
                env={"FILM_OS_DB": str(db_path), "FILM_OS_BACKUP_DB": str(backup_path)},
                database_path=db_path,
                enable_postgresql=False,
                database_url="",
                backup_path=backup_path,
                base_url=None,
                connect=lambda url: Mock(),
                request=lambda url: {"status": "ok"},
            )

            after = sorted(Path(directory).iterdir())
            self.assertEqual(before, after)

    def test_returns_one_result_per_check(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "film_os.db"
            db_path.write_bytes(b"")
            results = run_all_checks(
                env={},
                database_path=db_path,
                enable_postgresql=False,
                database_url="",
                backup_path=None,
                base_url=None,
            )
        self.assertEqual(
            {result.name for result in results},
            {
                "required_environment_variables",
                "enable_postgresql_state",
                "database_url_presence",
                "postgresql_connectivity",
                "sqlite_file_exists",
                "backup_exists",
                "health_endpoint",
            },
        )

    def test_all_pass_when_every_prerequisite_is_satisfied(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "film_os.db"
            db_path.write_bytes(b"")
            backup_path = Path(directory) / "backup.db"
            backup_path.write_bytes(b"")

            results = run_all_checks(
                env={"FILM_OS_DB": str(db_path), "FILM_OS_BACKUP_DB": str(backup_path)},
                database_path=db_path,
                enable_postgresql=True,
                database_url="postgresql://user:pass@host/db",
                backup_path=backup_path,
                base_url="https://example.invalid",
                connect=lambda url: Mock(),
                request=lambda url: {"status": "ok"},
            )

        self.assertTrue(all(result.passed for result in results))


if __name__ == "__main__":
    unittest.main()
