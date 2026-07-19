import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BatchShotStatusTests(unittest.TestCase):
    def test_batch_route_is_registered_before_dynamic_shot_routes(self):
        main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

        self.assertIn("shot_batches_router", main)
        self.assertLess(
            main.index("app.include_router(shot_batches_router)"),
            main.index("app.include_router(shots_router)"),
        )

    def test_batch_endpoint_requires_confirmation_and_project_scope(self):
        source = (ROOT / "app" / "api" / "shot_batches.py").read_text(encoding="utf-8")

        self.assertIn('@router.patch("/status")', source)
        self.assertIn("confirmed: bool = False", source)
        self.assertIn("request.project_id", source)
        self.assertIn("BEGIN IMMEDIATE", source)
        self.assertIn('Literal["מתוכנן", "פרומפט מוכן"]', source)
        self.assertNotIn("DELETE FROM", source)

    def test_prompt_ready_requires_an_existing_prompt(self):
        source = (ROOT / "app" / "api" / "shot_batches.py").read_text(encoding="utf-8")

        self.assertIn('request.status == "פרומפט מוכן"', source)
        self.assertIn('row["prompt"]', source)

    def test_ui_requires_selection_and_explicit_confirmation(self):
        source = (ROOT / "app" / "static" / "shot-filters-ui.js").read_text(encoding="utf-8")

        self.assertIn("selectedShotIds", source)
        self.assertIn("/api/shots/batch/status", source)
        self.assertIn("confirm(`לעדכן", source)
        self.assertIn("confirmed: true", source)
        self.assertIn('method: "PATCH"', source)
        self.assertNotIn('method: "DELETE"', source)


if __name__ == "__main__":
    unittest.main()
