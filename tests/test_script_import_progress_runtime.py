import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "script_import.html"


class ScriptImportProgressRuntimeTests(unittest.TestCase):
    def run_case(self, case):
        javascript = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const source = fs.readFileSync({json.dumps(str(TEMPLATE))}, 'utf8');
            const script = source.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
            const start = script.indexOf('function escapeHtml');
            const end = script.indexOf('async function runImport');
            const helpers = script.slice(start, end);
            const context = {{ console }};
            vm.createContext(context);
            vm.runInContext(helpers, context);
            const result = ({case})(context);
            console.log(JSON.stringify(result));
            """
        )
        completed = subprocess.run(
            ["node", "-e", javascript],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_backend_progress_wins_over_stale_local_counts(self):
        result = self.run_case(
            """(context) => context.resolvedFailureProgress(
                {stage:'shot-map', scenesCreated:5, shotsCreated:2, sceneIndex:1, sceneCount:5},
                {progress:{failed_stage:'shot_maps', scenes_created:5, shots_created:11,
                  failed_scene_number:3, completed_stages:['breakdown']}}
            )"""
        )
        self.assertEqual(result["stage"], "shot_maps")
        self.assertEqual(result["scenesCreated"], 5)
        self.assertEqual(result["shotsCreated"], 11)
        self.assertEqual(result["failedSceneNumber"], 3)
        self.assertEqual(result["completedStages"], ["breakdown"])

    def test_partial_success_summary_uses_server_counts_and_safe_retry_message(self):
        html = self.run_case(
            """(context) => context.partialFailureSummary(
                {stage:'shot-map', scenesCreated:0, shotsCreated:0, sceneIndex:0, sceneCount:5},
                {message:'Generation temporarily unavailable', retryable:true,
                 progress:{failed_stage:'shot_maps', scenes_created:5, shots_created:11,
                   failed_scene_number:3, completed_stages:['breakdown']}}
            )"""
        )
        self.assertIn("5 סצנות נשמרו", html)
        self.assertIn("11 שוטים נשמרו", html)
        self.assertIn("סצנה 3", html)
        self.assertIn("ניתן לנסות שוב", html)
        self.assertNotIn("[object Object]", html)

    def test_non_retryable_failure_does_not_offer_retry(self):
        html = self.run_case(
            """(context) => context.partialFailureSummary(
                {stage:'breakdown', scenesCreated:0, shotsCreated:0, sceneIndex:0, sceneCount:0},
                {message:'Invalid screenplay', retryable:false}
            )"""
        )
        self.assertIn("לא נשמרו נתונים חדשים", html)
        self.assertNotIn("ניתן לנסות שוב", html)

    def test_error_message_is_html_escaped(self):
        html = self.run_case(
            """(context) => context.partialFailureSummary(
                {stage:'breakdown', scenesCreated:0, shotsCreated:0, sceneIndex:0, sceneCount:0},
                {message:'<img src=x onerror=alert(1)>', retryable:false}
            )"""
        )
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)


if __name__ == "__main__":
    unittest.main()
