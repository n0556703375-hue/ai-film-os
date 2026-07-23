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
        self.assertIn("error&&error.retryable", self.html)


if __name__ == "__main__":
    unittest.main()
