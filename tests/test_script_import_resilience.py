import unittest
from pathlib import Path


class ScriptImportResilienceTests(unittest.TestCase):
    def setUp(self):
        self.template = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "templates"
            / "script_import.html"
        ).read_text(encoding="utf-8")

    def test_breakdown_is_bounded_and_resumable(self):
        self.assertIn("while(!state.completed)", self.template)
        self.assertIn("retryState={type:'breakdown',state}", self.template)
        self.assertIn("'/api/import-runs/process-next'", self.template)
        self.assertIn("next_chunk_index:state.nextChunkIndex", self.template)

    def test_import_responses_use_the_shared_safe_parser(self):
        self.assertIn('<script src="/static/safe_api.js"></script>', self.template)
        self.assertIn("return parseApiResponse(response)", self.template)
        self.assertIn("code:'network_error',retryable:true", self.template)

    def test_user_visible_error_is_html_escaped_and_non_destructive(self):
        self.assertIn("escapeHtml(error.message||'אירעה תקלה זמנית.')", self.template)
        self.assertIn("לא בוצעה החלפה של נתונים קיימים", self.template)
        self.assertIn("replace_existing:false", self.template)


if __name__ == "__main__":
    unittest.main()
