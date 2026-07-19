import unittest
from unittest.mock import patch

from app.services.prompt_builder import build_prompt
from app.services.scene_reference_propagation import apply_scene_asset_variants


class SceneReferencePropagationTests(unittest.TestCase):
    def setUp(self):
        self.shot = {
            "id": 10,
            "scene_id": 4,
            "title": "כניסה לחדר",
            "assets": [
                {
                    "id": 21,
                    "asset_type": "לוקיישן",
                    "name": "חדר בקרה",
                    "description": "חדר נקי",
                    "visual_rules": "אור קר",
                    "reference_url": "https://example.com/master.jpg",
                },
                {
                    "id": 22,
                    "asset_type": "דמות",
                    "name": "ליאורה",
                    "description": "דמות ראשית",
                    "visual_rules": "זהות נעולה",
                    "reference_url": "https://example.com/liora.jpg",
                },
            ],
        }
        self.variant = {
            "id": 31,
            "scene_id": 4,
            "asset_id": 21,
            "state_name": "מצב לילה",
            "description": "אותו חדר לאחר כיבוי מערכות",
            "visual_rules": "תאורת חירום כחולה חלשה",
            "reference_url": "https://example.com/night.jpg",
        }

    @patch("app.services.scene_reference_propagation.list_scene_variants")
    def test_overlays_only_matching_linked_asset(self, list_variants):
        list_variants.return_value = [self.variant]
        result = apply_scene_asset_variants(self.shot)

        location, character = result["assets"]
        self.assertEqual(location["name"], "חדר בקרה — מצב לילה")
        self.assertEqual(location["description"], self.variant["description"])
        self.assertEqual(location["visual_rules"], self.variant["visual_rules"])
        self.assertEqual(location["reference_url"], self.variant["reference_url"])
        self.assertEqual(location["source_asset_id"], 21)
        self.assertEqual(character, self.shot["assets"][1])
        self.assertEqual(self.shot["assets"][0]["name"], "חדר בקרה")

    @patch("app.services.scene_reference_propagation.list_scene_variants")
    def test_prompt_uses_scene_variant_automatically(self, list_variants):
        list_variants.return_value = [self.variant]
        prompt = build_prompt(self.shot)

        self.assertIn("חדר בקרה — מצב לילה", prompt)
        self.assertIn("אותו חדר לאחר כיבוי מערכות", prompt)
        self.assertIn("תאורת חירום כחולה חלשה", prompt)
        self.assertNotIn("חדר נקי Rules: אור קר", prompt)

    @patch("app.services.scene_reference_propagation.list_scene_variants")
    def test_no_variant_preserves_existing_assets(self, list_variants):
        list_variants.return_value = []
        result = apply_scene_asset_variants(self.shot)
        self.assertIs(result, self.shot)

    @patch("app.services.scene_reference_propagation.list_scene_variants")
    def test_shot_without_scene_does_not_query_variants(self, list_variants):
        shot = {**self.shot, "scene_id": None}
        result = apply_scene_asset_variants(shot)
        self.assertIs(result, shot)
        list_variants.assert_not_called()


if __name__ == "__main__":
    unittest.main()
