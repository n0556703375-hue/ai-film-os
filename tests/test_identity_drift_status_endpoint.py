"""Coverage for GET /api/shots/identity-drift/status — lets the UI tell
"still queued, will run shortly" apart from "queued forever because
OPENAI_API_KEY was never set"."""

import unittest

from app.api.identity_assessments import identity_drift_status
from app.core.config import settings


class IdentityDriftStatusEndpointTests(unittest.TestCase):
    def setUp(self):
        self.original_key = settings.openai_api_key

    def tearDown(self):
        settings.openai_api_key = self.original_key

    def test_reports_unconfigured_when_no_api_key(self):
        settings.openai_api_key = ""
        self.assertEqual(identity_drift_status(), {"configured": False})

    def test_reports_configured_when_api_key_present(self):
        settings.openai_api_key = "sk-test"
        self.assertEqual(identity_drift_status(), {"configured": True})


if __name__ == "__main__":
    unittest.main()
