import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import issues, projects


class ProjectScopedResolvedIssueCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()

        self.first_project = self._create_project("First")
        self.second_project = self._create_project("Second")

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _create_project(self, name: str):
        return projects.create_project({
            "name": name,
            "description": "",
            "visual_style": "",
            "rules": "",
        })

    def _create_resolved_issue(self, project_id: int, message: str):
        return issues.create_issue({
            "project_id": project_id,
            "severity": "medium",
            "category": "continuity",
            "message": message,
            "status": "נפתר",
        })

    def test_cleanup_removes_only_resolved_issues_from_requested_project(self):
        first_resolved = self._create_resolved_issue(
            self.first_project["id"], "First resolved",
        )
        second_resolved = self._create_resolved_issue(
            self.second_project["id"], "Second resolved",
        )
        first_open = issues.create_issue({
            "project_id": self.first_project["id"],
            "severity": "medium",
            "category": "continuity",
            "message": "First open",
            "status": "פתוח",
        })

        deleted = issues.clear_resolved(self.first_project["id"])

        self.assertEqual(deleted, 1)
        self.assertEqual(
            {item["id"] for item in issues.list_issues(project_id=self.first_project["id"])},
            {first_open["id"]},
        )
        self.assertEqual(
            {item["id"] for item in issues.list_issues(project_id=self.second_project["id"])},
            {second_resolved["id"]},
        )
        self.assertNotEqual(first_resolved["id"], second_resolved["id"])

    def test_cleanup_rejects_missing_project_without_deleting_anything(self):
        first_resolved = self._create_resolved_issue(
            self.first_project["id"], "First resolved",
        )

        with self.assertRaisesRegex(ValueError, "הפרויקט שנבחר אינו קיים"):
            issues.clear_resolved(999999)

        self.assertEqual(
            {item["id"] for item in issues.list_issues(project_id=self.first_project["id"])},
            {first_resolved["id"]},
        )


if __name__ == "__main__":
    unittest.main()
