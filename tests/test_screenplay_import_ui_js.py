"""Unit tests for the pure rendering helpers in
app/static/screenplay-import-ui.js, run under Node's vm module (no DOM
needed for these — they're plain string builders). The stateful/DOM-driven
parts of the flow (parse -> preview -> diff -> approve, edit/re-parse,
protected-removal blocking) were verified end to end against a running
server with Playwright during development; this file guards the pure
functions most likely to silently regress, especially HTML escaping.
"""

import json
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app" / "static" / "screenplay-import-ui.js"


class ScreenplayImportUiJsTests(unittest.TestCase):
    def run_js(self, expression: str):
        script = textwrap.dedent(
            f"""
            const vm = require("vm");
            const fs = require("fs");
            const source = fs.readFileSync({json.dumps(str(SOURCE))}, "utf-8");
            const fakeElement = {{ innerHTML: "", style: {{}}, appendChild() {{}} }};
            const context = vm.createContext({{
                document: {{
                    getElementById: () => fakeElement,
                    createElement: () => ({{ style: {{}} }}),
                }},
                window: undefined,
                localStorage: {{ getItem: () => null, setItem: () => {{}} }},
                fetch: () => Promise.resolve({{ ok: true, status: 200,
                    headers: {{ get: () => "application/json" }}, text: async () => "{{}}" }}),
                FilmOsApiError: class FilmOsApiError extends Error {{
                    constructor(message, opts) {{ super(message); Object.assign(this, opts); }}
                }},
                parseApiResponse: async () => ({{}}),
                console,
            }});
            vm.runInContext(source, context);
            const result = vm.runInContext({json.dumps(expression)}, context);
            console.log(JSON.stringify(result));
            """
        )
        completed = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_escape_html_neutralizes_script_injection(self):
        result = self.run_js('escapeHtml(\'<script>alert(1)</script>&"\\\'\')')
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)
        self.assertIn("&amp;", result)
        self.assertIn("&quot;", result)
        self.assertIn("&#39;", result)

    def test_block_label_escapes_character_name_and_dialogue_text(self):
        block = {
            "block_type": "dialogue",
            "character_name": "<b>JOHN</b>",
            "raw_text": "<img src=x onerror=alert(1)>",
            "parenthetical": "",
        }
        result = self.run_js(f"blockLabel({json.dumps(block)})")
        self.assertNotIn("<img", result)
        self.assertNotIn("<b>JOHN</b>", result)
        self.assertIn("&lt;b&gt;JOHN&lt;/b&gt;", result)

    def test_block_label_action_block_shows_type_badge(self):
        block = {"block_type": "action", "raw_text": "John walks in.", "character_name": "", "parenthetical": ""}
        result = self.run_js(f"blockLabel({json.dumps(block)})")
        self.assertIn("פעולה", result)
        self.assertIn("John walks in.", result)

    def test_scene_card_includes_heading_and_participants(self):
        scene = {
            "scene_number": 1, "original_heading": "1. INT. HOUSE - DAY",
            "int_ext": "INT", "location": "HOUSE", "time_of_day": "DAY",
            "participants": ["JOHN", "MARY"], "blocks": [],
        }
        result = self.run_js(f"sceneCard({json.dumps(scene)})")
        self.assertIn("סצנה 1", result)
        self.assertIn("INT. HOUSE - DAY", result)
        self.assertIn("JOHN, MARY", result)

    def test_entity_card_lists_aliases_excluding_canonical_name(self):
        entity = {"canonical_name": "JOHN", "aliases": ["JOHN", "JOHNNY"], "first_appearance_scene_number": 2}
        result = self.run_js(f'entityCard({json.dumps(entity)}, "הופעה")')
        self.assertIn("JOHN", result)
        self.assertIn("JOHNNY", result)
        self.assertIn("סצנה 2", result)

    def test_diff_scene_row_escapes_heading(self):
        scene = {"scene_number": 3, "normalized_heading": "<i>INT. X</i>"}
        result = self.run_js(f"diffSceneRow({json.dumps(scene)}, 7)")
        self.assertIn("#7", result)
        self.assertNotIn("<i>INT. X</i>", result)
        self.assertIn("&lt;i&gt;", result)


if __name__ == "__main__":
    unittest.main()
