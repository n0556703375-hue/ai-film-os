import unittest

from app.api.health import health
from app.core.version import APP_VERSION
from app.main import app


class DeploymentSmokeTests(unittest.TestCase):
    def test_application_and_health_report_same_version(self):
        payload = health()

        self.assertEqual(app.version, APP_VERSION)
        self.assertEqual(payload["version"], APP_VERSION)
        self.assertEqual(payload["status"], "ok")

    def test_required_deployment_routes_are_registered(self):
        paths = {route.path for route in app.routes}

        self.assertIn("/health", paths)
        self.assertIn("/", paths)
        self.assertIn("/api/jobs", paths)


if __name__ == "__main__":
    unittest.main()
