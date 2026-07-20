import unittest
from unittest.mock import patch

from app.services.prompt_builder import build_prompt


class ProductionBiblePromptTests(unittest.TestCase):
    def setUp(self):
        self.shot = {
            "id": 7,
            "project_id": 3,
            "scene_id": 4,
            "title": "מסדרון ראשי",
            "assets": [],
        }

    @patch("app.services.prompt_builder.apply_scene_asset_variants", side_effect=lambda shot: shot)
    @patch("app.services.prompt_builder.projects.get_project")
    def test_includes_project_visual_style_and_global_rules(self, get_project, _apply_variants):
        get_project.return_value = {
            "id": 3,
            "visual_style": "עתיד ריאליסטי קר ומאופק",
            "rules": "נשים בלבד על המסך; ללא גברים גם ברקע; לבוש צנוע ללא מכנסיים",
        }

        prompt = build_prompt(self.shot)

        self.assertIn("PRODUCTION BIBLE — MANDATORY FOR THIS SHOT", prompt)
        self.assertIn("עתיד ריאליסטי קר ומאופק", prompt)
        self.assertIn("נשים בלבד על המסך", prompt)
        self.assertIn("ללא גברים גם ברקע", prompt)
        self.assertIn("לבוש צנוע ללא מכנסיים", prompt)
        get_project.assert_called_once_with(3)

    @patch("app.services.prompt_builder.apply_scene_asset_variants", side_effect=lambda shot: shot)
    @patch("app.services.prompt_builder.projects.get_project", return_value=None)
    def test_missing_project_uses_safe_explicit_defaults(self, _get_project, _apply_variants):
        prompt = build_prompt(self.shot)

        self.assertIn("Use the established project visual language consistently.", prompt)
        self.assertIn("No additional project-wide restrictions were specified.", prompt)

    @patch("app.services.prompt_builder.apply_scene_asset_variants", side_effect=lambda shot: shot)
    @patch("app.services.prompt_builder.projects.get_project")
    def test_project_rules_precede_shot_instructions(self, get_project, _apply_variants):
        get_project.return_value = {"visual_style": "clean", "rules": "women only"}

        prompt = build_prompt(self.shot)

        self.assertLess(prompt.index("PRODUCTION BIBLE"), prompt.index("SHOT\n"))
        self.assertLess(prompt.index("women only"), prompt.index("ACTION\n"))

    @patch("app.services.prompt_builder.apply_scene_asset_variants", side_effect=lambda shot: shot)
    @patch("app.services.prompt_builder.projects.get_project")
    def test_scene_variant_propagation_remains_in_pipeline(self, get_project, apply_variants):
        get_project.return_value = {"visual_style": "", "rules": ""}
        apply_variants.return_value = {**self.shot, "title": "וריאנט סצנה", "assets": []}

        prompt = build_prompt(self.shot)

        self.assertIn("Title: וריאנט סצנה", prompt)
        apply_variants.assert_called_once_with(self.shot)


if __name__ == "__main__":
    unittest.main()
