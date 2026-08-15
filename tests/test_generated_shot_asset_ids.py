"""Coverage for app.repositories.scenes.create_generated_shots's handling of
asset_ids from an AI-generated shot map (app/services/shot_map.py).

The shot map's asset_ids come straight from an LLM's JSON response, which
this app trusts is limited to the real numeric catalog ids it was given —
but nothing stops the model from hallucinating a descriptive reference
like "LOCATION_BACKSTAGE_001" instead. Found via a real production
production crash: opening the shot-map generation surfaced a raw
`invalid literal for int() with base 10: 'LOCATION_BACKSTAGE_001'` to the
user because the unguarded int(v) call had no fallback.
"""

import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import assets, projects, scenes


class GeneratedShotAssetIdsTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        project = projects.create_project({
            "name": "Shot Map", "description": "", "visual_style": "", "rules": "",
        })
        self.project_id = project["id"]
        scene = scenes.create_scene({
            "project_id": self.project_id,
            "scene_number": 1,
            "title": "Scene",
            "status": "מתוכנן",
            "story_goal": "", "emotion": "", "conflict": "",
            "beginning": "", "ending": "", "notes": "",
        })
        self.scene_id = scene["id"]
        self.asset = assets.create_asset({
            "project_id": self.project_id,
            "asset_type": "לוקיישן",
            "name": "Backstage",
            "approved": True,
        })

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def test_hallucinated_non_numeric_asset_id_is_dropped_not_crashed(self):
        generated = [{
            "title": "Shot 1",
            "asset_ids": ["LOCATION_BACKSTAGE_001", self.asset["id"]],
        }]
        result = scenes.create_generated_shots(self.scene_id, generated)
        shot = result["shots"][0]
        self.assertEqual(shot["asset_count"], 1)

    def test_only_non_numeric_asset_ids_still_creates_the_shot(self):
        generated = [{"title": "Shot 1", "asset_ids": ["LOCATION_BACKSTAGE_001"]}]
        result = scenes.create_generated_shots(self.scene_id, generated)
        self.assertEqual(len(result["shots"]), 1)
        self.assertEqual(result["shots"][0]["asset_count"], 0)

    def test_asset_id_from_another_project_is_still_rejected(self):
        # Unchanged existing behavior: a numeric id that just isn't in this
        # project's catalog must keep being silently dropped, not linked.
        other_project = projects.create_project({
            "name": "Other", "description": "", "visual_style": "", "rules": "",
        })
        other_asset = assets.create_asset({
            "project_id": other_project["id"],
            "asset_type": "לוקיישן",
            "name": "Elsewhere",
            "approved": True,
        })
        generated = [{"title": "Shot 1", "asset_ids": [other_asset["id"]]}]
        result = scenes.create_generated_shots(self.scene_id, generated)
        self.assertEqual(result["shots"][0]["asset_count"], 0)

    def test_valid_numeric_asset_id_still_links_normally(self):
        generated = [{"title": "Shot 1", "asset_ids": [self.asset["id"]]}]
        result = scenes.create_generated_shots(self.scene_id, generated)
        self.assertEqual(result["shots"][0]["asset_count"], 1)


if __name__ == "__main__":
    unittest.main()
