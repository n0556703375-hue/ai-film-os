import unittest
from pathlib import Path


class RuntimeDependencyTests(unittest.TestCase):
    def test_postgresql_driver_is_declared_for_runtime_adapter(self):
        requirements = Path("requirements.txt").read_text(encoding="utf-8").splitlines()
        normalized = [line.strip().lower() for line in requirements if line.strip()]

        self.assertTrue(
            any(line.startswith("psycopg[binary]") for line in normalized),
            "The PostgreSQL backend requires the psycopg binary runtime dependency.",
        )


if __name__ == "__main__":
    unittest.main()
