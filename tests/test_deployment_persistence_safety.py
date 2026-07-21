import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentPersistenceSafetyTests(unittest.TestCase):
    def test_service_local_sqlite_is_not_split_across_render_services(self):
        config = (ROOT / "app" / "core" / "config.py").read_text(encoding="utf-8")
        render = (ROOT / "render.yaml").read_text(encoding="utf-8")

        uses_service_local_sqlite = "database_path = Path(" in config and "DATABASE_URL" not in config
        service_entries = [
            line for line in render.splitlines()
            if line.strip().startswith("- type:")
        ]

        if uses_service_local_sqlite:
            self.assertEqual(
                service_entries,
                ["  - type: web"],
                "Local SQLite must remain in a single Render service until shared persistence is implemented.",
            )
            self.assertNotIn("type: cron", render)
            self.assertNotIn("type: worker", render)

    def test_identity_worker_is_not_started_as_a_second_render_service(self):
        render = (ROOT / "render.yaml").read_text(encoding="utf-8")

        self.assertNotIn("identity_worker", render)
        self.assertNotIn("identity-worker", render)
        self.assertNotIn("run_identity", render)


if __name__ == "__main__":
    unittest.main()
