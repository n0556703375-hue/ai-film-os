import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "app" / "static" / "identity-drift-operator-panel.js"


@unittest.skipUnless(shutil.which("node"), "Node.js is required for UI regression tests")
class IdentityDriftOperatorPanelTests(unittest.TestCase):
    def run_node(self, expression: str):
        script = f"""
const panel = require({json.dumps(str(MODULE))});
const result = {expression};
process.stdout.write(JSON.stringify(result));
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_blocked_and_error_results_are_ordered_before_passed(self):
        result = self.run_node(
            "panel.orderCompletedAssessments(["
            "{shot_id:1,identity_drift:{status:'passed',completed_at:'2026-07-26T09:00:00Z'}},"
            "{shot_id:2,identity_drift:{status:'blocked',completed_at:'2026-07-26T08:00:00Z'}},"
            "{shot_id:3,identity_drift:{status:'error',completed_at:'2026-07-26T10:00:00Z'}}"
            "]).map(item=>item.shot_id)"
        )

        self.assertEqual(result, [2, 3, 1])

    def test_renderer_shows_safe_operator_fields_and_escapes_text(self):
        html = self.run_node(
            "panel.renderIdentityDriftOperatorPanel({items:[{shot_id:12,identity_drift:{"
            "status:'blocked',score:0.91,attempt:2,worker_id:'worker-1',"
            "completed_at:'2026-07-26T09:00:00Z',reasons:['<drift>']}}]})"
        )

        self.assertIn("שוט 12", html)
        self.assertIn("91%", html)
        self.assertIn("worker-1", html)
        self.assertIn("&lt;drift&gt;", html)
        self.assertNotIn("<drift>", html)

    def test_empty_payload_has_stable_empty_state(self):
        html = self.run_node("panel.renderIdentityDriftOperatorPanel({items:[]})")

        self.assertIn("עדיין אין בדיקות שהושלמו", html)
        self.assertIn("data-identity-drift-panel", html)


if __name__ == "__main__":
    unittest.main()
