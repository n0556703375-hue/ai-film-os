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

    def test_upload_chunk_size_recovers_after_a_block_clears(self):
        """A block-page response (non-JSON body, HTTP 200 — the exact shape a
        network content filter returns) must shrink the chunk size, and once
        requests start succeeding again the size must climb back toward the
        starting size instead of staying pinned at the floor for the rest of
        the upload. Runs the real safe_api.js parser alongside
        screenplay-import-ui.js so the retry decision (which error codes
        count as "blocked") is exercised end to end, not re-implemented here.
        """
        safe_api_path = ROOT / "app" / "static" / "safe_api.js"
        script = textwrap.dedent(
            f"""
            const fs = require("fs");
            const vm = require("vm");
            const uiSource = fs.readFileSync({json.dumps(str(SOURCE))}, "utf-8");
            const safeApiSource = fs.readFileSync({json.dumps(str(safe_api_path))}, "utf-8");

            const requestSizes = [];
            let callCount = 0;
            const BLOCKED_UNTIL = 6; // enough calls to shrink 1000 -> the 20-char floor

            function fetchMock(url, options) {{
              const body = JSON.parse(options.body);
              requestSizes.push(body.chunk_text.length);
              callCount += 1;
              if (callCount <= BLOCKED_UNTIL) {{
                return Promise.resolve({{
                  ok: true, status: 200,
                  headers: {{ get: () => "text/html" }},
                  text: async () => "<html>blocked</html>",
                }});
              }}
              const responseBody = body.is_final
                ? {{ completed: true, screenplay_text: "irrelevant", import_run_id: 1 }}
                : {{ completed: false, upload_id: body.upload_id, received_chars: 0 }};
              return Promise.resolve({{
                ok: true, status: 200,
                headers: {{ get: () => "application/json" }},
                text: async () => JSON.stringify(responseBody),
              }});
            }}

            const fakeElement = {{ innerHTML: "", style: {{}}, appendChild() {{}} }};
            const context = vm.createContext({{
              fetch: fetchMock,
              setTimeout,
              console,
              document: {{
                getElementById: () => fakeElement,
                createElement: () => ({{ style: {{}} }}),
              }},
              window: undefined,
              localStorage: {{ getItem: () => null, setItem: () => {{}} }},
            }});
            vm.runInContext(safeApiSource, context);
            vm.runInContext(uiSource, context);

            const text = "x".repeat(60000);
            const runner = vm.runInContext(
              "(text, opts) => uploadScreenplayInChunks(text, opts)", context,
            );
            runner(text, {{
              projectId: 1, sourceType: "paste", sourceFilename: "", importRunId: null, force: false,
              onProgress: () => {{}},
            }}).then(() => {{
              console.log(JSON.stringify(requestSizes));
            }}).catch((error) => {{
              console.error("UPLOAD_FAILED: " + error.message + " code=" + error.code);
              process.exit(1);
            }});
            """
        )
        completed = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        sizes = json.loads(completed.stdout.strip())

        # Halves on every blocked attempt, down to the 20-char floor.
        self.assertEqual(sizes[:6], [1000, 500, 250, 125, 62, 31])

        recovered = sizes[6:]
        # Recovers at the floor first — no jumping straight back to full size.
        self.assertEqual(recovered[:5], [20, 20, 20, 20, 20])
        # But it does climb back to the starting size once the block has
        # cleared, rather than staying at 20 chars/request for the rest of
        # a full-length screenplay.
        self.assertIn(1000, recovered)


if __name__ == "__main__":
    unittest.main()
