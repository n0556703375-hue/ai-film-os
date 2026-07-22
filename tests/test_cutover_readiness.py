import unittest
from pathlib import Path

from app.database.cutover_readiness import assess_cutover_readiness


class CutoverReadinessTests(unittest.TestCase):
    def setUp(self):
        self.source = Path("source.db")
        self.backup = Path("backup.db")
        self.url = "postgresql://user:secret@example.invalid/film_os"
        self.counts = {"projects": 2, "scenes": 4}

    def test_ready_requires_matching_verified_evidence(self):
        result = assess_cutover_readiness(
            self.source,
            self.backup,
            self.url,
            backup_verifier=lambda source, backup: {
                "status": "verified",
                "source_row_counts": self.counts,
            },
            import_validator=lambda source, url: {
                "status": "validated",
                "row_counts": self.counts,
                "table_count": 2,
                "constraints_validated": True,
                "rolled_back": True,
            },
        )

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["backup_verified"])
        self.assertTrue(result["import_validated"])
        self.assertTrue(result["constraints_validated"])
        self.assertTrue(result["rollback_confirmed"])
        self.assertFalse(result["persistent_changes"])
        self.assertNotIn("secret", str(result))
        self.assertNotIn(str(self.source), str(result))

    def test_failed_backup_stops_before_postgres_validation(self):
        calls = []

        result = assess_cutover_readiness(
            self.source,
            self.backup,
            self.url,
            backup_verifier=lambda source, backup: {"status": "blocked"},
            import_validator=lambda source, url: calls.append((source, url)),
        )

        self.assertEqual(result["reason"], "backup_verification_failed")
        self.assertEqual(calls, [])
        self.assertFalse(result["persistent_changes"])

    def test_failed_import_validation_blocks_readiness(self):
        result = assess_cutover_readiness(
            self.source,
            self.backup,
            self.url,
            backup_verifier=lambda source, backup: {
                "status": "verified",
                "source_row_counts": self.counts,
            },
            import_validator=lambda source, url: {"status": "blocked"},
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "import_validation_failed")
        self.assertTrue(result["backup_verified"])
        self.assertFalse(result["import_validated"])

    def test_missing_constraint_evidence_blocks_readiness(self):
        result = assess_cutover_readiness(
            self.source,
            self.backup,
            self.url,
            backup_verifier=lambda source, backup: {
                "status": "verified",
                "source_row_counts": self.counts,
            },
            import_validator=lambda source, url: {
                "status": "validated",
                "row_counts": self.counts,
                "rolled_back": True,
            },
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "validation_integrity_incomplete")
        self.assertFalse(result["constraints_validated"])
        self.assertTrue(result["rollback_confirmed"])
        self.assertFalse(result["persistent_changes"])

    def test_missing_rollback_evidence_blocks_readiness(self):
        result = assess_cutover_readiness(
            self.source,
            self.backup,
            self.url,
            backup_verifier=lambda source, backup: {
                "status": "verified",
                "source_row_counts": self.counts,
            },
            import_validator=lambda source, url: {
                "status": "validated",
                "row_counts": self.counts,
                "constraints_validated": True,
            },
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "validation_integrity_incomplete")
        self.assertTrue(result["constraints_validated"])
        self.assertFalse(result["rollback_confirmed"])
        self.assertFalse(result["persistent_changes"])

    def test_mismatched_row_count_evidence_blocks_readiness(self):
        result = assess_cutover_readiness(
            self.source,
            self.backup,
            self.url,
            backup_verifier=lambda source, backup: {
                "status": "verified",
                "source_row_counts": self.counts,
            },
            import_validator=lambda source, url: {
                "status": "validated",
                "row_counts": {"projects": 1, "scenes": 4},
                "constraints_validated": True,
                "rolled_back": True,
            },
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "validation_evidence_mismatch")
        self.assertFalse(result["persistent_changes"])


if __name__ == "__main__":
    unittest.main()
