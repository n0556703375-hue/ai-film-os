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
from app.services import chunked_screenplay_upload as chunk_service

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
        chunk_service._pending.clear()


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

    def test_force_bypasses_duplicate_shortcut_for_already_approved_text(self):
        first = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_SIMPLE_V1)
        )
        api.approve_import_run(first["id"], api.ApproveRequest())

        without_force = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_SIMPLE_V1)
        )
        self.assertEqual(without_force["duplicate_of_import_run_id"], first["id"])

        forced = api.create_import_run(
            api.CreateImportRunRequest(
                project_id=self.project["id"], screenplay_text=_SIMPLE_V1, force=True,
            )
        )
        self.assertIsNone(forced.get("duplicate_of_import_run_id"))
        self.assertNotEqual(forced["id"], first["id"])
        self.assertEqual(forced["status"], "review_required")


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


class EntityEditApiTests(ScreenplayImportsApiTestCase):
    def test_rename_location_returns_updated_preview(self):
        run = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_TWO_SCENES)
        )
        updated = api.rename_import_run_entity(
            run["id"], "locations",
            api.RenameEntityRequest(canonical_name="HOUSE", new_name="MAIN HOUSE"),
        )
        names = sorted(loc["canonical_name"] for loc in updated["locations"])
        self.assertEqual(names, ["MAIN HOUSE", "YARD"])

    def test_rename_unknown_entity_type_is_404(self):
        run = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_TWO_SCENES)
        )
        with self.assertRaises(HTTPException) as ctx:
            api.rename_import_run_entity(
                run["id"], "unknown_type",
                api.RenameEntityRequest(canonical_name="HOUSE", new_name="MAIN HOUSE"),
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_rename_unknown_run_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            api.rename_import_run_entity(
                999999, "locations",
                api.RenameEntityRequest(canonical_name="HOUSE", new_name="MAIN HOUSE"),
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_rename_after_approval_is_409(self):
        run = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_TWO_SCENES)
        )
        api.approve_import_run(run["id"], api.ApproveRequest())
        with self.assertRaises(HTTPException) as ctx:
            api.rename_import_run_entity(
                run["id"], "locations",
                api.RenameEntityRequest(canonical_name="HOUSE", new_name="MAIN HOUSE"),
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_delete_prop_returns_updated_preview(self):
        text = "1. INT. HOUSE - DAY\n\nHe grabs the \"letter\".\n\nJOHN\nHi.\n"
        run = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=text)
        )
        updated = api.delete_import_run_entity(
            run["id"], "props", api.DeleteEntityRequest(canonical_name="letter"),
        )
        self.assertEqual(updated["props"], [])

    def test_delete_unknown_entity_is_404(self):
        run = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_TWO_SCENES)
        )
        with self.assertRaises(HTTPException) as ctx:
            api.delete_import_run_entity(
                run["id"], "locations", api.DeleteEntityRequest(canonical_name="NOWHERE"),
            )
        self.assertEqual(ctx.exception.status_code, 404)


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


