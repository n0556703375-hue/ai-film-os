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
            rf"""
            const fs = require('fs');
            const vm = require('vm');
            const source = fs.readFileSync({json.dumps(str(TEMPLATE))}, 'utf8');
            const script = source.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
            const start = script.indexOf('let retryState=null;');
            const end = script.indexOf('async function runImport');
            const helpers = script.slice(start, end);
            const context = {{ console }};
            vm.createContext(context);
            vm.runInContext(helpers, context);
            const result = vm.runInContext({json.dumps(case)}, context);
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

    def test_completed_summary_uses_current_progress_counts(self):
        html = self.run_case(
            "completedSummary({scenesCreated:5, shotsCreated:11})"
        )
        self.assertIn("5</b> סצנות נשמרו", html)
        self.assertIn("11</b> שוטים נוצרו", html)

    def test_retryable_failure_with_saved_state_offers_resume(self):
        html = self.run_case(
            "retryState={type:'breakdown',state:{}}; "
            "failureSummary({message:'Generation temporarily unavailable',retryable:true})"
        )
        self.assertIn("Generation temporarily unavailable", html)
        self.assertIn('id="retryStageButton"', html)
        self.assertIn("המשך מהנקודה האחרונה", html)

    def test_non_retryable_failure_does_not_offer_retry(self):
        html = self.run_case(
            "retryState={type:'breakdown',state:{}}; "
            "failureSummary({message:'Invalid screenplay',retryable:false})"
        )
        self.assertIn("Invalid screenplay", html)
        self.assertNotIn('id="retryStageButton"', html)
        self.assertIn("לא בוצעה החלפה של נתונים קיימים", html)

    def test_error_message_is_html_escaped(self):
        html = self.run_case(
            "retryState=null; "
            "failureSummary({message:'<img src=x onerror=alert(1)>',retryable:false})"
        )
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)


if __name__ == "__main__":
    unittest.main()
