import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.repositories import shots


class ProjectIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "isolation.db"
        conn = self._connect()
        conn.executescript(
            """
            CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE scenes (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                scene_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                story_goal TEXT NOT NULL DEFAULT '',
                emotion TEXT NOT NULL DEFAULT '',
                conflict TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE shots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                scene_id INTEGER,
                shot_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                shot_type TEXT NOT NULL DEFAULT 'רגיל',
                status TEXT NOT NULL DEFAULT 'מתוכנן',
                prompt TEXT NOT NULL DEFAULT '',
                negative_prompt TEXT NOT NULL DEFAULT '',
                lighting TEXT NOT NULL DEFAULT '',
                mood TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                asset_type TEXT NOT NULL DEFAULT 'דמות',
                name TEXT NOT NULL,
                lock_status TEXT NOT NULL DEFAULT 'draft',
                master_reference_id INTEGER
            );
            CREATE TABLE shot_assets (shot_id INTEGER NOT NULL, asset_id INTEGER NOT NULL, PRIMARY KEY(shot_id, asset_id));
            CREATE TABLE asset_reference_images (
                id INTEGER PRIMARY KEY,
                asset_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                approved INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE prompt_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shot_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                prompt TEXT NOT NULL,
                negative_prompt TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE media_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shot_id INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                version INTEGER NOT NULL,
                url TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                prompt_version_id INTEGER,
                status TEXT NOT NULL DEFAULT 'טיוטה',
                notes TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO projects(id,name) VALUES (1,'A'),(2,'B');
            INSERT INTO scenes(id,project_id,scene_number,title) VALUES (11,1,1,'A1'),(22,2,1,'B1');
            INSERT INTO shots(id,project_id,scene_id,shot_number,title) VALUES (101,1,11,1,'shot A');
            INSERT INTO assets(id,project_id,name) VALUES (201,1,'asset A'),(202,2,'asset B');
            """
        )
        conn.commit()
        conn.close()
        self.patcher = patch("app.repositories.shots.get_connection", side_effect=self._connect)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_create_shot_rejects_scene_from_another_project(self):
        with self.assertRaisesRegex(ValueError, "סצנה מפרויקט אחר"):
            shots.create_shot({
                "project_id": 1,
                "scene_id": 22,
                "shot_number": 2,
                "title": "invalid",
            })

    def test_update_shot_rejects_move_to_scene_from_another_project(self):
        with self.assertRaisesRegex(ValueError, "סצנה מפרויקט אחר"):
            shots.update_shot(101, {"scene_id": 22})

    def test_asset_link_rejects_asset_from_another_project_without_mutation(self):
        shots.set_shot_assets(101, [201])
        with self.assertRaisesRegex(ValueError, "נכס מפרויקט אחר"):
            shots.set_shot_assets(101, [202])
        conn = self._connect()
        linked = conn.execute("SELECT asset_id FROM shot_assets WHERE shot_id=101").fetchall()
        conn.close()
        self.assertEqual([row["asset_id"] for row in linked], [201])

    def test_same_project_relationships_remain_allowed(self):
        created = shots.create_shot({
            "project_id": 1,
            "scene_id": 11,
            "shot_number": 2,
            "title": "valid",
        })
        shots.set_shot_assets(created["id"], [201])
        self.assertEqual(created["project_id"], 1)
        self.assertEqual(created["scene_id"], 11)


if __name__ == "__main__":
    unittest.main()
