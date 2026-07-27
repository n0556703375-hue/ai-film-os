import unittest

from app.services.video_model_selection import select_video_model_profile


class VideoModelSelectionTests(unittest.TestCase):
    def test_explicit_operator_hint_wins(self):
        profile = select_video_model_profile(
            {"movement": "fast tracking chase"},
            {"model_hint": "high_fidelity", "duration_seconds": 20, "audio_mode": "none"},
        )
        self.assertEqual(profile.name, "high_fidelity")
        self.assertEqual(profile.reason, "operator_hint")

    def test_dialogue_selects_high_fidelity(self):
        profile = select_video_model_profile(
            {"movement": "locked camera"},
            {"model_hint": "auto", "duration_seconds": 5, "audio_mode": "dialogue"},
        )
        self.assertEqual(profile.name, "high_fidelity")

    def test_close_up_selects_high_fidelity(self):
        profile = select_video_model_profile(
            {"camera": "close-up portrait", "movement": ""},
            {"model_hint": "auto", "duration_seconds": 5, "audio_mode": "none"},
        )
        self.assertEqual(profile.name, "high_fidelity")

    def test_long_or_complex_motion_selects_cinematic(self):
        profile = select_video_model_profile(
            {"movement": "slow crane and orbit"},
            {"model_hint": "auto", "duration_seconds": 14, "audio_mode": "ambient"},
        )
        self.assertEqual(profile.name, "cinematic")

    def test_standard_short_shot_selects_fast(self):
        profile = select_video_model_profile(
            {"movement": "static"},
            {"model_hint": "auto", "duration_seconds": 5, "audio_mode": "none"},
        )
        self.assertEqual(profile.name, "fast")


if __name__ == "__main__":
    unittest.main()
