import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "app" / "static" / "safe_api.js"


class SafeApiResponseParserTests(unittest.TestCase):
    def run_case(self, javascript):
        completed = subprocess.run(
            ["node", "-e", javascript],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_valid_json_success(self):
        result = self.run_case(textwrap.dedent(f"""
            const {{ parseApiResponse }} = require({json.dumps(str(MODULE))});
            const response = {{
              ok: true,
              status: 200,
              headers: {{ get: () => 'application/json; charset=utf-8' }},
              text: async () => '{{"scenes":5}}'
            }};
            parseApiResponse(response).then(value => console.log(JSON.stringify(value)));
        """))
        self.assertEqual(result, {"scenes": 5})

    def test_json_error_preserves_safe_detail(self):
        result = self.run_case(textwrap.dedent(f"""
            const {{ parseApiResponse }} = require({json.dumps(str(MODULE))});
            const response = {{
              ok: false,
              status: 500,
              headers: {{ get: () => 'application/json' }},
              text: async () => '{{"detail":"Import stage failed","code":"import_failed"}}'
            }};
            parseApiResponse(response).catch(error => console.log(JSON.stringify({{
              message: error.message, status: error.status, code: error.code, retryable: error.retryable
            }})));
        """))
        self.assertEqual(result["message"], "Import stage failed")
        self.assertEqual(result["status"], 500)
        self.assertEqual(result["code"], "import_failed")
        self.assertFalse(result["retryable"])

    def test_structured_import_error_preserves_allowlisted_progress(self):
        result = self.run_case(textwrap.dedent(f"""
            const {{ parseApiResponse }} = require({json.dumps(str(MODULE))});
            const response = {{
              ok: false,
              status: 502,
              headers: {{ get: () => 'application/json' }},
              text: async () => JSON.stringify({{
                detail: {{
                  message: 'Import paused safely',
                  code: 'import_upstream_failure',
                  retryable: true,
                  completed_stages: ['screenplay_breakdown', 'scene_persistence'],
                  failed_stage: 'shot_map_generation',
                  scenes_created: 5,
                  shots_created: 12,
                  failed_scene_id: 44,
                  failed_scene_number: 3,
                  provider_secret: 'must-not-leak'
                }}
              }})
            }};
            parseApiResponse(response).catch(error => console.log(JSON.stringify({{
              message: error.message,
              code: error.code,
              retryable: error.retryable,
              progress: error.progress
            }})));
        """))
        self.assertEqual(result["message"], "Import paused safely")
        self.assertEqual(result["code"], "import_upstream_failure")
        self.assertTrue(result["retryable"])
        self.assertEqual(result["progress"]["scenes_created"], 5)
        self.assertEqual(result["progress"]["shots_created"], 12)
        self.assertEqual(result["progress"]["failed_scene_number"], 3)
        self.assertNotIn("provider_secret", result["progress"])

    def test_html_gateway_error_is_redacted_and_retryable(self):
        result = self.run_case(textwrap.dedent(f"""
            const {{ parseApiResponse }} = require({json.dumps(str(MODULE))});
            const response = {{
              ok: false,
              status: 502,
              headers: {{ get: () => 'text/html' }},
              text: async () => '<html><body>upstream secret detail</body></html>'
            }};
            parseApiResponse(response).catch(error => console.log(JSON.stringify({{
              message: error.message, status: error.status, code: error.code, retryable: error.retryable
            }})));
        """))
        self.assertEqual(result["code"], "non_json_response")
        self.assertTrue(result["retryable"])
        self.assertNotIn("upstream", result["message"])

    def test_empty_error_response_has_stable_code(self):
        result = self.run_case(textwrap.dedent(f"""
            const {{ parseApiResponse }} = require({json.dumps(str(MODULE))});
            const response = {{
              ok: false,
              status: 504,
              headers: {{ get: () => '' }},
              text: async () => '   '
            }};
            parseApiResponse(response).catch(error => console.log(JSON.stringify({{
              code: error.code, retryable: error.retryable
            }})));
        """))
        self.assertEqual(result, {"code": "empty_response", "retryable": True})


if __name__ == "__main__":
    unittest.main()
