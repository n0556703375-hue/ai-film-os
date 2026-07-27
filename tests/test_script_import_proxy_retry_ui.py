from pathlib import Path
import unittest


TEMPLATE = Path("app/templates/script_import.html")


class ScriptImportProxyRetryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_import_parse_failures_are_retryable(self):
        self.assertIn("IMPORT_PARSE_RETRY_CODES", self.html)
        self.assertIn("'empty_response'", self.html)
        self.assertIn("'non_json_response'", self.html)
        self.assertIn("'malformed_json'", self.html)
        self.assertIn("retryable:true", self.html)

    def test_retry_override_is_scoped_to_screenplay_import_post(self):
        self.assertIn("startsWith('/api/scenes/import-script')", self.html)
        self.assertIn("toUpperCase()==='POST'", self.html)

    def test_original_error_metadata_is_preserved(self):
        self.assertIn("status:error.status", self.html)
        self.assertIn("code:error.code", self.html)
        self.assertIn("progress:error.progress", self.html)

    def test_stage_retry_still_requires_no_persisted_scenes(self):
        self.assertIn("progress.scenesCreated===0", self.html)


if __name__ == "__main__":
    unittest.main()
