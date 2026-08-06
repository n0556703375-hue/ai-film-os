from pathlib import Path
import unittest


WORKFLOW_PATH = Path(".github/workflows/production-screenplay-smoke.yml")


class ProductionScreenplaySmokeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_workflow_is_manual_only(self) -> None:
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertNotIn("pull_request:", self.workflow)
        self.assertNotIn("push:", self.workflow)
        self.assertNotIn("schedule:", self.workflow)

    def test_requires_explicit_confirmation(self) -> None:
        self.assertIn("RUN_PRODUCTION_IMPORT_SMOKE", self.workflow)
        self.assertIn("inputs.confirmation == 'RUN_PRODUCTION_IMPORT_SMOKE'", self.workflow)

    def test_targets_only_the_known_render_service(self) -> None:
        self.assertIn("--base-url https://ai-film-os.onrender.com", self.workflow)
        self.assertNotIn("base_url:", self.workflow)

    def test_screenplay_comes_from_a_secret_and_is_removed(self) -> None:
        self.assertIn("secrets.PRODUCTION_SMOKE_SCREENPLAY_B64", self.workflow)
        self.assertIn("umask 077", self.workflow)
        self.assertIn("rm -f production-smoke-screenplay.txt", self.workflow)
        self.assertNotIn("production-smoke-screenplay.txt\n          retention-days", self.workflow)

    def test_screenplay_secret_supports_the_split_fallback(self) -> None:
        self.assertIn("secrets.PRODUCTION_SMOKE_SCREENPLAY_B64_PART1", self.workflow)
        self.assertIn("secrets.PRODUCTION_SMOKE_SCREENPLAY_B64_PART2", self.workflow)
        self.assertIn(
            "python -m scripts.materialize_production_screenplay_secret", self.workflow
        )
        # The reconstruction/decode logic now lives in a real, unit-tested
        # module (tests/test_materialize_production_screenplay_secret.py)
        # instead of an inline heredoc that could only be checked by string
        # matching the workflow file.
        self.assertNotIn("base64.b64decode", self.workflow)

    def test_import_requires_existing_safe_script_flag(self) -> None:
        self.assertIn("python -m scripts.deployment_import_idempotency", self.workflow)
        self.assertNotIn("python scripts/deployment_import_idempotency.py", self.workflow)
        self.assertIn("--execute-import", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)

    def test_preflight_rejects_invalid_project_and_checks_health_first(self) -> None:
        self.assertIn("project_id must be a positive existing project ID", self.workflow)
        self.assertIn("https://ai-film-os.onrender.com/health", self.workflow)
        self.assertIn("--retry-all-errors", self.workflow)
        self.assertLess(
            self.workflow.index("Validate project input and deployed health"),
            self.workflow.index("Materialize screenplay without logging it"),
        )


if __name__ == "__main__":
    unittest.main()
