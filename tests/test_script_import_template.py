from pathlib import Path
import unittest


class ScriptImportTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = Path("app/templates/script_import.html").read_text(encoding="utf-8")

    def test_uses_bounded_resumable_import_endpoints(self):
        self.assertIn("/api/import-runs/process-next", self.template)
        self.assertIn("/api/import-runs/persist", self.template)
        self.assertNotIn("/api/scenes/import-script", self.template)

    def test_does_not_offer_destructive_scene_replacement(self):
        self.assertNotIn('id="replace"', self.template)
        self.assertIn("אינו מוחק או מחליף סצנות קיימות", self.template)

    def test_retry_continues_from_saved_chunk_state(self):
        self.assertIn("next_chunk_index:state.nextChunkIndex", self.template)
        self.assertIn("scenes:state.scenes", self.template)
        self.assertIn("המשך מהנקודה האחרונה", self.template)


if __name__ == "__main__":
    unittest.main()
