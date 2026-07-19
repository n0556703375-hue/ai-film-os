import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.api.health import health, readiness
from app.core.config import settings
from app.database.connection import init_db


class HealthReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database_path = settings.database_path
        settings.database_path = Path(self.temp_dir.name) / "health.db"

    def tearDown(self):
        settings.database_path = self.original_database_path
        self.temp_dir.cleanup()

    def test_liveness_does_not_expose_provider_configuration(self):
        result = health()

        self.assertEqual("ok", result["status"])
        self.assertNotIn("api_key_configured", result)
        self.assertNotIn("database_path", result)

    def test_readiness_passes_after_database_initialization(self):
        init_db()

        result = readiness()

        self.assertEqual("ready", result["status"])
        self.assertEqual("ok", result["database"])

    def test_readiness_fails_when_schema_is_missing(self):
        with self.assertRaises(HTTPException) as context:
            readiness()

        self.assertEqual(503, context.exception.status_code)
        self.assertIn("schema is incomplete", context.exception.detail)

    def test_readiness_masks_database_error_details(self):
        with patch("app.api.health.get_connection", side_effect=RuntimeError("secret path")):
            with self.assertRaises(HTTPException) as context:
                readiness()

        self.assertEqual(503, context.exception.status_code)
        self.assertEqual("Database readiness check failed.", context.exception.detail)
        self.assertNotIn("secret path", context.exception.detail)


if __name__ == "__main__":
    unittest.main()
