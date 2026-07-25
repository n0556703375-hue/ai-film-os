import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "app" / "static" / "character-reference-gallery-ui.js"


@unittest.skipUnless(shutil.which("node"), "Node.js is required for UI regression tests")
class CharacterReferenceGalleryUiTests(unittest.TestCase):
    def run_node(self, expression: str):
        harness = f"""
const fs = require("fs");
global.window = {{ openAsset: async () => {{}} }};
global.esc = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({{
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '\"': "&quot;", "'": "&#39;"
}})[char]);
global.api = async () => ({{ groups: {{}} }});
global.$ = () => null;
global.console = {{ warn: () => {{}} }};
eval(fs.readFileSync({json.dumps(str(SCRIPT))}, "utf8"));
const result = {expression};
process.stdout.write(JSON.stringify(result));
"""
        completed = subprocess.run(
            ["node", "-e", harness],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_flattens_view_and_expression_groups(self):
        result = self.run_node(
            "window.characterReferenceGallery.flattenGroups({front:{neutral:[{id:1}],focused:[{id:2}]}})"
        )

        self.assertEqual(
            result,
            [
                {"viewType": "front", "expression": "neutral", "references": [{"id": 1}]},
                {"viewType": "front", "expression": "focused", "references": [{"id": 2}]},
            ],
        )

    def test_renders_only_grouped_approved_reference_payload(self):
        html = self.run_node(
            "window.characterReferenceGallery.renderReferenceGallery(12,{profile:{neutral:[{id:7,model:'nano'}]}})"
        )

        self.assertIn("profile · neutral", html)
        self.assertIn("/api/assets/12/references/7/image", html)
        self.assertIn("nano", html)

    def test_empty_groups_render_nothing(self):
        html = self.run_node(
            "window.characterReferenceGallery.renderReferenceGallery(12,{})"
        )

        self.assertEqual(html, "")


if __name__ == "__main__":
    unittest.main()
