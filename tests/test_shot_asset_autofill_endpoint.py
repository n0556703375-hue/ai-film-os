"""Coverage for POST /api/shots/{shot_id}/assets/autofill — wires
suggest_shot_asset_ids to real shot/asset data, additive-only."""

import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app.api.shots import autofill_assets
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import assets as assets_repo
from app.repositories import projects, scenes, shots


class AutofillAssetsEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        self.project = projects.create_project(
            {"name": "Autofill", "description": "", "visual_style": "", "rules": ""}
        )
        scene = scenes.create_scene({
            "project_id": self.project["id"], "scene_number": 1, "title": "S",
            "status": "מתוכנן", "story_goal": "", "emotion": "", "conflict": "",
            "beginning": "", "ending": "", "notes": "",
        })
        self.character = assets_repo.create_asset({
            "project_id": self.project["id"], "asset_type": "דמות", "name": "יעל",
        })
        self.prop = assets_repo.create_asset({
            "project_id": self.project["id"], "asset_type": "אביזר", "name": "סכין",
        })
        self.shot = shots.create_shot({
            "project_id": self.project["id"], "scene_id": scene["id"],
            "shot_number": 1, "title": "Shot", "action": "יעל מרימה את הסכין.",
        })

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def test_404_for_missing_shot(self):
        with self.assertRaises(HTTPException) as ctx:
            autofill_assets(999999)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_links_matched_assets_and_reports_added_ids(self):
        result = autofill_assets(self.shot["id"])
        linked_ids = {a["id"] for a in result["assets"]}
        self.assertEqual(linked_ids, {self.character["id"], self.prop["id"]})
        self.assertEqual(sorted(result["added_asset_ids"]), sorted([self.character["id"], self.prop["id"]]))

    def test_is_additive_and_does_not_remove_manual_links(self):
        unrelated = assets_repo.create_asset({
            "project_id": self.project["id"], "asset_type": "לוקיישן", "name": "מטבח",
        })
        shots.set_shot_assets(self.shot["id"], [unrelated["id"]])
        result = autofill_assets(self.shot["id"])
        linked_ids = {a["id"] for a in result["assets"]}
        self.assertIn(unrelated["id"], linked_ids)
        self.assertIn(self.character["id"], linked_ids)
        self.assertNotIn(unrelated["id"], result["added_asset_ids"])

    def test_no_matches_leaves_assets_unchanged(self):
        shots.set_shot_assets(self.shot["id"], [])
        second_shot = shots.create_shot({
            "project_id": self.project["id"], "scene_id": self.shot["scene_id"],
            "shot_number": 2, "title": "Empty", "action": "רחוב ריק.",
        })
        result = autofill_assets(second_shot["id"])
        self.assertEqual(result["assets"], [])
        self.assertEqual(result["added_asset_ids"], [])


if __name__ == "__main__":
    unittest.main()
