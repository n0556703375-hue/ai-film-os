import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LockedShotReferenceTests(unittest.TestCase):
    def test_shot_assets_only_expose_locked_approved_master_reference(self):
        source = (ROOT / "app" / "repositories" / "shots.py").read_text(encoding="utf-8")

        self.assertIn("AND r.approved=1", source)
        self.assertIn("AND r.id=?", source)
        self.assertIn("AND ?='locked'", source)
        self.assertIn('asset.get("master_reference_id")', source)
        self.assertNotIn(
            'SELECT url FROM asset_reference_images WHERE asset_id=? ORDER BY id DESC',
            source,
        )


if __name__ == "__main__":
    unittest.main()
