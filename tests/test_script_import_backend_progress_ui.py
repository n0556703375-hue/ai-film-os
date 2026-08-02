import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "script_import.html"


class ScriptImportBackendProgressUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TEMPLATE.read_text(encoding="utf-8")

    def test_retry_state_preserves_progress_for_each_resumable_stage(self):
        self.assertIn("retryState={type:'breakdown',state}", self.source)
        self.assertIn("retryState={type:'persist',state,progress}", self.source)
        self.assertIn("retryState={type:'shot-map',scenes,index,progress}", self.source)
        self.assertIn("await continueImport(saved.state,{scenesCreated:0,shotsCreated:0})", self.source)
        self.assertIn("await createShotMaps(saved.scenes,saved.index,saved.progress)", self.source)

    def test_shot_map_progress_renders_current_scene_position(self):
        self.assertIn("`יוצרת מפת שוטים לסצנה ${index+1} מתוך ${scenes.length} · ${count} שוטים`", self.source)
        self.assertIn("progress.shotsCreated+=(created.shots||[]).length", self.source)

    def test_non_destructive_shot_map_generation_is_preserved(self):
        self.assertIn("replace_existing:false", self.source)

    def test_raw_backend_fields_are_not_rendered_directly(self):
        self.assertNotIn("JSON.stringify(error.progress)", self.source)
        self.assertNotIn("innerHTML=error.progress", self.source)


if __name__ == "__main__":
    unittest.main()
