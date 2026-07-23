import os
import unittest
from unittest.mock import Mock

from app.database.startup import build_database_startup_adapter
from app.database.validate_postgres_schema import validate_postgres_startup_connection


@unittest.skipUnless(os.environ.get("CI") == "true", "requires the isolated CI PostgreSQL service")
class PostgreSQLStartupLiveTests(unittest.TestCase):
    def test_gated_startup_uses_real_read_only_schema_validation(self):
        import psycopg

        database_url = (
            "postgresql://film_os_ci:film_os_ci_password@localhost:5432/"
            "film_os_validation"
        )
        migrate = Mock()
        seed = Mock()

        with psycopg.connect(database_url) as connection:
            startup = build_database_startup_adapter(
                "postgresql",
                schema_sql="unused",
                migrate=migrate,
                seed=seed,
                enable_postgresql=True,
                validate_postgresql=validate_postgres_startup_connection,
            )
            startup.initialize(connection)

            self.assertFalse(connection.closed)
            migrate.assert_not_called()
            seed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
