import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ShotFiltersUiTests(unittest.TestCase):
    def test_filter_script_loads_after_base_workspace_scripts(self):
        html = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn('/static/shot-filters-ui.js', html)
        self.assertLess(html.index('/static/cost-tracking-ui.js'), html.index('/static/shot-filters-ui.js'))

    def test_filters_cover_status_scene_and_search(self):
        script = (ROOT / "app" / "static" / "shot-filters-ui.js").read_text(encoding="utf-8")
        self.assertIn('shotFilterStatus', script)
        self.assertIn('shotFilterScene', script)
        self.assertIn('shotFilterQuery', script)
        self.assertIn('matchesStatus', script)
        self.assertIn('matchesScene', script)
        self.assertIn('matchesQuery', script)

    def test_filter_loading_is_read_only(self):
        script = (ROOT / "app" / "static" / "shot-filters-ui.js").read_text(encoding="utf-8")
        start = script.index("window.loadShots = async function loadShotsWithFilters()")
        end = script.index("function renderFilteredShotCard", start)
        filter_loader = script[start:end]

        self.assertIn('api("/api/shots")', filter_loader)
        for method in ("POST", "PATCH", "DELETE"):
            self.assertNotIn(f'method: "{method}"', filter_loader)
            self.assertNotIn(f'method:"{method}"', filter_loader)


if __name__ == "__main__":
    unittest.main()
