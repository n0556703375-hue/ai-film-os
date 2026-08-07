"""Structural checks on the new two-stage script_import.html shell.

The page used to embed its whole chunked-resumable import flow as inline
JS (tested by the now-deleted test_script_import_*_ui.py / resilience /
retry test files). It has been replaced by a parse -> preview -> compare
-> explicit-approve flow against /api/screenplay-imports, with the JS
moved out to app/static/screenplay-import-ui.js — see that file and
tests/test_screenplay_import_ui_js.py for the flow's own tests.
"""

from pathlib import Path
import unittest


class ScriptImportTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = Path("app/templates/script_import.html").read_text(encoding="utf-8")

    def test_loads_safe_parser_before_the_import_ui_script(self):
        safe_parser_index = self.template.index('<script src="/static/safe_api.js"></script>')
        ui_script_index = self.template.index('<script src="/static/screenplay-import-ui.js"></script>')
        self.assertLess(safe_parser_index, ui_script_index)

    def test_does_not_reference_the_old_chunked_resumable_endpoints(self):
        self.assertNotIn("/api/import-runs/process-next", self.template)
        self.assertNotIn("/api/import-runs/persist", self.template)
        self.assertNotIn("/api/scenes/import-script", self.template)

    def test_has_no_inline_script_logic(self):
        # All behavior lives in screenplay-import-ui.js now — the template
        # is just the page shell, so there is nothing here to drift out of
        # sync with the (separately tested) JS.
        self.assertNotIn("function ", self.template)


if __name__ == "__main__":
    unittest.main()
