import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.api.production_brain import get_production_brain, get_production_snapshot


class ProductionSnapshotApiPanelTests(unittest.TestCase):
    def test_snapshot_endpoint_returns_read_only_snapshot(self):
        snapshot = {
            "project": {"id": 7},
            "scenes": [],
            "shots": [],
            "assets": [],
            "continuity_issues": [],
            "read_only": True,
        }
        with patch("app.api.production_brain.build_production_snapshot", return_value=snapshot):
            self.assertEqual(get_production_snapshot(7), snapshot)

    def test_brain_endpoint_evaluates_the_same_snapshot(self):
        snapshot = {
            "project": {"id": 7},
            "scenes": [],
            "shots": [],
            "assets": [],
            "continuity_issues": [],
            "read_only": True,
        }
        decision = {"project_id": 7, "project_status": "ready", "read_only": True}
        with patch("app.api.production_brain.build_production_snapshot", return_value=snapshot), patch(
            "app.api.production_brain.evaluate_production_snapshot", return_value=decision
        ) as evaluate:
            result = get_production_brain(7)

        self.assertEqual(result, {"snapshot": snapshot, "decision": decision})
        evaluate.assert_called_once_with(snapshot)

    def test_unknown_project_returns_404(self):
        with patch("app.api.production_brain.build_production_snapshot", return_value=None):
            with self.assertRaises(HTTPException) as raised:
                get_production_snapshot(999)
        self.assertEqual(raised.exception.status_code, 404)

    def test_panel_is_registered_without_replacing_legacy_app(self):
        root = Path(__file__).resolve().parents[1]
        app_source = (root / "app/static/app.js").read_text(encoding="utf-8")
        panel_source = (root / "app/static/production-brain-ui.js").read_text(encoding="utf-8")
        index_source = (root / "app/templates/index.html").read_text(encoding="utf-8")

        self.assertIn("async function openShot", app_source)
        self.assertIn("async function loadAssets", app_source)
        self.assertIn('loaders["production-brain"] = loadProductionBrain;', panel_source)
        self.assertIn('data-tab="production-brain"', index_source)
        self.assertIn('/static/production-brain-ui.js', index_source)


if __name__ == "__main__":
    unittest.main()
