import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "script_import.html"


class ScriptImportSafeParserWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_safe_parser_loads_before_inline_import_script(self):
        safe_parser = '<script src="/static/safe_api.js"></script>'
        self.assertIn(safe_parser, self.html)
        self.assertLess(self.html.index(safe_parser), self.html.index("async function json"))

    def test_import_requests_use_shared_safe_parser(self):
        self.assertIn("return parseApiResponse(response);", self.html)
        self.assertNotIn("JSON.parse(text)", self.html)
        self.assertNotIn("preview=cleaned", self.html)

    def test_network_failures_have_stable_retryable_error(self):
        self.assertIn("new FilmOsApiError", self.html)
        self.assertIn("code:'network_error'", self.html)
        self.assertIn("retryable:true", self.html)

    def test_retry_copy_is_only_shown_for_retryable_errors(self):
        self.assertIn("error&&error.retryable&&retryState", self.html)

    def test_server_progress_updates_current_persisted_counts(self):
        self.assertIn("progress.scenesCreated=Number(data.scenes_created||scenes.length||0)", self.html)
        self.assertIn("if(data.idempotent_replay)progress.scenesCreated=scenes.length", self.html)
        self.assertIn("progress.shotsCreated+=(created.shots||[]).length", self.html)
        self.assertIn("progress.shotsCreated+=(current.shots||[]).length", self.html)

    def test_failure_summary_uses_saved_retry_state_without_raw_backend_progress(self):
        self.assertIn("function failureSummary(error)", self.html)
        self.assertIn("error&&error.retryable&&retryState", self.html)
        self.assertIn("לא בוצעה החלפה של נתונים קיימים", self.html)
        self.assertNotIn("partialFailureSummary", self.html)
        self.assertNotIn("error.progress", self.html)


if __name__ == "__main__":
    unittest.main()
