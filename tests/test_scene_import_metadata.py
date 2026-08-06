import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.repositories import scenes


class SceneImportMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "scene-import.db"
        conn = self._connect()
        conn.executescript(
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE scenes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                scene_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'מתוכנן',
                story_goal TEXT NOT NULL DEFAULT '',
                emotion TEXT NOT NULL DEFAULT '',
                conflict TEXT NOT NULL DEFAULT '',
                beginning TEXT NOT NULL DEFAULT '',
                ending TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO projects(id, name) VALUES (2, 'Production Smoke Test');
            """
        )
        conn.commit()
        conn.close()
        self.patcher = patch(
            "app.repositories.scenes.get_connection",
            side_effect=self._connect,
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_import_response_preserves_owning_project_id(self):
        created = scenes.import_scenes(
            2,
            [
                {
                    "scene_number": 1,
                    "title": "פתיחה",
                    "recommended_shot_count": 4,
                    "estimated_duration_seconds": 45,
                }
            ],
            False,
        )

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["project_id"], 2)
        self.assertEqual(created[0]["recommended_shot_count"], 4)

        conn = self._connect()
        stored = conn.execute(
            "SELECT project_id FROM scenes WHERE id=?",
            (created[0]["id"],),
        ).fetchone()
        conn.close()
        self.assertEqual(stored["project_id"], 2)


if __name__ == "__main__":
    unittest.main()
