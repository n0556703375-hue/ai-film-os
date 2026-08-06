"""Acceptance tests for issue #214: audio as a first-class media_results type.

Everything runs against a real SQLite database via init_db() and the normal
repository/API paths. No test uses PRAGMA ignore_check_constraints; audio rows
are created through the real schema, and unknown types are rejected by both
Pydantic and the database CHECK constraint.
"""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import pydantic

from app.core.config import settings
from app.database.connection import (
    _media_type_check_allows_audio,
    get_connection,
    init_db,
    migrate_database,
)
from app.database.schema import SCHEMA_SQL
from app.models.schemas import MediaResultCreate
from app.repositories import approvals, projects, scenes, shots

APPROVED = "מאושר"

_MEDIA_COLUMNS = (
    "id,shot_id,media_type,version,url,provider,model,"
    "prompt_version_id,status,notes,metadata_json,created_at"
)


class _RealDbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db = settings.database_path
        settings.database_path = Path(self._tmp.name) / "test.db"

    def tearDown(self):
        settings.database_path = self._orig_db
        self._tmp.cleanup()

    def _project_scene_shot(self):
        project = projects.create_project(
            {"name": "Audio", "description": "", "visual_style": "", "rules": ""}
        )
        scene = scenes.create_scene({
            "project_id": project["id"], "scene_number": 1, "title": "S",
            "status": "מתוכנן", "story_goal": "", "emotion": "", "conflict": "",
            "beginning": "", "ending": "", "notes": "",
        })
        shot = shots.create_shot({
            "project_id": project["id"], "scene_id": scene["id"], "shot_number": 1,
            "title": "Shot", "prompt": "p", "status": "פרומפט מוכן",
        })
        return project, scene, shot


