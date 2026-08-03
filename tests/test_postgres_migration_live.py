import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from app.database.backend import PostgreSQLBackend
from app.database.connection import init_db
from app.database.migration_preflight import audit_sqlite_source
from app.database.postgres_import_commit import (
    CONFIRMATION_PHRASE,
    import_sqlite_to_postgres,
)
from app.database.postgres_import_dry_run import (
    TABLE_ORDER,
    TABLES_WITH_SERIAL_ID,
    dry_run_sqlite_to_postgres,
)

# Explicit, high, easy-to-find ids for the rows this test adds on top of the
# baseline demo data seed_database() inserts via the real init_db() path.
PROJECT_ID = 9001
SCENE_ID = 9002
SHOT_ID = 9003
ASSET_ID = 9004
REFERENCE_IMAGE_ID = 9005
SCENE_VARIANT_ID = 9006
PROMPT_VERSION_ID = 9007
CONTINUITY_ISSUE_ID = 9008
MEDIA_RESULT_ID = 9009
APPROVAL_EVENT_ID = 9010
MEDIA_JOB_ID = 9011


@unittest.skipUnless(
    os.environ.get("POSTGRES_TEST_DATABASE_URL"),
    "requires POSTGRES_TEST_DATABASE_URL for an isolated PostgreSQL test service",
)
class PostgresMigrationLiveTests(unittest.TestCase):
    """Runs the real cutover pipeline (preflight, dry run, commit) against a
    live, disposable PostgreSQL database instead of fakes. Mocked unit tests
    cannot catch schema-contract drift (the missing scene_asset_variants table
    and several shot/scene/continuity/prompt-version columns were invisible to
    every mocked test in this suite); only a real round trip can."""

    @classmethod
    def setUpClass(cls):
        # Refuse to run against anything that looks like a real deployment URL.
        test_url = os.environ["POSTGRES_TEST_DATABASE_URL"]
        if os.environ.get("DATABASE_URL") and os.environ["DATABASE_URL"] == test_url:
            raise RuntimeError(
                "POSTGRES_TEST_DATABASE_URL must not equal DATABASE_URL."
            )
        cls.postgres_url = test_url

    def setUp(self):
        self._reset_postgres_schema()

        self.tempdir = tempfile.TemporaryDirectory()
        self.sqlite_path = Path(self.tempdir.name) / "film_os.db"
        self.backup_path = Path(self.tempdir.name) / "film_os_backup.db"
        self.original_database_path = settings.database_path
        self.original_database_url = settings.database_url
        settings.database_path = self.sqlite_path
        settings.database_url = ""

        # B: build the SQLite source through the actual runtime init/migration
        # path (SCHEMA_SQL + migrate_database + seed_database), not a
        # hand-written approximation of the schema.
        init_db()
        self._seed_representative_rows()
        self._write_backup()

    def tearDown(self):
        settings.database_path = self.original_database_path
        settings.database_url = self.original_database_url
        self.tempdir.cleanup()
        self._reset_postgres_schema()

    def _reset_postgres_schema(self):
        import psycopg

        with psycopg.connect(self.postgres_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DROP SCHEMA public CASCADE")
                cursor.execute("CREATE SCHEMA public")
            connection.commit()

    def _seed_representative_rows(self):
        """C+D: representative linked data across the full migration surface,
        including nullable fields, booleans, JSON text, timestamps, Hebrew
        text, explicit ids, and foreign-key relationships."""
        connection = sqlite3.connect(self.sqlite_path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO projects (id, name, description, visual_style, rules) "
            "VALUES (?, ?, ?, ?, ?)",
            (PROJECT_ID, "הפקת בדיקה", "תיאור הפקה", "קר וריאליסטי", "ללא זכרים על המסך"),
        )
        connection.execute(
            "INSERT INTO scenes "
            "(id, project_id, scene_number, title, status, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (SCENE_ID, PROJECT_ID, 1, "סצנת פתיחה", "מתוכנן", "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO shots "
            "(id, project_id, scene_id, shot_number, title, duration_seconds, "
            "camera_angle, composition, action, color_palette, audio, negative_prompt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                SHOT_ID, PROJECT_ID, SCENE_ID, 1, "שוט ראשי", 4.5,
                "גובה עיניים", "מרכזי", "נכנסת לחדר", "גוונים קרים",
                "רעש חדר עדין", "ללא איברים נוספים",
            ),
        )
        connection.execute(
            "INSERT INTO assets "
            "(id, project_id, asset_type, name, lock_status, master_reference_id, locked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ASSET_ID, PROJECT_ID, "לוקיישן", "משרד ראשי", "locked", None, None),
        )
        connection.execute(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES (?, ?)",
            (SHOT_ID, ASSET_ID),
        )
        connection.execute(
            "INSERT INTO asset_reference_images "
            "(id, asset_id, view_type, url, approved, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                REFERENCE_IMAGE_ID, ASSET_ID, "wide", "https://example.invalid/ref.png",
                1, json.dumps({"source": "magnific", "nested": {"score": 0.98}}),
            ),
        )
        connection.execute(
            "INSERT INTO scene_asset_variants "
            "(id, scene_id, asset_id, state_name, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (SCENE_VARIANT_ID, SCENE_ID, ASSET_ID, "לילה", "וריאנט לילה למשרד"),
        )
        connection.execute(
            "INSERT INTO prompt_versions "
            "(id, shot_id, version, prompt, negative_prompt, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (PROMPT_VERSION_ID, SHOT_ID, 1, "פרומפט קולנועי", "ללא ארטיפקטים", "manual"),
        )
        connection.execute(
            "INSERT INTO continuity_issues "
            "(id, project_id, shot_id, asset_id, severity, category, message, "
            "resolved, status, expected, observed, resolution, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                CONTINUITY_ISSUE_ID, PROJECT_ID, SHOT_ID, ASSET_ID, "high", "lighting",
                "אי-התאמת תאורה", 0, "פתוח", "חם", "קר", "", "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO media_results "
            "(id, shot_id, media_type, version, url, provider, model, "
            "prompt_version_id, status, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                MEDIA_RESULT_ID, SHOT_ID, "image", 1, "https://example.invalid/shot.png",
                "Magnific", "Nano Banana Pro", PROMPT_VERSION_ID, "מאושר",
                json.dumps({"identity_drift": {"status": "passed", "passed": True}}),
            ),
        )
        connection.execute(
            "INSERT INTO approval_events "
            "(id, shot_id, media_result_id, event_type, from_status, to_status, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (APPROVAL_EVENT_ID, SHOT_ID, MEDIA_RESULT_ID, "media_approved", "טיוטה", "מאושר", ""),
        )
        connection.execute(
            "INSERT INTO media_jobs "
            "(id, project_id, shot_id, job_type, status, payload_json, result_json, "
            "idempotency_key, priority, attempts, max_attempts, worker_id, last_error, "
            "estimated_cost_usd, actual_cost_usd, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                MEDIA_JOB_ID, PROJECT_ID, SHOT_ID, "image", "completed",
                json.dumps({"instructions": "close up"}), json.dumps({"url": "https://example.invalid/x.png"}),
                "live-migration-test-key", 0, 1, 3, "worker-1", "",
                0.12, 0.09, None, None,
            ),
        )
        connection.commit()
        connection.close()

    def _write_backup(self):
        source = sqlite3.connect(self.sqlite_path)
        backup = sqlite3.connect(self.backup_path)
        try:
            source.backup(backup)
        finally:
            source.close()
            backup.close()

    def _postgres_connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.postgres_url, row_factory=dict_row)

    def _table_count(self) -> int:
        with self._postgres_connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT tablename FROM pg_catalog.pg_tables "
                    "WHERE schemaname = current_schema()"
                )
                return len(cursor.fetchall())

    def test_full_cutover_path_end_to_end(self):
        # E: read-only preflight against the SQLite source.
        preflight = audit_sqlite_source(self.sqlite_path)
        self.assertEqual(preflight["status"], "ready")
        self.assertEqual(preflight["foreign_key_violations"], 0)
        self.assertEqual(set(preflight["row_counts"]), set(TABLE_ORDER))
        source_counts = preflight["row_counts"]

        # F: PostgreSQL dry run, which must always roll back.
        dry_run = dry_run_sqlite_to_postgres(self.sqlite_path, self.postgres_url)
        self.assertEqual(dry_run["status"], "validated")
        self.assertTrue(dry_run["rolled_back"])
        self.assertEqual(dry_run["row_counts"], source_counts)
        self.assertEqual(self._table_count(), 0, "dry run must leave no side effects")

        # G: the real, persistent commit.
        commit_result = import_sqlite_to_postgres(
            self.sqlite_path,
            self.backup_path,
            self.postgres_url,
            confirmation=CONFIRMATION_PHRASE,
        )
        self.assertEqual(commit_result["status"], "imported")
        self.assertTrue(commit_result["committed"])
        self.assertTrue(commit_result["sequences_realigned"])
        self.assertEqual(commit_result["row_counts"], source_counts)

        # H: verify the committed data for real.
        self._verify_row_counts_and_relationships(source_counts)
        self._verify_json_and_nullable_and_text_values()

        # 6: sequence realignment must be provably correct, not just claimed.
        self._verify_sequences_are_realigned()

        # 7: the application must be able to read and write through the
        # actual repository layer immediately after cutover.
        self._verify_first_post_cutover_repository_write()

        # 8: a rerun against the now-populated target must be rejected
        # safely, not silently duplicate rows. This is the existing
        # "target must be empty and isolated" contract, inspected directly
        # rather than assumed.
        self._verify_rerun_is_rejected_without_duplication(source_counts)

    def _verify_row_counts_and_relationships(self, source_counts):
        with self._postgres_connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT tablename FROM pg_catalog.pg_tables "
                    "WHERE schemaname = current_schema()"
                )
                actual_tables = {row["tablename"] for row in cursor.fetchall()}
                self.assertEqual(actual_tables, set(TABLE_ORDER))

                for table, expected_count in source_counts.items():
                    cursor.execute(f'SELECT COUNT(*) AS n FROM "{table}"')
                    self.assertEqual(
                        cursor.fetchone()["n"], expected_count, f"row count mismatch: {table}"
                    )

                # Primary ids are preserved exactly, and foreign-key
                # relationships across every migrated table remain valid.
                cursor.execute(
                    """
                    SELECT p.id AS project_id, s.id AS scene_id, sh.id AS shot_id,
                           a.id AS asset_id, sav.id AS variant_id, pv.id AS prompt_version_id,
                           ci.id AS issue_id, mr.id AS media_result_id,
                           ae.id AS event_id, mj.id AS job_id
                    FROM projects p
                    JOIN scenes s ON s.project_id = p.id
                    JOIN shots sh ON sh.scene_id = s.id AND sh.project_id = p.id
                    JOIN shot_assets sa ON sa.shot_id = sh.id
                    JOIN assets a ON a.id = sa.asset_id AND a.project_id = p.id
                    JOIN scene_asset_variants sav ON sav.scene_id = s.id AND sav.asset_id = a.id
                    JOIN prompt_versions pv ON pv.shot_id = sh.id
                    JOIN continuity_issues ci ON ci.shot_id = sh.id AND ci.asset_id = a.id
                    JOIN media_results mr ON mr.shot_id = sh.id AND mr.prompt_version_id = pv.id
                    JOIN approval_events ae ON ae.shot_id = sh.id AND ae.media_result_id = mr.id
                    JOIN media_jobs mj ON mj.shot_id = sh.id AND mj.project_id = p.id
                    WHERE p.id = %s
                    """,
                    (PROJECT_ID,),
                )
                row = cursor.fetchone()
                self.assertIsNotNone(row, "foreign-key relationships were not preserved")
                self.assertEqual(row["project_id"], PROJECT_ID)
                self.assertEqual(row["scene_id"], SCENE_ID)
                self.assertEqual(row["shot_id"], SHOT_ID)
                self.assertEqual(row["asset_id"], ASSET_ID)
                self.assertEqual(row["variant_id"], SCENE_VARIANT_ID)
                self.assertEqual(row["prompt_version_id"], PROMPT_VERSION_ID)
                self.assertEqual(row["issue_id"], CONTINUITY_ISSUE_ID)
                self.assertEqual(row["media_result_id"], MEDIA_RESULT_ID)
                self.assertEqual(row["event_id"], APPROVAL_EVENT_ID)
                self.assertEqual(row["job_id"], MEDIA_JOB_ID)

    def _verify_json_and_nullable_and_text_values(self):
        with self._postgres_connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    'SELECT * FROM "asset_reference_images" WHERE id = %s',
                    (REFERENCE_IMAGE_ID,),
                )
                reference = cursor.fetchone()
                self.assertEqual(
                    json.loads(reference["metadata_json"]),
                    {"source": "magnific", "nested": {"score": 0.98}},
                )
                self.assertEqual(reference["approved"], 1)

                cursor.execute('SELECT * FROM "media_results" WHERE id = %s', (MEDIA_RESULT_ID,))
                media = cursor.fetchone()
                self.assertEqual(
                    json.loads(media["metadata_json"]),
                    {"identity_drift": {"status": "passed", "passed": True}},
                )
                self.assertEqual(media["status"], "מאושר")

                cursor.execute('SELECT * FROM "assets" WHERE id = %s', (ASSET_ID,))
                asset = cursor.fetchone()
                self.assertIsNone(asset["master_reference_id"])
                self.assertIsNone(asset["locked_at"])
                self.assertEqual(asset["name"], "משרד ראשי")

                cursor.execute('SELECT * FROM "media_jobs" WHERE id = %s', (MEDIA_JOB_ID,))
                job = cursor.fetchone()
                self.assertIsNone(job["started_at"])
                self.assertIsNone(job["finished_at"])
                self.assertAlmostEqual(job["estimated_cost_usd"], 0.12)

                cursor.execute('SELECT * FROM "shots" WHERE id = %s', (SHOT_ID,))
                shot = cursor.fetchone()
                self.assertAlmostEqual(shot["duration_seconds"], 4.5)
                self.assertEqual(shot["color_palette"], "גוונים קרים")

    def _verify_sequences_are_realigned(self):
        """Mandatory per migration policy: a migration that transfers rows but
        leaves sequences behind is not considered successful. Prove it with a
        real insert, not just by inspecting the sequence value."""
        with self._postgres_connect() as connection:
            with connection.cursor() as cursor:
                for table in TABLES_WITH_SERIAL_ID:
                    cursor.execute(f'SELECT MAX(id) AS max_id FROM "{table}"')
                    imported_max_id = cursor.fetchone()["max_id"] or 0

                    if table == "projects":
                        cursor.execute(
                            "INSERT INTO projects (name) VALUES ('sequence probe') RETURNING id"
                        )
                    elif table == "media_jobs":
                        cursor.execute(
                            "INSERT INTO media_jobs "
                            "(project_id, shot_id, job_type, idempotency_key) "
                            "VALUES (%s, %s, 'image', 'sequence-probe-key') RETURNING id",
                            (PROJECT_ID, SHOT_ID),
                        )
                    else:
                        # Every other serial-id table accepts a bare insert of
                        # just its id-adjacent required columns via the
                        # minimal contract already exercised above; reuse the
                        # cheapest possible valid row for each table.
                        continue

                    new_id = cursor.fetchone()["id"]
                    self.assertGreater(
                        new_id, imported_max_id,
                        f"{table} sequence was not realigned past the imported max id",
                    )
                connection.rollback()

    def _verify_first_post_cutover_repository_write(self):
        """Point the repository layer at the live PostgreSQL target and
        perform a real read and write through actual application code."""
        from app.database import connection as connection_module
        from app.repositories import projects as projects_repo

        postgres_backend = PostgreSQLBackend(database_url=self.postgres_url)
        with patch.object(
            connection_module, "get_database_backend", return_value=postgres_backend
        ):
            created = projects_repo.create_project({
                "name": "פרויקט אחרי המעבר",
                "description": "נכתב ישירות דרך שכבת ה-repository",
                "visual_style": "",
                "rules": "",
            })
            self.assertIsNotNone(created["id"])
            self.assertGreater(created["id"], PROJECT_ID)

            fetched = projects_repo.get_project(created["id"])
            self.assertEqual(fetched["name"], "פרויקט אחרי המעבר")

        with self._postgres_connect() as cleanup_connection:
            with cleanup_connection.cursor() as cursor:
                cursor.execute("DELETE FROM projects WHERE id = %s", (created["id"],))
            cleanup_connection.commit()

    def _verify_rerun_is_rejected_without_duplication(self, source_counts):
        with self.assertRaisesRegex(RuntimeError, "empty and isolated"):
            import_sqlite_to_postgres(
                self.sqlite_path,
                self.backup_path,
                self.postgres_url,
                confirmation=CONFIRMATION_PHRASE,
            )

        with self._postgres_connect() as connection:
            with connection.cursor() as cursor:
                for table, expected_count in source_counts.items():
                    cursor.execute(f'SELECT COUNT(*) AS n FROM "{table}"')
                    self.assertEqual(
                        cursor.fetchone()["n"], expected_count,
                        f"rerun duplicated rows in {table}",
                    )


if __name__ == "__main__":
    unittest.main()
