import unittest
from unittest.mock import patch

from app.services.resumable_screenplay_import import (
    ImportRunState,
    process_next_chunk,
    restore_state,
    serialize_state,
)


class ResumableScreenplayImportTests(unittest.TestCase):
    @patch("app.services.resumable_screenplay_import._breakdown_chunk")
    def test_processes_exactly_one_chunk_per_call(self, breakdown_chunk):
        breakdown_chunk.side_effect = [
            [{"title": "א"}],
            [{"title": "ב"}],
        ]
        state = ImportRunState(project_id=7, screenplay=("קטע ראשון\n\n" + "א" * 6000 + "\n\nקטע שני"))

        process_next_chunk({"id": 7}, state)

        self.assertEqual(state.next_chunk_index, 1)
        self.assertEqual(state.scenes[0]["scene_number"], 1)
        self.assertEqual(state.scenes[0]["title"], "א")
        self.assertEqual(state.scenes[0]["status"], "מתוכנן")
        self.assertEqual(state.scenes[0]["recommended_shot_count"], 6)
        self.assertFalse(state.completed)
        breakdown_chunk.assert_called_once()

    @patch("app.services.resumable_screenplay_import._breakdown_chunk")
    def test_assigns_unique_global_scene_numbers_across_chunks(self, breakdown_chunk):
        breakdown_chunk.side_effect = [
            [{"scene_number": 1, "title": "פתיחה"}],
            [{"scene_number": 1, "title": "המשך"}],
        ]
        state = ImportRunState(project_id=7, screenplay="א" * 6000)

        process_next_chunk({"id": 7}, state)
        process_next_chunk({"id": 7}, state)

        self.assertTrue(state.completed)
        self.assertEqual(
            [(scene["scene_number"], scene["title"]) for scene in state.scenes],
            [(1, "פתיחה"), (2, "המשך")],
        )

    @patch("app.services.resumable_screenplay_import._breakdown_chunk")
    def test_normalizes_provider_bounds_before_returning_resumable_state(self, breakdown_chunk):
        breakdown_chunk.return_value = [{
            "scene_number": 99,
            "title": "",
            "estimated_duration_seconds": 1,
            "recommended_shot_count": 999,
        }]
        state = ImportRunState(project_id=7, screenplay="א" * 80)

        process_next_chunk({"id": 7}, state)

        self.assertEqual(state.scenes[0]["scene_number"], 1)
        self.assertEqual(state.scenes[0]["title"], "סצנה 1")
        self.assertEqual(state.scenes[0]["estimated_duration_seconds"], 5)
        self.assertEqual(state.scenes[0]["recommended_shot_count"], 60)

    @patch("app.services.resumable_screenplay_import._breakdown_chunk")
    def test_completed_state_is_idempotent(self, breakdown_chunk):
        state = ImportRunState(project_id=7, screenplay="א" * 80, next_chunk_index=1, scenes=[{"title": "א"}])

        process_next_chunk({"id": 7}, state)

        self.assertTrue(state.completed)
        self.assertEqual(state.scenes, [{"title": "א"}])
        breakdown_chunk.assert_not_called()

    def test_state_round_trip_preserves_progress_and_fingerprint(self):
        original = ImportRunState(
            project_id=7,
            screenplay="א" * 80,
            target_shots_per_minute=4.5,
            next_chunk_index=1,
            scenes=[{"title": "א"}],
        )
        payload = serialize_state(original)
        restored = restore_state(payload)

        self.assertEqual(restored.project_id, 7)
        self.assertEqual(restored.screenplay, original.screenplay)
        self.assertEqual(restored.target_shots_per_minute, 4.5)
        self.assertEqual(restored.next_chunk_index, 1)
        self.assertEqual(restored.scenes, [{"title": "א"}])
        self.assertEqual(payload["screenplay_fingerprint"], original.screenplay_fingerprint)

    def test_restore_rejects_changed_screenplay_for_saved_fingerprint(self):
        original = ImportRunState(project_id=7, screenplay="א" * 80)
        payload = serialize_state(original)
        payload["screenplay"] = "ב" * 80

        with self.assertRaisesRegex(ValueError, "אינו תואם"):
            restore_state(payload)

    def test_empty_screenplay_is_rejected_before_provider_call(self):
        with self.assertRaisesRegex(ValueError, "ריק"):
            process_next_chunk({"id": 7}, ImportRunState(project_id=7, screenplay="   "))


if __name__ == "__main__":
    unittest.main()
