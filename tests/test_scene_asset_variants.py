import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import assets, projects, scenes, scene_asset_variants


class SceneAssetVariantTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        self.project = projects.create_project({
            "name": "Variant Film",
            "description": "",
            "visual_style": "",
            "rules": "",
        })
        self.scene = scenes.create_scene({
            "project_id": self.project["id"],
            "scene_number": 1,
            "title": "לילה בעיר",
            "status": "מתוכנן",
            "story_goal": "",
            "emotion": "",
            "conflict": "",
            "beginning": "",
            "ending": "",
            "notes": "",
        })

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _locked_asset(self, asset_type: str, name: str):
        asset = assets.create_asset({
            "project_id": self.project["id"],
            "asset_type": asset_type,
            "name": name,
        })
        reference = assets.create_reference_image(asset["id"], {
            "view_type": "master",
            "url": "https://example.com/reference.jpg",
        })
        assets.set_reference_approval(asset["id"], reference["id"], True)
        return assets.lock_asset(asset["id"], reference["id"])

    def test_creates_and_updates_locked_location_variant(self):
        location = self._locked_asset("לוקיישן", "כיכר העיר")
        created = scene_asset_variants.upsert_scene_variant(self.scene["id"], location["id"], {
            "state_name": "לילה גשום",
            "description": "רחוב רטוב ושקט",
            "reference_url": "https://example.com/night.jpg",
            "visual_rules": "אור כחול קר",
        })
        self.assertEqual(created["state_name"], "לילה גשום")

        updated = scene_asset_variants.upsert_scene_variant(self.scene["id"], location["id"], {
            "state_name": "לפנות בוקר",
            "description": "",
            "reference_url": "",
            "visual_rules": "ערפל קל",
        })
        self.assertEqual(updated["id"], created["id"])
        self.assertEqual(updated["state_name"], "לפנות בוקר")
        self.assertEqual(len(scene_asset_variants.list_scene_variants(self.scene["id"])), 1)

    def test_requires_locked_location_or_wardrobe(self):
        wardrobe = assets.create_asset({
            "project_id": self.project["id"],
            "asset_type": "לבוש",
            "name": "חליפת עבודה",
        })
        with self.assertRaisesRegex(ValueError, "לנעול"):
            scene_asset_variants.upsert_scene_variant(self.scene["id"], wardrobe["id"], {
                "state_name": "אחרי משמרת",
            })

        character = self._locked_asset("דמות", "ליאורה")
        with self.assertRaisesRegex(ValueError, "ללוקיישן וללבוש"):
            scene_asset_variants.upsert_scene_variant(self.scene["id"], character["id"], {
                "state_name": "עייפה",
            })

    def test_rejects_cross_project_variant(self):
        other_project = projects.create_project({
            "name": "Other Film", "description": "", "visual_style": "", "rules": ""
        })
        asset = assets.create_asset({
            "project_id": other_project["id"],
            "asset_type": "לוקיישן",
            "name": "מחסן",
        })
        reference = assets.create_reference_image(asset["id"], {
            "view_type": "master", "url": "https://example.com/warehouse.jpg"
        })
        assets.set_reference_approval(asset["id"], reference["id"], True)
        assets.lock_asset(asset["id"], reference["id"])

        with self.assertRaisesRegex(ValueError, "אותה הפקה"):
            scene_asset_variants.upsert_scene_variant(self.scene["id"], asset["id"], {
                "state_name": "נטוש",
            })


if __name__ == "__main__":
    unittest.main()
