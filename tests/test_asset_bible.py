import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import settings
from app.services.asset_bible import generate_asset_bible
from app.services.generation import GenerationNotConfigured


def _fake_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(output_text=text)


_VALID_PAYLOAD = (
    '{"description": "a", "visual_rules": "b", '
    '"master_prompt": "c", "negative_prompt": "d"}'
)


class AssetBibleServiceTests(unittest.TestCase):
    def setUp(self):
        self.original_key = settings.openai_api_key
        settings.openai_api_key = "test-key"

    def tearDown(self):
        settings.openai_api_key = self.original_key

    def test_raises_generation_not_configured_when_no_api_key(self):
        settings.openai_api_key = ""
        with self.assertRaises(GenerationNotConfigured):
            generate_asset_bible({"asset_type": "דמות", "name": "x"}, {"name": "p"})

    def test_parses_valid_json_response_into_bible_fields(self):
        with patch("app.services.asset_bible._openai_client") as client:
            client.return_value.responses.create.return_value = _fake_response(_VALID_PAYLOAD)
            result = generate_asset_bible(
                {"asset_type": "דמות", "name": "תמר"}, {"name": "Project"},
            )
        self.assertEqual(
            result,
            {"description": "a", "visual_rules": "b", "master_prompt": "c", "negative_prompt": "d"},
        )

    def test_works_for_location_asset_type(self):
        with patch("app.services.asset_bible._openai_client") as client:
            client.return_value.responses.create.return_value = _fake_response(_VALID_PAYLOAD)
            result = generate_asset_bible(
                {"asset_type": "לוקיישן", "name": "תיאטרון"}, {"name": "Project"},
            )
        self.assertEqual(result["description"], "a")

    def test_strips_markdown_code_fence_before_parsing(self):
        payload = f"```json\n{_VALID_PAYLOAD}\n```"
        with patch("app.services.asset_bible._openai_client") as client:
            client.return_value.responses.create.return_value = _fake_response(payload)
            result = generate_asset_bible({"asset_type": "דמות", "name": "x"}, {"name": "p"})
        self.assertEqual(result["description"], "a")

    def test_raises_when_response_is_missing_a_required_field(self):
        payload = '{"description": "a", "visual_rules": "b", "master_prompt": "c"}'
        with patch("app.services.asset_bible._openai_client") as client:
            client.return_value.responses.create.return_value = _fake_response(payload)
            with self.assertRaises(RuntimeError):
                generate_asset_bible({"asset_type": "דמות", "name": "x"}, {"name": "p"})

    def test_raises_when_response_is_not_a_json_object(self):
        payload = '["a", "b"]'
        with patch("app.services.asset_bible._openai_client") as client:
            client.return_value.responses.create.return_value = _fake_response(payload)
            with self.assertRaises(RuntimeError):
                generate_asset_bible({"asset_type": "דמות", "name": "x"}, {"name": "p"})


class AssetBibleApiTests(unittest.TestCase):
    @patch("app.api.assets.generate_asset_bible")
    @patch("app.api.assets.project_repo.get_project")
    @patch("app.api.assets.repo.update_asset")
    @patch("app.api.assets.repo.get_asset")
    def test_generate_bible_saves_and_returns_updated_asset(
        self, get_asset, update_asset, get_project, generate_bible_fn
    ):
        from app.api.assets import generate_bible

        get_asset.return_value = {"id": 5, "project_id": 1, "asset_type": "דמות", "name": "תמר"}
        get_project.return_value = {"id": 1, "name": "P"}
        fields = {
            "description": "a", "visual_rules": "b",
            "master_prompt": "c", "negative_prompt": "d",
        }
        generate_bible_fn.return_value = fields
        update_asset.return_value = {"id": 5, **fields}

        result = generate_bible(5)

        update_asset.assert_called_once_with(5, fields)
        self.assertEqual(result["description"], "a")

    @patch("app.api.assets.repo.get_asset")
    def test_generate_bible_404s_when_asset_missing(self, get_asset):
        from fastapi import HTTPException

        from app.api.assets import generate_bible

        get_asset.return_value = None
        with self.assertRaises(HTTPException) as ctx:
            generate_bible(999)
        self.assertEqual(ctx.exception.status_code, 404)

    @patch("app.api.assets.repo.get_asset")
    def test_generate_bible_409s_for_unsupported_asset_type(self, get_asset):
        from fastapi import HTTPException

        from app.api.assets import generate_bible

        get_asset.return_value = {"id": 5, "project_id": 1, "asset_type": "אביזר", "name": "x"}
        with self.assertRaises(HTTPException) as ctx:
            generate_bible(5)
        self.assertEqual(ctx.exception.status_code, 409)

    @patch("app.api.assets.generate_asset_bible")
    @patch("app.api.assets.project_repo.get_project")
    @patch("app.api.assets.repo.get_asset")
    def test_generate_bible_503s_when_generation_not_configured(
        self, get_asset, get_project, generate_bible_fn
    ):
        from fastapi import HTTPException

        from app.api.assets import generate_bible

        get_asset.return_value = {"id": 5, "project_id": 1, "asset_type": "לוקיישן", "name": "x"}
        get_project.return_value = {"id": 1}
        generate_bible_fn.side_effect = GenerationNotConfigured("OPENAI_API_KEY אינו מוגדר.")
        with self.assertRaises(HTTPException) as ctx:
            generate_bible(5)
        self.assertEqual(ctx.exception.status_code, 503)

    @patch("app.api.assets.generate_asset_bible")
    @patch("app.api.assets.project_repo.get_project")
    @patch("app.api.assets.repo.get_asset")
    def test_generate_bible_409s_when_asset_is_locked(
        self, get_asset, get_project, generate_bible_fn
    ):
        from fastapi import HTTPException

        from app.api.assets import generate_bible

        get_asset.return_value = {"id": 5, "project_id": 1, "asset_type": "דמות", "name": "x"}
        get_project.return_value = {"id": 1}
        generate_bible_fn.return_value = {
            "description": "a", "visual_rules": "b",
            "master_prompt": "c", "negative_prompt": "d",
        }
        with patch("app.api.assets.repo.update_asset") as update_asset:
            update_asset.side_effect = ValueError("לא ניתן לשנות שדות Master של נכס נעול.")
            with self.assertRaises(HTTPException) as ctx:
                generate_bible(5)
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
