import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import assets, issues, projects, scenes, shots


class ContinuityIssueProjectOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()

        self.first = self._create_production("First")
        self.second = self._create_production("Second")

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _create_production(self, marker: str):
        project = projects.create_project({
            "name": f"{marker} Production",
            "description": "",
            "visual_style": "",
            "rules": "",
        })
        scene = scenes.create_scene({
            "project_id": project["id"],
            "scene_number": 1,
            "title": f"{marker} Scene",
            "status": "מתוכנן",
            "story_goal": "",
            "emotion": "",
            "conflict": "",
            "beginning": "",
            "ending": "",
            "notes": "",
        })
        shot = shots.create_shot({
            "project_id": project["id"],
            "scene_id": scene["id"],
            "shot_number": 1,
            "title": f"{marker} Shot",
            "status": "מתוכנן",
        })
        asset = assets.create_asset({
            "project_id": project["id"],
            "asset_type": "אביזר",
            "name": f"{marker} Asset",
            "description": "",
        })
        return {"project": project, "scene": scene, "shot": shot, "asset": asset}

    def _issue_data(self):
        return {
            "project_id": self.first["project"]["id"],
            "shot_id": self.first["shot"]["id"],
            "asset_id": self.first["asset"]["id"],
            "severity": "high",
            "category": "continuity",
            "message": "Keep relationships scoped",
            "status": "פתוח",
        }

    def test_create_rejects_shot_and_asset_from_other_projects_without_writing(self):
        with self.assertRaisesRegex(ValueError, "שוט מפרויקט אחר"):
            issues.create_issue({
                **self._issue_data(),
                "shot_id": self.second["shot"]["id"],
            })

        with self.assertRaisesRegex(ValueError, "נכס מפרויקט אחר"):
            issues.create_issue({
                **self._issue_data(),
                "asset_id": self.second["asset"]["id"],
            })

        self.assertEqual(issues.list_issues(), [])

    def test_update_rejects_cross_project_relationship_without_mutating_issue(self):
        created = issues.create_issue(self._issue_data())

        with self.assertRaisesRegex(ValueError, "שוט מפרויקט אחר"):
            issues.update_issue(created["id"], {
                "shot_id": self.second["shot"]["id"],
            })

        with self.assertRaisesRegex(ValueError, "נכס מפרויקט אחר"):
            issues.update_issue(created["id"], {
                "asset_id": self.second["asset"]["id"],
            })

        stored = issues.list_issues(project_id=self.first["project"]["id"])
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["shot_id"], self.first["shot"]["id"])
        self.assertEqual(stored[0]["asset_id"], self.first["asset"]["id"])
        self.assertEqual(
            issues.list_issues(project_id=self.second["project"]["id"]),
            [],
        )


if __name__ == "__main__":
    unittest.main()
