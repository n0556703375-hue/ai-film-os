from pathlib import Path
import unittest


TEMPLATE = Path("app/templates/script_import.html")


class ScriptImportRetryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_retries_only_the_failed_shot_map_stage(self):
        self.assertIn("async function retryFailedStage()", self.html)
        self.assertIn("await createShotMaps(state.scenes,state.index,state.progress)", self.html)
        self.assertIn("replace_existing:false", self.html)

    def test_does_not_retry_when_partial_shots_already_exist(self):
        self.assertIn("if((currentScene.shots||[]).length)", self.html)
        self.assertIn("לא בוצע ניסיון חוזר אוטומטי", self.html)

    def test_breakdown_retry_requires_no_persisted_scenes(self):
        self.assertIn("return progress.scenesCreated===0&&retryState&&retryState.type==='breakdown'", self.html)

    def test_retry_button_is_only_rendered_for_retryable_errors(self):
        self.assertIn("if(!error||!error.retryable)return false", self.html)
        self.assertIn("retryButton(progress,error)", self.html)


if __name__ == "__main__":
    unittest.main()
