import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import assets, projects


class CharacterLockTests(unittest.TestCase):
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
        self.character = assets.create_asset({
            "project_id": self.project["id"],
            "asset_type": "דמות",
            "name": "ליאורה",
        })
        self.reference = assets.create_reference_image(self.character["id"], {
            "view_type": "portrait",
            "url": "https://example.com/liora.jpg",
        })

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def test_lock_requires_approved_reference(self):
        with self.assertRaisesRegex(ValueError, "לאשר"):
            assets.lock_character(self.character["id"], self.reference["id"])

    def test_lock_sets_master_and_blocks_identity_edit(self):
        assets.set_reference_approval(self.character["id"], self.reference["id"], True)
        locked = assets.lock_character(self.character["id"], self.reference["id"])
        self.assertEqual(locked["lock_status"], "locked")
        self.assertEqual(locked["master_reference_id"], self.reference["id"])
        self.assertEqual(locked["reference_url"], self.reference["url"])
        with self.assertRaisesRegex(ValueError, "נכס נעול"):
            assets.update_asset(self.character["id"], {"reference_url": "https://example.com/other.jpg"})

    def test_unlock_allows_identity_edit(self):
        assets.set_reference_approval(self.character["id"], self.reference["id"], True)
        assets.lock_character(self.character["id"], self.reference["id"])
        unlocked = assets.unlock_character(self.character["id"])
        self.assertEqual(unlocked["lock_status"], "review")
        updated = assets.update_asset(self.character["id"], {"reference_url": "https://example.com/other.jpg"})
        self.assertEqual(updated["reference_url"], "https://example.com/other.jpg")

    def test_locked_master_cannot_be_unapproved(self):
        assets.set_reference_approval(self.character["id"], self.reference["id"], True)
        assets.lock_character(self.character["id"], self.reference["id"])
        with self.assertRaisesRegex(ValueError, "רפרנס הראשי"):
            assets.set_reference_approval(self.character["id"], self.reference["id"], False)


if __name__ == "__main__":
    unittest.main()
