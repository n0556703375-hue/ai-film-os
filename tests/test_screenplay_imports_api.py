"""API-layer coverage for the new two-stage screenplay import router
(app/api/screenplay_imports.py): request validation, HTTP status/category
mapping, and that the endpoints correctly delegate to the service layer
already covered in depth by tests/test_screenplay_import_service.py.

Uses a real temporary SQLite database (matching the pattern in
tests/test_screenplay_import_service.py) rather than mocking the service,
since the goal here is proving the wiring end to end, not re-testing logic
already covered at the service layer.
"""

import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app.api import screenplay_imports as api
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import projects, scenes as scene_repo, shots as shot_repo

_SIMPLE_V1 = "1. INT. HOUSE - DAY\n\nJOHN\nHi there.\n"
_TWO_SCENES = (
    "1. INT. HOUSE - DAY\n\nJOHN\nHi there.\n\n"
    "2. EXT. YARD - NIGHT\n\nMARY\nHello John.\n"
)
_TWO_SCENES_CHANGED = (
    "1. INT. HOUSE - DAY\n\nJOHN\nHi there, again.\n\n"
    "2. EXT. YARD - NIGHT\n\nMARY\nHello John.\n"
)


class ScreenplayImportsApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        self.project = projects.create_project(
            {"name": "Import", "description": "", "visual_style": "", "rules": ""}
        )

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()


class CreateImportRunApiTests(ScreenplayImportsApiTestCase):
    def test_create_returns_structured_preview(self):
        result = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_TWO_SCENES)
        )
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["scene_count"], 2)
        self.assertEqual(len(result["scenes"]), 2)
        self.assertEqual(len(result["characters"]), 2)
        # No production writes yet.
        self.assertEqual(scene_repo.list_scenes(self.project["id"]), [])

    def test_missing_project_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            api.create_import_run(
                api.CreateImportRunRequest(project_id=999999, screenplay_text=_TWO_SCENES)
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_empty_screenplay_is_422_empty_script(self):
        with self.assertRaises(HTTPException) as ctx:
            api.create_import_run(
                api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text="   ")
            )
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail["code"], "empty_script")
        self.assertNotIn("Traceback", ctx.exception.detail["message"])


class GetAndListImportRunApiTests(ScreenplayImportsApiTestCase):
    def test_get_unknown_run_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            api.get_import_run(999999)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_list_requires_existing_project(self):
        with self.assertRaises(HTTPException) as ctx:
            api.list_import_runs(999999)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_list_returns_lightweight_summaries_most_recent_first(self):
        first = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_SIMPLE_V1)
        )
        second = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_TWO_SCENES)
        )
        result = api.list_import_runs(self.project["id"])
        ids = [run["id"] for run in result["import_runs"]]
        self.assertEqual(ids, [second["id"], first["id"]])
        self.assertNotIn("scenes", result["import_runs"][0])


class ReparseApiTests(ScreenplayImportsApiTestCase):
    def test_reparse_updates_same_run_with_edited_text(self):
        run = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_SIMPLE_V1)
        )
        updated = api.reparse_import_run(
            run["id"], api.ReparseRequest(screenplay_text=_TWO_SCENES)
        )
        self.assertEqual(updated["id"], run["id"])
        self.assertEqual(updated["scene_count"], 2)

    def test_reparse_unknown_run_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            api.reparse_import_run(999999, api.ReparseRequest())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_reparse_after_approval_is_409(self):
        run = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_SIMPLE_V1)
        )
        api.approve_import_run(run["id"], api.ApproveRequest())
        with self.assertRaises(HTTPException) as ctx:
            api.reparse_import_run(run["id"], api.ReparseRequest())
        self.assertEqual(ctx.exception.status_code, 409)


class DiffApiTests(ScreenplayImportsApiTestCase):
    def test_diff_unknown_run_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            api.get_import_run_diff(999999)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_diff_reports_pure_addition_without_confirmation(self):
        run = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_TWO_SCENES)
        )
        diff = api.get_import_run_diff(run["id"])
        self.assertEqual(len(diff["added"]), 2)
        self.assertFalse(diff["requires_confirmation"])


class ApproveApiTests(ScreenplayImportsApiTestCase):
    def test_approve_persists_scenes(self):
        run = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_TWO_SCENES)
        )
        summary = api.approve_import_run(run["id"], api.ApproveRequest())
        self.assertEqual(summary["scenes_added"], 2)
        self.assertEqual(len(scene_repo.list_scenes(self.project["id"])), 2)

    def test_approve_unknown_run_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            api.approve_import_run(999999, api.ApproveRequest())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_change_without_confirm_is_409_import_conflict_with_diff(self):
        first = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_TWO_SCENES)
        )
        api.approve_import_run(first["id"], api.ApproveRequest())

        second = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_TWO_SCENES_CHANGED)
        )
        with self.assertRaises(HTTPException) as ctx:
            api.approve_import_run(second["id"], api.ApproveRequest(confirm=False))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "confirmation_required")
        self.assertIn("diff", ctx.exception.detail)

        confirmed = api.approve_import_run(second["id"], api.ApproveRequest(confirm=True))
        self.assertEqual(confirmed["scenes_changed"], 1)

    def test_removing_scene_with_shots_is_blocked_even_with_confirm(self):
        first = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_TWO_SCENES)
        )
        api.approve_import_run(first["id"], api.ApproveRequest())
        existing_scenes = scene_repo.list_scenes(self.project["id"])
        scene_with_shot = existing_scenes[1]
        shot_repo.create_shot({
            "project_id": self.project["id"],
            "scene_id": scene_with_shot["id"],
            "shot_number": 1,
            "title": "שוט 1",
        })

        second = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_SIMPLE_V1)
        )
        with self.assertRaises(HTTPException) as ctx:
            api.approve_import_run(second["id"], api.ApproveRequest(confirm=True))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "downstream_data_protected")
        self.assertIn(scene_with_shot["id"], ctx.exception.detail["protected_scene_ids"])


if __name__ == "__main__":
    unittest.main()