class UploadChunkApiTests(ScreenplayImportsApiTestCase):
    """Covers /api/screenplay-imports/upload-chunk — the transport-only
    workaround for networks that block a single large POST body but pass
    small ones through (see chunked_screenplay_upload.py). Splitting the
    text into pieces must produce byte-for-byte the same parsed result as
    the single-shot endpoint. The finalize response is deliberately just
    an id (a large response can hit the same network filter as a large
    request) — callers fetch the full breakdown with a separate GET.
    """

    def _upload_in_chunks(self, text, chunk_size, *, upload_id="test-upload", import_run_id=None, force=False):
        pieces = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)] or [""]
        result = None
        for index, chunk_text in enumerate(pieces):
            result = api.upload_screenplay_chunk(api.UploadChunkRequest(
                upload_id=upload_id, chunk_text=chunk_text, is_final=(index == len(pieces) - 1),
                project_id=self.project["id"], import_run_id=import_run_id, force=force,
            ))
        return result

    def test_multi_chunk_upload_produces_the_same_result_as_single_shot(self):
        direct = api.create_import_run(
            api.CreateImportRunRequest(project_id=self.project["id"], screenplay_text=_TWO_SCENES)
        )
        chunked = self._upload_in_chunks(_TWO_SCENES, chunk_size=7, upload_id="upload-a")
        self.assertTrue(chunked["completed"])

        fetched = api.get_import_run(chunked["import_run_id"])
        self.assertEqual(fetched["scene_count"], direct["scene_count"])
        self.assertEqual(fetched["character_count"], direct["character_count"])
        self.assertEqual(fetched["scenes"], direct["scenes"])

    def test_intermediate_chunks_report_progress_without_completing(self):
        pieces = [_TWO_SCENES[i:i + 5] for i in range(0, len(_TWO_SCENES), 5)]
        first = api.upload_screenplay_chunk(api.UploadChunkRequest(
            upload_id="upload-b", chunk_text=pieces[0], is_final=False,
            project_id=self.project["id"],
        ))
        self.assertFalse(first["completed"])
        self.assertEqual(first["received_chars"], len(pieces[0]))
        # No production writes, and no import run created yet either.
        self.assertEqual(scene_repo.list_scenes(self.project["id"]), [])

    def test_chunked_upload_can_reparse_an_existing_run(self):
        created = self._upload_in_chunks(_SIMPLE_V1, chunk_size=6, upload_id="upload-c")
        reparsed = self._upload_in_chunks(
            _TWO_SCENES, chunk_size=9, upload_id="upload-d", import_run_id=created["import_run_id"],
        )
        self.assertTrue(reparsed["completed"])
        self.assertEqual(reparsed["import_run_id"], created["import_run_id"])

        fetched = api.get_import_run(reparsed["import_run_id"])
        self.assertEqual(fetched["scene_count"], 2)

    def test_reparsing_an_approved_run_via_chunks_is_rejected(self):
        created = self._upload_in_chunks(_SIMPLE_V1, chunk_size=6, upload_id="upload-e")
        api.approve_import_run(created["import_run_id"], api.ApproveRequest())
        with self.assertRaises(HTTPException) as ctx:
            self._upload_in_chunks(
                _TWO_SCENES, chunk_size=9, upload_id="upload-f",
                import_run_id=created["import_run_id"],
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_missing_project_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            api.upload_screenplay_chunk(api.UploadChunkRequest(
                upload_id="upload-g", chunk_text="hi", is_final=True, project_id=999999,
            ))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_inconsistent_project_id_mid_upload_is_409_upload_mismatch(self):
        other_project = projects.create_project(
            {"name": "Other", "description": "", "visual_style": "", "rules": ""}
        )
        api.upload_screenplay_chunk(api.UploadChunkRequest(
            upload_id="upload-h", chunk_text="AAA", is_final=False,
            project_id=self.project["id"],
        ))
        with self.assertRaises(HTTPException) as ctx:
            api.upload_screenplay_chunk(api.UploadChunkRequest(
                upload_id="upload-h", chunk_text="BBB", is_final=True,
                project_id=other_project["id"],
            ))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "upload_mismatch")

    def test_duplicate_of_an_already_approved_screenplay_is_reported_via_chunks(self):
        first = self._upload_in_chunks(_SIMPLE_V1, chunk_size=6, upload_id="upload-i")
        api.approve_import_run(first["import_run_id"], api.ApproveRequest())

        second = self._upload_in_chunks(_SIMPLE_V1, chunk_size=6, upload_id="upload-j")
        self.assertEqual(second["duplicate_of_import_run_id"], first["import_run_id"])

    def test_force_bypasses_duplicate_shortcut_via_chunks(self):
        first = self._upload_in_chunks(_SIMPLE_V1, chunk_size=6, upload_id="upload-k")
        api.approve_import_run(first["import_run_id"], api.ApproveRequest())

        forced = self._upload_in_chunks(
            _SIMPLE_V1, chunk_size=6, upload_id="upload-l", force=True,
        )
        self.assertIsNone(forced.get("duplicate_of_import_run_id"))
        self.assertNotEqual(forced["import_run_id"], first["import_run_id"])


if __name__ == "__main__":
    unittest.main()
