from pathlib import Path
import unittest


class BatchFinalizeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("app/static/shot-filters-ui.js").read_text(encoding="utf-8")

    def test_preview_is_required_before_execution(self):
        self.assertIn('api("/api/shots/batch/finalize-preview"', self.source)
        self.assertIn("pendingBatchFinalizeIds = [...selectedShotIds]", self.source)
        self.assertIn("item.eligible && !item.already_final", self.source)

    def test_execution_requires_explicit_confirmation(self):
        self.assertIn('api("/api/shots/batch/finalize"', self.source)
        self.assertIn("confirmed: true", self.source)
        self.assertIn("if (!confirm(", self.source)

    def test_blockers_and_partial_results_are_visible(self):
        self.assertIn("item.reasons.map(esc)", self.source)
        self.assertIn("result.finalized", self.source)
        self.assertIn("result.blocked", self.source)
        self.assertIn("result.already_final", self.source)


if __name__ == "__main__":
    unittest.main()
