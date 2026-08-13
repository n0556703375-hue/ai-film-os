import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CostTrackingUiTests(unittest.TestCase):
    def test_cost_tracking_script_loads_after_dashboard_extensions(self):
        html = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn('/static/cost-tracking-ui.js', html)
        self.assertLess(html.index('/static/scene-assembly-ui.js'), html.index('/static/cost-tracking-ui.js'))

    def test_cost_dashboard_uses_existing_read_only_endpoints(self):
        script = (ROOT / "app" / "static" / "cost-tracking-ui.js").read_text(encoding="utf-8")

        self.assertIn('/api/jobs/cost-summary?project_id=${currentProjectId}', script)
        self.assertIn('/api/jobs?project_id=${currentProjectId}', script)
        self.assertIn('estimated_cost_usd', script)
        self.assertIn('actual_cost_usd', script)
        self.assertNotIn('method: "POST"', script)
        self.assertNotIn('method: "PATCH"', script)
        self.assertNotIn('method: "DELETE"', script)

    def test_cost_dashboard_surfaces_status_and_variance(self):
        script = (ROOT / "app" / "static" / "cost-tracking-ui.js").read_text(encoding="utf-8")

        self.assertIn('queued', script)
        self.assertIn('retrying', script)
        self.assertIn('failed', script)
        self.assertIn('formatSignedUsd', script)
        self.assertIn('data-cost-summary', script)

    def test_cost_dashboard_surfaces_the_project_cost_projection(self):
        # A brand-new project has zero real media_jobs, so estimated_cost_usd
        # is always $0 there — the projection (shot_count x provider rate)
        # is what gives a new project a meaningful number before anything
        # has actually been generated.
        script = (ROOT / "app" / "static" / "cost-tracking-ui.js").read_text(encoding="utf-8")

        self.assertIn('projected_total_cost_usd', script)
        self.assertIn('projected_shot_cost_usd', script)
        self.assertIn('shot_count', script)


if __name__ == "__main__":
    unittest.main()
