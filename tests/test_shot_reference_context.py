import copy
import unittest
from unittest.mock import MagicMock, patch

from app.services.generation import submit_magnific_image
from app.services.shot_reference_context import build_shot_reference_context


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"data": {"task_id": "task-1", "status": "IN_PROGRESS"}}


class _Client:
    last_payload = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, *, headers, json):
        _Client.last_payload = json
        return _Response()


class ShotReferenceContextTests(unittest.TestCase):
    def test_loads_only_linked_scene_variants_without_mutating_shot(self):
        shot = {
            "id": 31,
            "scene_id": 12,
            "assets": [
                {
                    "id": 21,
                    "asset_type": "לוקיישן",
                    "reference_images": ["https://cdn.example/master-room.png"],
                },
                {
                    "id": 22,
                    "asset_type": "דמות",
                    "reference_images": ["https://cdn.example/locked-character.png"],
                },
            ],
        }
        original = copy.deepcopy(shot)
        rows = [{
            "scene_id": 12,
            "asset_id": 21,
            "state_name": "לילה",
            "description": "",
            "reference_url": "https://cdn.example/night-room.png",
            "visual_rules": "",
            "updated_at": "now",
        }]
        cursor = MagicMock()
        cursor.fetchall.return_value = rows

        with patch("app.services.shot_reference_context.get_connection", return_value=MagicMock()), patch(
            "app.services.shot_reference_context.execute_query", return_value=cursor
        ) as execute:
            result = build_shot_reference_context(shot)

        self.assertEqual(shot, original)
        self.assertEqual(
            result["assets"][0]["generation_reference_images"],
            [
                "https://cdn.example/night-room.png",
                "https://cdn.example/master-room.png",
            ],
        )
        self.assertEqual(
            result["assets"][1]["generation_reference_images"],
            ["https://cdn.example/locked-character.png"],
        )
        self.assertEqual(execute.call_args.args[2], (12, 21, 22))

    def test_generation_submits_scene_variant_before_master_fallback(self):
        shot = {
            "id": 31,
            "scene_id": 12,
            "prompt": "A locked production shot",
            "assets": [{
                "id": 21,
                "asset_type": "לוקיישן",
                "reference_images": ["https://cdn.example/master-room.png"],
            }],
        }
        context = {
            **shot,
            "assets": [{
                **shot["assets"][0],
                "generation_reference_images": [
                    "https://cdn.example/night-room.png",
                    "https://cdn.example/master-room.png",
                ],
            }],
        }

        with patch(
            "app.services.generation.build_shot_reference_context", return_value=context
        ), patch("app.services.generation.httpx.Client", _Client), patch(
            "app.services.generation._magnific_headers", return_value={}
        ):
            result = submit_magnific_image(shot)

        self.assertEqual(result["task_id"], "task-1")
        self.assertEqual(
            _Client.last_payload["reference_images"],
            ["https://cdn.example/night-room.png"],
        )

    def test_context_skips_database_when_no_scene_or_assets(self):
        with patch("app.services.shot_reference_context.get_connection") as connect:
            result = build_shot_reference_context({"scene_id": None, "assets": []})
        connect.assert_not_called()
        self.assertEqual(result["assets"], [])


if __name__ == "__main__":
    unittest.main()
