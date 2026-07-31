import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import issues, projects, scenes, shots


class ContinuityIssueResolveProjectIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()

        self.first = self._create_production("First")
        self.second = self._create_production("Second")
        self.issue = issues.create_issue({
            "project_id": self.first["project"]["id"],
            "shot_id": self.first["shot"]["id"],
            "asset_id": None,
            "severity": "high",
            "category": "continuity",
            "message": "Keep resolution scoped",
            "status": "פתוח",
        })

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
        return {"project": project, "scene": scene, "shot": shot}

    def _stored_issue(self):
        stored = issues.list_issues(
            project_id=self.first["project"]["id"],
        )
        self.assertEqual(len(stored), 1)
        return stored[0]

    def test_resolve_rejects_issue_owned_by_another_project_without_mutation(self):
        updated = issues.resolve_issue(
            self.issue["id"],
            self.second["project"]["id"],
            True,
        )

        self.assertFalse(updated)
        stored = self._stored_issue()
        self.assertEqual(stored["resolved"], 0)
        self.assertEqual(stored["status"], "פתוח")

    def test_resolve_updates_only_the_owning_project(self):
        updated = issues.resolve_issue(
            self.issue["id"],
            self.first["project"]["id"],
            True,
        )

        self.assertTrue(updated)
        stored = self._stored_issue()
        self.assertEqual(stored["resolved"], 1)
        self.assertEqual(stored["status"], "נפתר")
        self.assertEqual(
            issues.list_issues(project_id=self.second["project"]["id"]),
            [],
        )

    def test_resolve_rejects_unknown_project_without_mutation(self):
        with self.assertRaisesRegex(ValueError, "הפרויקט שנבחר אינו קיים"):
            issues.resolve_issue(self.issue["id"], 999999, True)

        stored = self._stored_issue()
        self.assertEqual(stored["resolved"], 0)
        self.assertEqual(stored["status"], "פתוח")


if __name__ == "__main__":
    unittest.main()
