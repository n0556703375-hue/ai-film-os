"""Coverage for app.static.app.js's api() helper on a raw network failure.

safe-api-response.js (app/static/safe-api-response.js) only ever sees a
response it can safely re-read — it has no way to intercept fetch() itself
rejecting (server unreachable, connection reset, a cold-starting deploy).
Left unhandled, that raw browser TypeError ("Failed to fetch") leaked
straight into the otherwise all-Hebrew UI, found via a real production
error dialog showing the English message verbatim.
"""

import json
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app" / "static" / "app.js"


class AppJsNetworkErrorTests(unittest.TestCase):
    def test_network_failure_raises_a_friendly_hebrew_message_not_the_raw_error(self):
        script = textwrap.dedent(
            f"""
            const vm = require("vm");
            const fs = require("fs");
            const source = fs.readFileSync({json.dumps(str(SOURCE))}, "utf-8");
            const fakeElement = {{ innerHTML: "", style: {{}}, appendChild() {{}}, querySelectorAll: () => [] }};
            const context = vm.createContext({{
                document: {{
                    getElementById: () => fakeElement,
                    createElement: () => ({{ style: {{}} }}),
                    querySelectorAll: () => [],
                }},
                window: undefined,
                localStorage: {{ getItem: () => null, setItem: () => {{}} }},
                fetch: () => Promise.reject(new TypeError("Failed to fetch")),
                console,
            }});
            vm.runInContext(source, context);
            vm.runInContext("api('/api/projects')", context)
              .then(() => {{ console.log(JSON.stringify({{ resolved: true }})); }})
              .catch((error) => {{ console.log(JSON.stringify({{ message: error.message }})); }});
            """
        )
        completed = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertNotIn("resolved", result)
        self.assertNotIn("Failed to fetch", result["message"])
        self.assertEqual(result["message"], "לא ניתן להגיע לשרת. בדקי את החיבור ונסי שוב.")

    def test_a_real_backend_error_detail_still_surfaces_unchanged(self):
        script = textwrap.dedent(
            f"""
            const vm = require("vm");
            const fs = require("fs");
            const source = fs.readFileSync({json.dumps(str(SOURCE))}, "utf-8");
            const fakeElement = {{ innerHTML: "", style: {{}}, appendChild() {{}}, querySelectorAll: () => [] }};
            const context = vm.createContext({{
                document: {{
                    getElementById: () => fakeElement,
                    createElement: () => ({{ style: {{}} }}),
                    querySelectorAll: () => [],
                }},
                window: undefined,
                localStorage: {{ getItem: () => null, setItem: () => {{}} }},
                fetch: () => Promise.resolve({{
                    ok: false, status: 409,
                    json: async () => ({{ detail: "כבר קיימים שוטים בסצנה." }}),
                }}),
                console,
            }});
            vm.runInContext(source, context);
            vm.runInContext("api('/api/scenes/1')", context)
              .then(() => {{ console.log(JSON.stringify({{ resolved: true }})); }})
              .catch((error) => {{ console.log(JSON.stringify({{ message: error.message }})); }});
            """
        )
        completed = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(result["message"], "כבר קיימים שוטים בסצנה.")


if __name__ == "__main__":
    unittest.main()
