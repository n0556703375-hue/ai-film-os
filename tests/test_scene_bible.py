import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import settings
from app.services.generation import GenerationNotConfigured
from app.services.scene_bible import generate_scene_bible


def _fake_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(output_text=text)


class SceneBibleServiceTests(unittest.TestCase):
    def setUp(self):
        self.original_key = settings.openai_api_key
        settings.openai_api_key = "test-key"

    def tearDown(self):
        settings.openai_api_key = self.original_key

    def test_raises_generation_not_configured_when_no_api_key(self):
        settings.openai_api_key = ""
        with self.assertRaises(GenerationNotConfigured):
            generate_scene_bible({"raw_scene_text": "x"}, {"name": "p"})

    def test_parses_valid_json_response_into_bible_fields(self):
        payload = (
            '{"story_goal": "a", "emotion": "b", "conflict": "c", '
            '"beginning": "d", "ending": "e", "recommended_shot_count": 8}'
        )
        with patch("app.services.scene_bible._openai_client") as client:
            client.return_value.responses.create.return_value = _fake_response(payload)
            result = generate_scene_bible(
                {"scene_number": 1, "raw_scene_text": "some scene text"},
                {"name": "Project"},
            )
        self.assertEqual(
            result,
            {
                "story_goal": "a", "emotion": "b", "conflict": "c",
                "beginning": "d", "ending": "e", "recommended_shot_count": 8,
            },
        )

    def test_strips_markdown_code_fence_before_parsing(self):
        payload = (
            "```json\n"
            '{"story_goal": "a", "emotion": "b", "conflict": "c", '
            '"beginning": "d", "ending": "e", "recommended_shot_count": 5}\n'
            "```"
        )
        with patch("app.services.scene_bible._openai_client") as client:
            client.return_value.responses.create.return_value = _fake_response(payload)
            result = generate_scene_bible({"raw_scene_text": "x"}, {"name": "p"})
        self.assertEqual(result["story_goal"], "a")

    def test_raises_when_response_is_missing_a_required_field(self):
        payload = '{"story_goal": "a", "emotion": "b", "conflict": "c", "beginning": "d"}'
        with patch("app.services.scene_bible._openai_client") as client:
            client.return_value.responses.create.return_value = _fake_response(payload)
            with self.assertRaises(RuntimeError):
                generate_scene_bible({"raw_scene_text": "x"}, {"name": "p"})

    def test_raises_when_response_is_not_a_json_object(self):
        payload = '["a", "b"]'
        with patch("app.services.scene_bible._openai_client") as client:
            client.return_value.responses.create.return_value = _fake_response(payload)
            with self.assertRaises(RuntimeError):
                generate_scene_bible({"raw_scene_text": "x"}, {"name": "p"})

    def test_shot_count_is_clamped_to_the_valid_range(self):
        payload = (
            '{"story_goal": "a", "emotion": "b", "conflict": "c", '
            '"beginning": "d", "ending": "e", "recommended_shot_count": 999}'
        )
        with patch("app.services.scene_bible._openai_client") as client:
            client.return_value.responses.create.return_value = _fake_response(payload)
            result = generate_scene_bible({"raw_scene_text": "x"}, {"name": "p"})
        self.assertEqual(result["recommended_shot_count"], 20)

    def test_missing_or_invalid_shot_count_falls_back_to_default(self):
        payload = (
            '{"story_goal": "a", "emotion": "b", "conflict": "c", '
            '"beginning": "d", "ending": "e", "recommended_shot_count": "lots"}'
        )
        with patch("app.services.scene_bible._openai_client") as client:
            client.return_value.responses.create.return_value = _fake_response(payload)
            result = generate_scene_bible({"raw_scene_text": "x"}, {"name": "p"})
        self.assertEqual(result["recommended_shot_count"], 6)


class SceneBibleApiTests(unittest.TestCase):
    @patch("app.api.scenes.generate_scene_bible")
    @patch("app.api.scenes.project_repo.get_project")
    @patch("app.api.scenes.repo.update_scene")
    @patch("app.api.scenes.repo.get_scene")
    def test_generate_bible_saves_and_returns_updated_scene(
        self, get_scene, update_scene, get_project, generate_bible_fn
    ):
        from app.api.scenes import generate_bible

        get_scene.return_value = {
            "id": 5,
            "project_id": 1,
            "raw_scene_text": "INT. ROOM - DAY\nSomething happens.",
        }
        get_project.return_value = {"id": 1, "name": "P"}
        fields = {
            "story_goal": "a", "emotion": "b", "conflict": "c",
            "beginning": "d", "ending": "e", "recommended_shot_count": 7,
        }
        generate_bible_fn.return_value = fields
        update_scene.return_value = {"id": 5, **fields}

        result = generate_bible(5)

        update_scene.assert_called_once_with(5, fields)
        self.assertEqual(result["story_goal"], "a")

    @patch("app.api.scenes.repo.get_scene")
    def test_generate_bible_404s_when_scene_missing(self, get_scene):
        from fastapi import HTTPException

        from app.api.scenes import generate_bible

        get_scene.return_value = None
        with self.assertRaises(HTTPException) as ctx:
            generate_bible(999)
        self.assertEqual(ctx.exception.status_code, 404)

    @patch("app.api.scenes.repo.get_scene")
    def test_generate_bible_409s_when_no_raw_scene_text(self, get_scene):
        from fastapi import HTTPException

        from app.api.scenes import generate_bible

        get_scene.return_value = {"id": 5, "project_id": 1, "raw_scene_text": "   "}
        with self.assertRaises(HTTPException) as ctx:
            generate_bible(5)
        self.assertEqual(ctx.exception.status_code, 409)

    @patch("app.api.scenes.generate_scene_bible")
    @patch("app.api.scenes.project_repo.get_project")
    @patch("app.api.scenes.repo.get_scene")
    def test_generate_bible_503s_when_generation_not_configured(
        self, get_scene, get_project, generate_bible_fn
    ):
        from fastapi import HTTPException

        from app.api.scenes import generate_bible

        get_scene.return_value = {"id": 5, "project_id": 1, "raw_scene_text": "text"}
        get_project.return_value = {"id": 1}
        generate_bible_fn.side_effect = GenerationNotConfigured("OPENAI_API_KEY אינו מוגדר.")
        with self.assertRaises(HTTPException) as ctx:
            generate_bible(5)
        self.assertEqual(ctx.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
