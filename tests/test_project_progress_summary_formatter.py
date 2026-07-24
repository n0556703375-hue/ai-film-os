import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "app" / "static" / "project-progress.js"


class ProjectProgressSummaryFormatterTests(unittest.TestCase):
    def run_case(self, expression):
        script = textwrap.dedent(
            f"""
            const {{ formatProjectProgressSummary, normalizedCount }} = require({json.dumps(str(MODULE))});
            const result = {expression};
            console.log(JSON.stringify(result));
            """
        )
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_formats_project_totals_and_status_counts(self):
        result = self.run_case(
            "formatProjectProgressSummary({scenes_total:4, shots_total:9, assets_total:3, "
            "shot_status_totals:{'טיוטת תמונה':3, 'פרומפט מוכן':5, not_started:1}})"
        )
        self.assertIn("4 סצנות", result)
        self.assertIn("9 שוטים", result)
        self.assertIn("3 נכסים", result)
        self.assertIn("טיוטת תמונה: 3", result)
        self.assertIn("פרומפט מוכן: 5", result)
        self.assertIn("not_started: 1", result)

    def test_empty_project_has_stable_compact_summary(self):
        result = self.run_case("formatProjectProgressSummary({})")
        self.assertEqual(result, "0 סצנות · 0 שוטים · 0 נכסים")

    def test_invalid_or_negative_counts_are_normalized_without_mutation(self):
        result = self.run_case(
            "({summary: formatProjectProgressSummary({scenes_total:-2, shots_total:'bad', "
            "assets_total:1.9, shot_status_totals:{draft:-1, approved:'2'}}), "
            "negative: normalizedCount(-5), decimal: normalizedCount(3.8)})"
        )
        self.assertEqual(result["negative"], 0)
        self.assertEqual(result["decimal"], 3)
        self.assertIn("0 סצנות", result["summary"])
        self.assertIn("0 שוטים", result["summary"])
        self.assertIn("1 נכסים", result["summary"])
        self.assertIn("approved: 2", result["summary"])
        self.assertNotIn("draft", result["summary"])


if __name__ == "__main__":
    unittest.main()
