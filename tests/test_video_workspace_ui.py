import unittest
from pathlib import Path


class VideoWorkspaceUiTests(unittest.TestCase):
    def test_video_queue_controls_are_exposed_in_workspace_script(self):
        script = Path("app/static/job-queue-ui.js").read_text(encoding="utf-8")

        self.assertIn("data-video-generation-button", script)
        self.assertIn("videoDuration", script)
        self.assertIn("videoMotion", script)
        self.assertIn("videoAudio", script)
        self.assertIn("videoModel", script)
        self.assertIn("/api/video-generation/shots/${shotId}/queue", script)
        self.assertIn('value="ambient"', script)
        self.assertIn('value="high_fidelity"', script)
        self.assertNotIn("/api/generation/shots/${shotId}/video/queue", script)
        self.assertNotIn('value="ambience"', script)
        self.assertNotIn('value="high_quality"', script)
        self.assertIn("confirm(", script)

    def test_video_completion_renders_a_video_element(self):
        script = Path("app/static/job-queue-ui.js").read_text(encoding="utf-8")

        self.assertIn("<video", script)
        self.assertIn("controls", script)
        self.assertIn("waitForMediaJob", script)


if __name__ == "__main__":
    unittest.main()
