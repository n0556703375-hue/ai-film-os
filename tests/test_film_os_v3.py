import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import get_connection, init_db
from app.repositories import issues, projects, scenes, shots, assets


class FilmOSV3Tests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_database_path = settings.database_path
        settings.database_path = Path(self.temp_dir.name) / "film_os.db"
        init_db()

    def tearDown(self):
        settings.database_path = self.previous_database_path
        self.temp_dir.cleanup()

    def test_reinitialization_preserves_existing_data_and_adds_columns(self):
        with get_connection() as conn:
            conn.execute("UPDATE shots SET notes='מידע קיים' WHERE id=1")
            conn.commit()

        init_db()

        with get_connection() as conn:
            shot = conn.execute("SELECT * FROM shots WHERE id=1").fetchone()
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(shots)")}
            self.assertEqual(shot["notes"], "מידע קיים")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM shots").fetchone()[0], 20)
            self.assertTrue({"duration_seconds", "composition", "audio", "negative_prompt"} <= columns)

    def test_scene_shot_prompt_media_and_continuity_workflow(self):
        scene = scenes.create_scene({
            "project_id": 1,
            "scene_number": 6,
            "title": "סצנת בדיקה",
            "status": "בעבודה",
            "story_goal": "בדיקת הזרימה",
            "emotion": "",
            "conflict": "",
            "beginning": "",
            "ending": "",
            "notes": "",
        })
        shot = shots.create_shot({
            "project_id": 1,
            "scene_id": scene["id"],
            "shot_number": 21,
            "title": "שוט בדיקה",
            "shot_type": "Close-up",
            "duration_seconds": 3.5,
        })
        shots.update_shot(shot["id"], {"prompt": "גרסה ראשונה", "negative_prompt": "ללא טקסט"})
        shots.update_shot(shot["id"], {"prompt": "גרסה שנייה"})
        versions = shots.list_prompt_versions(shot["id"])
        self.assertEqual([item["version"] for item in versions], [2, 1])

        image_one = shots.create_media_result(shot["id"], {
            "media_type": "image", "url": "https://example.com/one.jpg"
        })
        image_two = shots.create_media_result(shot["id"], {
            "media_type": "image", "url": "https://example.com/two.jpg"
        })
        self.assertEqual((image_one["version"], image_two["version"]), (1, 2))

        issue = issues.create_issue({
            "project_id": 1,
            "shot_id": shot["id"],
            "severity": "high",
            "category": "צבע",
            "message": "גוון אינו תואם",
            "status": "פתוח",
            "expected": "כחול קר",
            "observed": "כחול חם",
            "resolution": "",
        })
        updated = issues.update_issue(issue["id"], {"status": "נפתר", "resolution": "הגוון תוקן"})
        self.assertEqual(updated["status"], "נפתר")
        self.assertEqual(updated["resolved"], 1)


    def test_scenes_shots_assets_and_issues_are_isolated_per_project(self):
        second_project = projects.create_project({
            "name": "פרויקט שני",
            "description": "בדיקת בידוד נתונים",
            "visual_style": "",
            "rules": "",
        })

        second_scene = scenes.create_scene({
            "project_id": second_project["id"],
            "scene_number": 1,
            "title": "סצנה בפרויקט השני",
            "status": "מתוכנן",
            "story_goal": "", "emotion": "", "conflict": "",
            "beginning": "", "ending": "", "notes": "",
        })
        shots.create_shot({
            "project_id": second_project["id"],
            "scene_id": second_scene["id"],
            "shot_number": 1,
            "title": "שוט בפרויקט השני",
        })
        assets.create_asset({
            "project_id": second_project["id"],
            "asset_type": "דמות",
            "name": "דמות בפרויקט השני",
            "approved": False,
        })
        issues.create_issue({
            "project_id": second_project["id"],
            "severity": "medium",
            "category": "בדיקה",
            "message": "בעיה בפרויקט השני",
            "status": "פתוח",
        })

        # Original seeded project (id=1) must not see the second project's data.
        self.assertTrue(all(s["project_id"] == 1 for s in scenes.list_scenes(1)))
        self.assertTrue(all(s["project_id"] == 1 for s in shots.list_shots(1)))
        self.assertTrue(all(a["project_id"] == 1 for a in assets.list_assets(1)))
        self.assertTrue(all(
            i["project_id"] == 1 for i in issues.list_issues(project_id=1)
        ))

        # The second project must only see its own single scene/shot/asset/issue.
        self.assertEqual(len(scenes.list_scenes(second_project["id"])), 1)
        self.assertEqual(len(shots.list_shots(second_project["id"])), 1)
        self.assertEqual(len(assets.list_assets(second_project["id"])), 1)
        self.assertEqual(len(issues.list_issues(project_id=second_project["id"])), 1)

        # Unfiltered calls still return everything (backward compatible default).
        self.assertGreaterEqual(len(scenes.list_scenes()), 6)
        self.assertGreaterEqual(len(shots.list_shots()), 21)


if __name__ == "__main__":
    unittest.main()
