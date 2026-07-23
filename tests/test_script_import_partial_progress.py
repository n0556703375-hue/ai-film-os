import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "script_import.html"


class ScriptImportPartialProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_import_tracks_persisted_counts(self):
        self.assertIn("scenesCreated:0", self.html)
        self.assertIn("shotsCreated:0", self.html)
        self.assertIn("progress.scenesCreated=", self.html)
        self.assertIn("progress.shotsCreated+=", self.html)

    def test_failure_reports_exact_stage(self):
        self.assertIn("function partialFailureSummary", self.html)
        self.assertIn("progress.stage==='shot-map'", self.html)
        self.assertIn("השלב שנכשל:", self.html)
        self.assertIn("progress.sceneIndex+1", self.html)

    def test_failure_does_not_claim_data_was_saved_before_breakdown_success(self):
        self.assertIn("לא נשמרו נתונים חדשים לפני הכשל.", self.html)
        self.assertNotIn("הסצנות שכבר נוצרו נשמרו", self.html)

    def test_retry_guidance_remains_retryable_only(self):
        self.assertIn("error&&error.retryable", self.html)

    def test_shot_map_retry_never_replaces_existing_shots(self):
        self.assertIn("body:JSON.stringify({shot_count:count,replace_existing:false})", self.html)


if __name__ == "__main__":
    unittest.main()
