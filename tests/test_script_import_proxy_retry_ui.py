from pathlib import Path
import unittest


TEMPLATE = Path("app/templates/script_import.html")


class ScriptImportProxyRetryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_shared_safe_parser_handles_import_responses(self):
        self.assertIn('<script src="/static/safe_api.js"></script>', self.html)
        self.assertIn("return parseApiResponse(response)", self.html)
        self.assertIn("code:'network_error',retryable:true", self.html)

    def test_retry_is_scoped_to_current_resumable_import_stages(self):
        self.assertIn("retryState={type:'breakdown',state}", self.html)
        self.assertIn("retryState={type:'persist',state,progress}", self.html)
        self.assertIn("retryState={type:'shot-map',scenes,index,progress}", self.html)
        self.assertIn("'/api/import-runs/process-next'", self.html)
        self.assertIn("'/api/import-runs/persist'", self.html)
        self.assertNotIn("/api/scenes/import-script", self.html)

    def test_failure_summary_only_offers_retry_for_retryable_saved_state(self):
        self.assertIn("error&&error.retryable&&retryState", self.html)
        self.assertIn('id="retryStageButton"', self.html)
        self.assertIn("onclick=\"retryFailedStage()\"", self.html)

    def test_retry_resumes_saved_stage_without_replacing_existing_data(self):
        self.assertIn("if(saved.type==='breakdown')", self.html)
        self.assertIn("else if(saved.type==='persist')", self.html)
        self.assertIn("await createShotMaps(saved.scenes,saved.index,saved.progress)", self.html)
        self.assertIn("replace_existing:false", self.html)


if __name__ == "__main__":
    unittest.main()
