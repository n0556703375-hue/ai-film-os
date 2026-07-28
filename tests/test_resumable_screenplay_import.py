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
        self.assertEqual(state.scenes, [{"title": "א"}])
        self.assertFalse(state.completed)
        breakdown_chunk.assert_called_once()

    @patch("app.services.resumable_screenplay_import._breakdown_chunk")
    def test_completed_state_is_idempotent(self, breakdown_chunk):
        state = ImportRunState(project_id=7, screenplay="א" * 80, next_chunk_index=1, scenes=[{"title": "א"}])

        process_next_chunk({"id": 7}, state)

        self.assertTrue(state.completed)
        self.assertEqual(state.scenes, [{"title": "א"}])
        breakdown_chunk.assert_not_called()

    def test_state_round_trip_preserves_progress(self):
        original = ImportRunState(
            project_id=7,
            screenplay="א" * 80,
            target_shots_per_minute=4.5,
            next_chunk_index=1,
            scenes=[{"title": "א"}],
        )

        restored = restore_state(serialize_state(original))

        self.assertEqual(restored.project_id, 7)
        self.assertEqual(restored.screenplay, original.screenplay)
        self.assertEqual(restored.target_shots_per_minute, 4.5)
        self.assertEqual(restored.next_chunk_index, 1)
        self.assertEqual(restored.scenes, [{"title": "א"}])

    def test_empty_screenplay_is_rejected_before_provider_call(self):
        with self.assertRaisesRegex(ValueError, "ריק"):
            process_next_chunk({"id": 7}, ImportRunState(project_id=7, screenplay="   "))


if __name__ == "__main__":
    unittest.main()
