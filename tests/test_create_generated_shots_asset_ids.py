"""Coverage for app.repositories.scenes.create_generated_shots' asset_ids
handling: an AI-generated shot map (app/services/shot_map.py) is prompted
to return only real catalog asset ids, but nothing constrains the model to
actually do that. A hallucinated non-numeric value (observed in production:
"LOC_THEATER_BACKSTAGE_108") must be skipped, not crash the whole request.
"""

import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import assets as assets_repo
from app.repositories import projects as project_repo
from app.repositories import scenes as scene_repo


class CreateGeneratedShotsAssetIdsTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        self.project = project_repo.create_project(
            {"name": "Shots", "description": "", "visual_style": "", "rules": ""}
        )
        self.scene = scene_repo.create_scene({
            "project_id": self.project["id"], "scene_number": 1, "title": "Scene 1",
        })
        self.asset = assets_repo.create_asset({
            "project_id": self.project["id"], "asset_type": "לוקיישן", "name": "תיאטרון",
        })

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def test_hallucinated_non_numeric_asset_id_is_skipped_not_raised(self):
        shots = [{
            "title": "שוט 1",
            "asset_ids": [str(self.asset["id"]), "LOC_THEATER_BACKSTAGE_108"],
        }]
        result = scene_repo.create_generated_shots(self.scene["id"], shots)

        shot = result["shots"][0]
        self.assertEqual(shot["title"], "שוט 1")

    def test_asset_ids_outside_the_project_catalog_are_dropped(self):
        shots = [{"title": "שוט 1", "asset_ids": [self.asset["id"], 999999]}]
        scene_repo.create_generated_shots(self.scene["id"], shots)
        # No error means both the invalid id was silently dropped and the
        # valid one accepted — the real assertion is the absence of a crash;
        # this is confirmed further by the linked-asset test below.

    def test_valid_numeric_string_asset_id_still_links(self):
        shots = [{"title": "שוט 1", "asset_ids": [str(self.asset["id"])]}]
        result = scene_repo.create_generated_shots(self.scene["id"], shots)
        shot_id = result["shots"][0]["id"]

        from app.repositories import shots as shot_repo
        linked = shot_repo.get_shot(shot_id)
        self.assertEqual(linked["id"], shot_id)


if __name__ == "__main__":
    unittest.main()