def _build_legacy_database(path: Path) -> None:
    """Create a full schema but roll media_results back to the pre-audio CHECK.

    This reproduces a real deployed database: every sibling table present, and a
    media_results whose media_type CHECK allows only image/video, populated with
    rows and referenced by approval_events. foreign_keys is turned OFF only to
    swap in the legacy table shape for the fixture — never to bypass a CHECK.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    conn.commit()

    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN")
    conn.execute("DROP TABLE media_results")
    conn.execute("""
        CREATE TABLE media_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shot_id INTEGER NOT NULL,
            media_type TEXT NOT NULL CHECK(media_type IN ('image', 'video')),
            version INTEGER NOT NULL,
            url TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            prompt_version_id INTEGER,
            status TEXT NOT NULL DEFAULT 'טיוטה',
            notes TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(shot_id, media_type, version),
            FOREIGN KEY(shot_id) REFERENCES shots(id) ON DELETE CASCADE,
            FOREIGN KEY(prompt_version_id) REFERENCES prompt_versions(id) ON DELETE SET NULL
        )
    """)
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")

    # Parents required by foreign keys.
    conn.execute(
        "INSERT INTO projects (id,name,description,visual_style,rules) VALUES (1,'p','','','')"
    )
    conn.execute(
        "INSERT INTO scenes (id,project_id,scene_number,title) VALUES (1,1,1,'s')"
    )
    conn.execute(
        "INSERT INTO shots (id,project_id,scene_id,shot_number,title,prompt) "
        "VALUES (1,1,1,1,'sh','pr'),(2,1,1,2,'sh2','pr2')"
    )
    conn.execute("INSERT INTO prompt_versions (id,shot_id,version,prompt) VALUES (5,1,1,'pv')")
    conn.executemany(
        f"INSERT INTO media_results ({_MEDIA_COLUMNS}) VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, 1, "image", 1, "u1", "Magnific", "nb", 5, APPROVED, "n1", '{"k":1}', "2020-01-01 00:00:00"),
            (2, 1, "video", 1, "u2", "kling", "v", 5, "טיוטה", "", "{}", "2020-01-02 00:00:00"),
            (3, 2, "image", 1, "u3", "Magnific", "nb", None, "הוחלף", "", "{}", "2020-01-03 00:00:00"),
        ],
    )
    # A deleted max row so the AUTOINCREMENT high-water mark exceeds max(id).
    conn.execute("DELETE FROM media_results WHERE id=3")
    conn.execute(
        "INSERT INTO approval_events (id,shot_id,media_result_id,event_type) "
        "VALUES (100,1,1,'media_approved'),(101,1,2,'media_rejected')"
    )
    conn.commit()
    conn.close()


class FreshSchemaAudioTests(_RealDbTestCase):
    def test_fresh_schema_allows_audio_check(self):
        init_db()
        with closing(get_connection()) as conn:
            self.assertTrue(_media_type_check_allows_audio(conn))

    def test_schema_sql_constant_itself_allows_audio(self):
        """The fresh schema must allow audio directly, not only after migration.

        Building a database from SCHEMA_SQL alone (no migrate_database) must
        already accept audio; otherwise the fresh-schema requirement is only
        satisfied by the migration silently rebuilding the table.
        """
        self.assertIn("'audio'", SCHEMA_SQL)
        with tempfile.TemporaryDirectory() as directory:
            conn = sqlite3.connect(Path(directory) / "schema_only.db")
            conn.row_factory = sqlite3.Row
            try:
                conn.executescript(SCHEMA_SQL)
                conn.commit()
                self.assertTrue(_media_type_check_allows_audio(conn))
                conn.execute("INSERT INTO projects (id,name) VALUES (1,'p')")
                conn.execute(
                    "INSERT INTO scenes (id,project_id,scene_number,title) VALUES (1,1,1,'s')"
                )
                conn.execute(
                    "INSERT INTO shots (id,project_id,scene_id,shot_number,title,prompt) "
                    "VALUES (1,1,1,1,'sh','pr')"
                )
                conn.execute(
                    "INSERT INTO media_results (shot_id,media_type,version,url) "
                    "VALUES (1,'audio',1,'https://a/x.mp3')"
                )
                conn.commit()
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        "INSERT INTO media_results (shot_id,media_type,version,url) "
                        "VALUES (1,'bogus',9,'https://a/y.mp3')"
                    )
            finally:
                conn.close()

    def test_fresh_schema_accepts_audio_row(self):
        init_db()
        _, _, shot = self._project_scene_shot()
        media = shots.create_media_result(shot["id"], {
            "media_type": "audio", "url": "https://a/x.mp3", "status": "טיוטה",
        })
        self.assertEqual(media["media_type"], "audio")
        self.assertGreaterEqual(media["id"], 1)

    def test_fresh_schema_rejects_unknown_type_at_db(self):
        init_db()
        _, _, shot = self._project_scene_shot()
        with self.assertRaises(sqlite3.IntegrityError):
            shots.create_media_result(shot["id"], {
                "media_type": "podcast", "url": "https://a/x.mp3",
            })

    def test_pydantic_accepts_audio_rejects_unknown(self):
        MediaResultCreate(media_type="audio", url="https://a/x.mp3")
        with self.assertRaises(pydantic.ValidationError):
            MediaResultCreate(media_type="podcast", url="https://a/x.mp3")


class MigrationTests(_RealDbTestCase):
    def _snapshot(self, conn):
        rows = [tuple(r) for r in conn.execute(
            f"SELECT {_MEDIA_COLUMNS} FROM media_results ORDER BY id"
        )]
        events = [tuple(r) for r in conn.execute(
            "SELECT id,shot_id,media_result_id,event_type FROM approval_events ORDER BY id"
        )]
        return rows, events

    def test_existing_database_migrates_without_data_changes(self):
        _build_legacy_database(settings.database_path)
        conn = sqlite3.connect(settings.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            self.assertFalse(_media_type_check_allows_audio(conn))
            before_rows, before_events = self._snapshot(conn)

            migrate_database(conn)
            conn.commit()

            after_rows, after_events = self._snapshot(conn)
            self.assertEqual(before_rows, after_rows)
            self.assertEqual(before_events, after_events)
            self.assertTrue(_media_type_check_allows_audio(conn))
        finally:
            conn.close()

    def test_migration_preserves_approval_event_references(self):
        _build_legacy_database(settings.database_path)
        conn = sqlite3.connect(settings.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            migrate_database(conn)
            conn.commit()
            refs = [tuple(r) for r in conn.execute(
                "SELECT id,media_result_id FROM approval_events ORDER BY id"
            )]
            self.assertEqual(refs, [(100, 1), (101, 2)])
            # Every referenced media row still exists.
            for _event_id, media_id in refs:
                self.assertIsNotNone(conn.execute(
                    "SELECT 1 FROM media_results WHERE id=?", (media_id,)
                ).fetchone())
        finally:
            conn.close()

    def test_migration_foreign_key_check_is_clean(self):
        _build_legacy_database(settings.database_path)
        conn = sqlite3.connect(settings.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            migrate_database(conn)
            conn.commit()
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            conn.close()

    def test_migration_is_idempotent(self):
        _build_legacy_database(settings.database_path)
        conn = sqlite3.connect(settings.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            migrate_database(conn)
            conn.commit()
            first_rows, first_events = self._snapshot(conn)
            # Second and third runs must be no-ops with no error or data change.
            migrate_database(conn)
            migrate_database(conn)
            conn.commit()
            self.assertEqual(self._snapshot(conn), (first_rows, first_events))
        finally:
            conn.close()

    def test_migrated_database_accepts_audio_rejects_unknown(self):
        _build_legacy_database(settings.database_path)
        conn = sqlite3.connect(settings.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            migrate_database(conn)
            conn.commit()
            conn.execute(
                "INSERT INTO media_results (shot_id,media_type,version,url) "
                "VALUES (1,'audio',1,'https://a/x.mp3')"
            )
            conn.commit()
            # No id reuse: preserved rows are 1 and 2, deleted max was 3.
            audio_id = conn.execute(
                "SELECT id FROM media_results WHERE media_type='audio'"
            ).fetchone()[0]
            self.assertGreater(audio_id, 2)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO media_results (shot_id,media_type,version,url) "
                    "VALUES (1,'bogus',9,'https://a/y.mp3')"
                )
        finally:
            conn.close()

    def test_init_db_on_legacy_database_migrates_in_place(self):
        """The real startup path (init_db) migrates a legacy DB end to end."""
        _build_legacy_database(settings.database_path)
        init_db()
        with closing(get_connection()) as conn:
            self.assertTrue(_media_type_check_allows_audio(conn))
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM media_results").fetchone()[0], 2
            )


class AudioApprovalTests(_RealDbTestCase):
    def setUp(self):
        super().setUp()
        init_db()
        self.project, self.scene, self.shot = self._project_scene_shot()

    def _create(self, media_type, status="טיוטה", url=None):
        return shots.create_media_result(self.shot["id"], {
            "media_type": media_type,
            "url": url or f"https://a/{media_type}.mp3",
            "status": status,
        })

    def _shot_status(self):
        with closing(get_connection()) as conn:
            return conn.execute(
                "SELECT status FROM shots WHERE id=?", (self.shot["id"],)
            ).fetchone()[0]

    def test_audio_create_and_read(self):
        media = self._create("audio")
        listed = shots.list_media_results(self.shot["id"])
        audio = [m for m in listed if m["media_type"] == "audio"]
        self.assertEqual(len(audio), 1)
        self.assertEqual(audio[0]["id"], media["id"])

    def test_audio_versions_increment_independently(self):
        a1 = self._create("audio")
        a2 = self._create("audio")
        self.assertEqual(a1["version"], 1)
        self.assertEqual(a2["version"], 2)

    def test_audio_approval_and_single_approved_version(self):
        a1 = self._create("audio")
        approvals.decide_media(self.shot["id"], a1["id"], "approve", self.project["id"])
        a2 = self._create("audio")
        approvals.decide_media(self.shot["id"], a2["id"], "approve", self.project["id"])

        with closing(get_connection()) as conn:
            approved = conn.execute(
                "SELECT id FROM media_results WHERE shot_id=? AND media_type='audio' AND status=?",
                (self.shot["id"], APPROVED),
            ).fetchall()
            replaced = conn.execute(
                "SELECT status FROM media_results WHERE id=?", (a1["id"],)
            ).fetchone()[0]
        self.assertEqual([r[0] for r in approved], [a2["id"]])
        self.assertEqual(replaced, "הוחלף")

    def test_audio_approval_does_not_regress_finalized_shot(self):
        image = self._create("image")
        approvals.decide_media(self.shot["id"], image["id"], "approve", self.project["id"])
        video = self._create("video")
        approvals.decide_media(self.shot["id"], video["id"], "approve", self.project["id"])
        approvals.finalize_shot(self.shot["id"], self.project["id"])
        self.assertEqual(self._shot_status(), "סופי")

        audio = self._create("audio")
        approvals.decide_media(self.shot["id"], audio["id"], "approve", self.project["id"])
        # Approving audio must not pull the finalized shot backwards.
        self.assertEqual(self._shot_status(), "סופי")

    def test_audio_approval_does_not_advance_pipeline(self):
        audio = self._create("audio")
        before = self._shot_status()
        approvals.decide_media(self.shot["id"], audio["id"], "approve", self.project["id"])
        self.assertEqual(self._shot_status(), before)

    def test_audio_approval_event_reference_is_valid(self):
        audio = self._create("audio")
        approvals.decide_media(self.shot["id"], audio["id"], "approve", self.project["id"])
        with closing(get_connection()) as conn:
            event = conn.execute(
                "SELECT media_result_id FROM approval_events "
                "WHERE shot_id=? AND event_type='media_approved' ORDER BY id DESC LIMIT 1",
                (self.shot["id"],),
            ).fetchone()
            self.assertEqual(event[0], audio["id"])
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
