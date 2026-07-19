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

    def test_import_breakdown_does_not_generate_all_shot_maps_in_one_request(self):
        self.assertIn("generate_shot_maps:false", self.template)
        self.assertIn("/shot-map", self.template)
        self.assertIn("for(let index=0;index<scenes.length;index++)", self.template)

    def test_non_json_server_response_is_handled_without_raw_json_parse_error(self):
        self.assertIn("const text=await response.text()", self.template)
        self.assertIn("JSON.parse(text)", self.template)
        self.assertIn("השרת הפסיק את הפעולה לפני שהסתיימה", self.template)

    def test_user_visible_error_is_html_escaped(self):
        self.assertIn("escapeHtml(error.message)", self.template)


if __name__ == "__main__":
    unittest.main()
