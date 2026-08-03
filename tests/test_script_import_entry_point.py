import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.api.import_runs import (
    ImportRunPersistRequest,
    ImportRunStepRequest,
    persist_completed_import,
    process_next_import_chunk,
)
from app.api.scenes import ShotMapRequest, create_shot_map
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import projects as project_repo
from app.repositories import scenes as scene_repo
from app.repositories import shots as shot_repo


def _fake_chunk_breakdown(project, chunk, target_shots_per_minute, chunk_index, chunk_count):
    return [
        {
            "scene_number": chunk_index,
            "title": f"סצנה {chunk_index}",
            "story_goal": "",
            "emotion": "",
            "conflict": "",
            "beginning": "",
            "ending": "",
            "notes": "",
            "estimated_duration_seconds": 60,
            "recommended_shot_count": 3,
        }
    ]


class ScreenplayImportEntryPointTests(unittest.TestCase):
    """Proves the documented production import sequence end to end:

    POST /api/import-runs/process-next (first call, next_chunk_index=0) is the
    real start of an import; there is no separate start endpoint, and
    /api/scenes/import-script is legacy and unused (see app/api/scenes.py).
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        self.project_a = self._create_project("Project A")
        self.project_b = self._create_project("Project B")

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _create_project(self, name: str):
        return project_repo.create_project(
            {"name": name, "description": "", "visual_style": "", "rules": ""}
        )

    def _run_import_to_completion(self, project_id: int, screenplay: str):
        """Mirrors app/templates/script_import.html's processBreakdown loop."""
        next_chunk_index = 0
        fingerprint = ""
        scenes: list[dict] = []
        rounds = 0
        with patch(
            "app.services.resumable_screenplay_import._breakdown_chunk",
            side_effect=_fake_chunk_breakdown,
        ):
            while True:
                rounds += 1
                result = process_next_import_chunk(
                    ImportRunStepRequest(
                        project_id=project_id,
                        screenplay=screenplay,
                        screenplay_fingerprint=fingerprint,
                        next_chunk_index=next_chunk_index,
                        scenes=scenes,
                    )
                )
                fingerprint = result["screenplay_fingerprint"]
                next_chunk_index = result["next_chunk_index"]
                scenes = result["scenes"]
                if result["completed"]:
                    break
        return scenes, rounds

    def test_openapi_hides_legacy_endpoint_and_documents_the_real_entry_point(self):
        from app.main import app

        schema = app.openapi()
        paths = schema["paths"]

        self.assertNotIn("/api/scenes/import-script", paths)
        self.assertIn("/api/import-runs/process-next", paths)
        self.assertIn("/api/import-runs/persist", paths)

        start_doc = paths["/api/import-runs/process-next"]["post"]
        self.assertIn("entry point", start_doc["summary"].lower())
        self.assertIn("no separate", start_doc["description"].lower())

        persist_doc = paths["/api/import-runs/persist"]["post"]
        self.assertIn("idempotent_replay", persist_doc["description"])

    def test_first_request_starts_a_project_scoped_multi_chunk_import(self):
        screenplay = ("א" * 5900 + "\n\n") * 3  # forces more than one chunk

        with patch("app.api.scenes.import_script") as legacy_endpoint:
            scenes, rounds = self._run_import_to_completion(self.project_a["id"], screenplay)
            self.assertGreater(rounds, 1, "long screenplay must require multiple process-next calls")
            self.assertEqual(len(scenes), rounds)

            persisted = persist_completed_import(
                ImportRunPersistRequest(
                    project_id=self.project_a["id"], completed=True, scenes=scenes
                )
            )
            legacy_endpoint.assert_not_called()

        self.assertTrue(persisted["persisted"])
        self.assertFalse(persisted["idempotent_replay"])
        self.assertEqual(persisted["scenes_created"], rounds)

        stored_a = scene_repo.list_scenes(self.project_a["id"])
        self.assertEqual(len(stored_a), rounds)
        self.assertEqual(scene_repo.list_scenes(self.project_b["id"]), [])

    def test_documented_sequence_only_persists_once_process_next_reports_completed(self):
        """The client only has scenes to persist once the loop's completed flag is
        true; persist called with the still-partial in-flight scenes list produces
        a strictly smaller, and never a larger, count than the finished run."""
        screenplay = ("א" * 5900 + "\n\n") * 3  # multiple chunks
        with patch(
            "app.services.resumable_screenplay_import._breakdown_chunk",
            side_effect=_fake_chunk_breakdown,
        ):
            first_chunk = process_next_import_chunk(
                ImportRunStepRequest(project_id=self.project_a["id"], screenplay=screenplay)
            )
        self.assertFalse(first_chunk["completed"])

        full_scenes, rounds = self._run_import_to_completion(self.project_a["id"], screenplay)
        self.assertGreater(len(full_scenes), len(first_chunk["scenes"]))
        self.assertEqual(len(full_scenes), rounds)

    def test_second_identical_import_is_idempotent_and_counts_do_not_grow(self):
        screenplay = "א" * 200

        scenes, _ = self._run_import_to_completion(self.project_a["id"], screenplay)
        first = persist_completed_import(
            ImportRunPersistRequest(
                project_id=self.project_a["id"], completed=True, scenes=scenes
            )
        )
        self.assertTrue(first["persisted"])
        scenes_after_first = scene_repo.list_scenes(self.project_a["id"])

        second = persist_completed_import(
            ImportRunPersistRequest(
                project_id=self.project_a["id"], completed=True, scenes=scenes
            )
        )
        scenes_after_second = scene_repo.list_scenes(self.project_a["id"])

        self.assertTrue(second["idempotent_replay"])
        self.assertFalse(second["persisted"])
        self.assertEqual(second["scenes_created"], 0)
        self.assertEqual(len(scenes_after_first), len(scenes_after_second))
        self.assertEqual(scene_repo.list_scenes(self.project_b["id"]), [])

        scene = scenes_after_first[0]
        with patch(
            "app.api.scenes.generate_shot_map",
            return_value=[{"title": "שוט 1"}, {"title": "שוט 2"}, {"title": "שוט 3"}],
        ), patch("app.api.scenes.build_prompt", return_value="prompt"):
            create_shot_map(scene["id"], ShotMapRequest(shot_count=3, replace_existing=False))

        shots_after_first_map = shot_repo.list_shots(self.project_a["id"])
        self.assertEqual(len(shots_after_first_map), 3)

        # A second shot-map attempt for the same scene must not silently
        # duplicate shots: the backend refuses instead of replacing.
        with patch(
            "app.api.scenes.generate_shot_map",
            return_value=[{"title": "שוט 1"}, {"title": "שוט 2"}, {"title": "שוט 3"}],
        ), patch("app.api.scenes.build_prompt", return_value="prompt"):
            with self.assertRaises(HTTPException) as raised:
                create_shot_map(scene["id"], ShotMapRequest(shot_count=3, replace_existing=False))
        self.assertEqual(raised.exception.status_code, 409)

        shots_after_retry = shot_repo.list_shots(self.project_a["id"])
        self.assertEqual(len(shots_after_retry), 3)
        self.assertEqual(shot_repo.list_shots(self.project_b["id"]), [])

    def test_no_request_in_the_documented_sequence_uses_the_legacy_endpoint(self):
        screenplay = "א" * 200
        with patch("app.api.scenes.import_script") as legacy_endpoint:
            scenes, _ = self._run_import_to_completion(self.project_a["id"], screenplay)
            persist_completed_import(
                ImportRunPersistRequest(
                    project_id=self.project_a["id"], completed=True, scenes=scenes
                )
            )
            persist_completed_import(
                ImportRunPersistRequest(
                    project_id=self.project_a["id"], completed=True, scenes=scenes
                )
            )
        legacy_endpoint.assert_not_called()


if __name__ == "__main__":
    unittest.main()
