import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContinuityUiTests(unittest.TestCase):
    def test_workspace_loads_continuity_ui_after_other_overrides(self):
        html = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn('/static/continuity-ui.js', html)
        self.assertLess(html.index('/static/job-queue-ui.js'), html.index('/static/continuity-ui.js'))

    def test_continuity_ui_surfaces_saved_and_preview_blockers(self):
        script = (ROOT / "app" / "static" / "continuity-ui.js").read_text(encoding="utf-8")

        self.assertIn('/api/issues/shots/${shotId}/continuity-preview', script)
        self.assertIn('/api/issues?resolved=false', script)
        self.assertIn('["critical", "high"]', script)
        self.assertIn('neighbor_shot_id', script)
        self.assertIn('האישור הסופי חסום', script)

    def test_continuity_ui_is_read_only(self):
        script = (ROOT / "app" / "static" / "continuity-ui.js").read_text(encoding="utf-8")

        self.assertNotIn('method: "POST"', script)
        self.assertNotIn('method: "PATCH"', script)
        self.assertNotIn('method: "DELETE"', script)


if __name__ == "__main__":
    unittest.main()
