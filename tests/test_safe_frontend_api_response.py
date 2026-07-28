import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SafeFrontendApiResponseTests(unittest.TestCase):
    def test_wrapper_loads_before_main_app(self):
        html = (ROOT / "app/templates/index.html").read_text(encoding="utf-8")
        safe_index = html.index('/static/safe-api-response.js')
        app_index = html.index('/static/app.js')
        self.assertLess(safe_index, app_index)

    def test_wrapper_handles_empty_and_malformed_responses_without_raw_body(self):
        source = (ROOT / "app/static/safe-api-response.js").read_text(encoding="utf-8")
        self.assertIn('"empty_response"', source)
        self.assertIn('"invalid_response"', source)
        self.assertIn('target.clone().text()', source)
        self.assertNotIn('text.slice(', source)
        self.assertNotIn('innerHTML = text', source)

    def test_structured_fastapi_detail_is_reduced_to_safe_message(self):
        source = (ROOT / "app/static/safe-api-response.js").read_text(encoding="utf-8")
        self.assertIn('typeof payload.detail === "object"', source)
        self.assertIn('detail.message ||', source)
        self.assertIn('retryable: status === 502 || status === 503 || status === 504', source)


if __name__ == "__main__":
    unittest.main()
