import unittest

from app.services.video_model_selector import select_video_model


class VideoModelSelectorTests(unittest.TestCase):
    def test_explicit_hint_wins(self):
        selection = select_video_model(
            {"shot_type": "Close-up", "dialogue": "Hello"},
            {"model_hint": "fast", "duration_seconds": 12},
        )
        self.assertEqual(selection.profile, "fast")
        self.assertIn("operator selected", selection.reason)

    def test_dialogue_prefers_high_fidelity(self):
        selection = select_video_model(
            {"shot_type": "Medium", "dialogue": "A spoken line"},
            {"model_hint": "auto", "audio_mode": "dialogue"},
        )
        self.assertEqual(selection.profile, "high_fidelity")

    def test_close_up_prefers_identity_fidelity(self):
        selection = select_video_model(
            {"shot_type": "Close-up", "dialogue": ""},
            {"model_hint": "auto", "audio_mode": "none"},
        )
        self.assertEqual(selection.profile, "high_fidelity")

    def test_long_or_complex_motion_prefers_cinematic(self):
        selection = select_video_model(
            {"shot_type": "Wide", "dialogue": ""},
            {
                "model_hint": "auto",
                "duration_seconds": 10,
                "camera_motion": "fast tracking orbit",
                "audio_mode": "none",
            },
        )
        self.assertEqual(selection.profile, "cinematic")

    def test_short_static_silent_shot_prefers_fast(self):
        selection = select_video_model(
            {"shot_type": "Insert", "dialogue": "", "movement": ""},
            {
                "model_hint": "auto",
                "duration_seconds": 3,
                "camera_motion": "",
                "audio_mode": "none",
            },
        )
        self.assertEqual(selection.profile, "fast")


if __name__ == "__main__":
    unittest.main()
