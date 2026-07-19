import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import settings
from app.services.screenplay_breakdown import (
    _extract_json_array,
    _split_screenplay,
    breakdown_screenplay,
)


class ScreenplayBreakdownChunkingTests(unittest.TestCase):
    def setUp(self):
        self.original_key = settings.openai_api_key
        settings.openai_api_key = "test-key"

    def tearDown(self):
        settings.openai_api_key = self.original_key

    def test_long_screenplay_is_split_without_losing_text(self):
        screenplay = "\n\n".join(["סצנה " + ("א" * 2500) for _ in range(8)])
        chunks = _split_screenplay(screenplay, max_characters=5000)

        self.assertGreater(len(chunks), 1)
        rebuilt = "\n\n".join(chunks)
        self.assertEqual(rebuilt, screenplay)
        self.assertTrue(all(len(chunk) <= 5000 for chunk in chunks))

    def test_json_array_can_be_extracted_from_fenced_response(self):
        result = _extract_json_array('```json\n[{"title":"א"}]\n```')
        self.assertEqual(result[0]["title"], "א")

    @patch("app.services.screenplay_breakdown._openai_client")
    @patch("app.services.screenplay_breakdown._split_screenplay")
    def test_each_chunk_is_processed_and_scenes_are_renumbered(self, split, client_factory):
        split.return_value = ["חלק ראשון", "חלק שני"]
        responses = [
            SimpleNamespace(output_text=json.dumps([{
                "scene_number": 8,
                "title": "ראשונה",
                "recommended_shot_count": 4,
                "estimated_duration_seconds": 45,
            }], ensure_ascii=False)),
            SimpleNamespace(output_text=json.dumps([{
                "scene_number": 99,
                "title": "שנייה",
                "recommended_shot_count": 7,
                "estimated_duration_seconds": 70,
            }], ensure_ascii=False)),
        ]
        client = SimpleNamespace(
            responses=SimpleNamespace(create=lambda **kwargs: responses.pop(0))
        )
        client_factory.return_value = client

        scenes = breakdown_screenplay({"name": "בדיקה"}, "תסריט מספיק ארוך " * 10)

        self.assertEqual([scene["scene_number"] for scene in scenes], [1, 2])
        self.assertEqual([scene["title"] for scene in scenes], ["ראשונה", "שנייה"])
        self.assertEqual(scenes[1]["recommended_shot_count"], 7)
        self.assertEqual(responses, [])

    @patch("app.services.screenplay_breakdown._openai_client")
    @patch("app.services.screenplay_breakdown._split_screenplay")
    def test_chunk_failure_reports_chunk_number(self, split, client_factory):
        split.return_value = ["חלק ראשון", "חלק שני"]
        responses = [
            SimpleNamespace(output_text='[{"title":"ראשונה"}]'),
            SimpleNamespace(output_text="not-json"),
        ]
        client = SimpleNamespace(
            responses=SimpleNamespace(create=lambda **kwargs: responses.pop(0))
        )
        client_factory.return_value = client

        with self.assertRaisesRegex(RuntimeError, "מקטע 2 מתוך 2"):
            breakdown_screenplay({"name": "בדיקה"}, "תסריט מספיק ארוך " * 10)


if __name__ == "__main__":
    unittest.main()
