import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "script_import.html"


class ScriptImportBackendProgressUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TEMPLATE.read_text(encoding="utf-8")

    def test_backend_progress_overrides_local_persisted_counts(self):
        self.assertIn("const backend=error&&error.progress", self.source)
        self.assertIn("backend.scenes_created??localProgress.scenesCreated", self.source)
        self.assertIn("backend.shots_created??localProgress.shotsCreated", self.source)

    def test_backend_failed_scene_number_is_rendered(self):
        self.assertIn("failedSceneNumber:backend.failed_scene_number||null", self.source)
        self.assertIn("יצירת מפת השוטים לסצנה ${progress.failedSceneNumber}", self.source)

    def test_non_destructive_shot_map_generation_is_preserved(self):
        self.assertIn("replace_existing:false", self.source)

    def test_raw_backend_fields_are_not_rendered_directly(self):
        self.assertNotIn("JSON.stringify(error.progress)", self.source)
        self.assertNotIn("innerHTML=error.progress", self.source)


if __name__ == "__main__":
    unittest.main()
