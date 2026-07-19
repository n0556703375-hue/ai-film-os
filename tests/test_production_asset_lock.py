import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app.api.generation import _validate_locked_assets
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import assets, projects


class ProductionAssetLockTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        self.project = projects.create_project({
            "name": "Test Film",
            "description": "",
            "visual_style": "",
            "rules": "",
        })

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _create_lockable_asset(self, asset_type: str, name: str):
        asset = assets.create_asset({
            "project_id": self.project["id"],
            "asset_type": asset_type,
            "name": name,
        })
        reference = assets.create_reference_image(asset["id"], {
            "view_type": "master",
            "url": f"https://example.com/{asset_type}.jpg",
        })
        return asset, reference

    def test_location_can_be_locked_with_approved_master(self):
        location, reference = self._create_lockable_asset("לוקיישן", "תחנת מרום")
        assets.set_reference_approval(location["id"], reference["id"], True)
        locked = assets.lock_asset(location["id"], reference["id"])
        self.assertEqual(locked["lock_status"], "locked")
        self.assertEqual(locked["master_reference_id"], reference["id"])

    def test_wardrobe_can_be_unlocked_for_revision(self):
        wardrobe, reference = self._create_lockable_asset("לבוש", "חליפת ליאורה")
        assets.set_reference_approval(wardrobe["id"], reference["id"], True)
        assets.lock_asset(wardrobe["id"], reference["id"])
        unlocked = assets.unlock_asset(wardrobe["id"])
        self.assertEqual(unlocked["lock_status"], "review")

    def test_generation_blocks_unlocked_location_and_wardrobe(self):
        shot = {"assets": [
            {"asset_type": "דמות", "name": "ליאורה", "lock_status": "locked"},
            {"asset_type": "לוקיישן", "name": "תחנת מרום", "lock_status": "review"},
            {"asset_type": "לבוש", "name": "חליפת ליאורה", "lock_status": "draft"},
        ]}
        with self.assertRaises(HTTPException) as caught:
            _validate_locked_assets(shot)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("תחנת מרום", caught.exception.detail)
        self.assertIn("חליפת ליאורה", caught.exception.detail)

    def test_generation_allows_locked_required_assets(self):
        shot = {"assets": [
            {"asset_type": "דמות", "name": "ליאורה", "lock_status": "locked"},
            {"asset_type": "לוקיישן", "name": "תחנת מרום", "lock_status": "locked"},
            {"asset_type": "לבוש", "name": "חליפת ליאורה", "lock_status": "locked"},
            {"asset_type": "אביזר", "name": "סורק", "lock_status": "draft"},
        ]}
        _validate_locked_assets(shot)


if __name__ == "__main__":
    unittest.main()
