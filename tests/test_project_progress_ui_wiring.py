import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "index.html"
MODULE = ROOT / "app" / "static" / "project-progress-ui.js"


class ProjectProgressUiWiringTests(unittest.TestCase):
    def test_formatter_and_ui_wiring_load_in_safe_order(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        formatter = '<script src="/static/project-progress.js"></script>'
        app = '<script src="/static/app.js"></script>'
        wiring = '<script src="/static/project-progress-ui.js"></script>'
        self.assertIn('id="projectProgressSummary"', source)
        self.assertLess(source.index(formatter), source.index(app))
        self.assertLess(source.index(app), source.index(wiring))

    def test_active_project_selection_prefers_selected_id_and_falls_back(self):
        script = textwrap.dedent(
            f"""
            global.document = {{ addEventListener: () => {{}} }};
            global.window = {{}};
            const {{ activeProject }} = require({json.dumps(str(MODULE))});
            const projects = [{{id: 1, name: 'A'}}, {{id: 2, name: 'B'}}];
            console.log(JSON.stringify({{
              selected: activeProject(projects, '2').id,
              fallback: activeProject(projects, 'missing').id,
              empty: activeProject([], '1')
            }}));
            """
        )
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result, {"selected": 2, "fallback": 1, "empty": None})


if __name__ == "__main__":
    unittest.main()
