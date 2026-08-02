from pathlib import Path
import unittest


TEMPLATE = Path("app/templates/script_import.html")


class ScriptImportRetryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_retries_only_the_saved_failed_stage(self):
        self.assertIn("async function retryFailedStage()", self.html)
        self.assertIn("if(saved.type==='breakdown')", self.html)
        self.assertIn("else if(saved.type==='persist')", self.html)
        self.assertIn("await createShotMaps(saved.scenes,saved.index,saved.progress)", self.html)

    def test_existing_shot_maps_are_skipped_without_replacement(self):
        self.assertIn("const current=await json(`/api/scenes/${scene.id}`)", self.html)
        self.assertIn("if((current.shots||[]).length)", self.html)
        self.assertIn("continue", self.html)
        self.assertIn("replace_existing:false", self.html)

    def test_breakdown_retry_resumes_saved_chunk_state(self):
        self.assertIn("retryState={type:'breakdown',state}", self.html)
        self.assertIn("await continueImport(saved.state,{scenesCreated:0,shotsCreated:0})", self.html)
        self.assertIn("next_chunk_index:state.nextChunkIndex", self.html)

    def test_retry_button_requires_retryable_error_and_saved_state(self):
        self.assertIn("error&&error.retryable&&retryState", self.html)
        self.assertIn('id="retryStageButton"', self.html)
        self.assertIn("onclick=\"retryFailedStage()\"", self.html)


if __name__ == "__main__":
    unittest.main()
