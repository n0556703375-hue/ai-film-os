import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "script_import.html"


class ScriptImportPartialProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_import_tracks_persisted_counts(self):
        self.assertIn("const progress={scenesCreated:0,shotsCreated:0}", self.html)
        self.assertIn("progress.scenesCreated=Number(data.scenes_created||scenes.length||0)", self.html)
        self.assertIn("progress.shotsCreated+=(created.shots||[]).length", self.html)

    def test_each_resumable_stage_saves_retry_state_before_the_request(self):
        self.assertIn("retryState={type:'breakdown',state}", self.html)
        self.assertIn("retryState={type:'persist',state,progress}", self.html)
        self.assertIn("retryState={type:'shot-map',scenes,index,progress}", self.html)

    def test_failure_summary_is_non_destructive_and_only_offers_saved_retry(self):
        self.assertIn("function failureSummary(error)", self.html)
        self.assertIn("error&&error.retryable&&retryState", self.html)
        self.assertIn("לא בוצעה החלפה של נתונים קיימים", self.html)
        self.assertNotIn("הסצנות שכבר נוצרו נשמרו", self.html)

    def test_retry_resumes_the_saved_stage_without_restarting_completed_work(self):
        self.assertIn("if(saved.type==='breakdown')", self.html)
        self.assertIn("else if(saved.type==='persist')", self.html)
        self.assertIn("await createShotMaps(saved.scenes,saved.index,saved.progress)", self.html)

    def test_shot_map_retry_never_replaces_existing_shots(self):
        self.assertIn("body:JSON.stringify({shot_count:count,replace_existing:false})", self.html)


if __name__ == "__main__":
    unittest.main()
