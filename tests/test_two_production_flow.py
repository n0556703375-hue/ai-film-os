import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.repositories import assets, projects, scenes, shots


class TwoProductionFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "two-productions.db"
        conn = self._connect()
        conn.executescript(
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                visual_style TEXT NOT NULL DEFAULT '',
                rules TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE shots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                scene_id INTEGER,
                shot_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                shot_type TEXT NOT NULL DEFAULT 'רגיל',
                status TEXT NOT NULL DEFAULT 'מתוכנן',
                duration_seconds REAL,
                notes TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL DEFAULT '',
                negative_prompt TEXT NOT NULL DEFAULT '',
                camera TEXT NOT NULL DEFAULT '',
                lens TEXT NOT NULL DEFAULT '',
                lighting TEXT NOT NULL DEFAULT '',
                movement TEXT NOT NULL DEFAULT '',
                mood TEXT NOT NULL DEFAULT '',
                dialogue TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                asset_type TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                visual_rules TEXT NOT NULL DEFAULT '',
                master_prompt TEXT NOT NULL DEFAULT '',
                negative_prompt TEXT NOT NULL DEFAULT '',
                reference_url TEXT NOT NULL DEFAULT '',
                approved INTEGER NOT NULL DEFAULT 0,
                lock_status TEXT NOT NULL DEFAULT 'draft',
                master_reference_id INTEGER,
                locked_at TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE shot_assets (
                shot_id INTEGER NOT NULL,
                asset_id INTEGER NOT NULL,
                PRIMARY KEY(shot_id, asset_id)
            );
            CREATE TABLE asset_reference_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER NOT NULL,
                view_type TEXT NOT NULL,
                url TEXT NOT NULL,
                prompt TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                approved INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
            """
        )
        conn.commit()
        conn.close()

        self.patchers = [
            patch("app.repositories.projects.get_connection", side_effect=self._connect),
            patch("app.repositories.scenes.get_connection", side_effect=self._connect),
            patch("app.repositories.shots.get_connection", side_effect=self._connect),
            patch("app.repositories.assets.get_connection", side_effect=self._connect),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _create_production(self, name):
        project = projects.create_project({
            "name": name,
            "description": f"Production {name}",
            "visual_style": "cinematic",
            "rules": "isolated",
        })
        scene = scenes.create_scene({
            "project_id": project["id"],
            "scene_number": 1,
            "title": f"{name} scene",
            "status": "מתוכנן",
        })
        asset = assets.create_asset({
            "project_id": project["id"],
            "asset_type": "דמות",
            "name": f"{name} character",
        })
        shot = shots.create_shot({
            "project_id": project["id"],
            "scene_id": scene["id"],
            "shot_number": 1,
            "title": f"{name} shot",
        })
        shots.set_shot_assets(shot["id"], [asset["id"]])
        return project, scene, asset, shot

    def test_two_productions_stay_isolated_through_core_flow(self):
        project_a, scene_a, asset_a, shot_a = self._create_production("A")
        project_b, scene_b, asset_b, shot_b = self._create_production("B")

        self.assertEqual([item["id"] for item in scenes.list_scenes(project_a["id"])], [scene_a["id"]])
        self.assertEqual([item["id"] for item in scenes.list_scenes(project_b["id"])], [scene_b["id"]])
        self.assertEqual([item["id"] for item in shots.list_shots(project_a["id"])], [shot_a["id"]])
        self.assertEqual([item["id"] for item in shots.list_shots(project_b["id"])], [shot_b["id"]])
        self.assertEqual([item["id"] for item in assets.list_assets(project_a["id"])], [asset_a["id"]])
        self.assertEqual([item["id"] for item in assets.list_assets(project_b["id"])], [asset_b["id"]])

        self.assertEqual([item["id"] for item in shots.get_shot(shot_a["id"])["assets"]], [asset_a["id"]])
        self.assertEqual([item["id"] for item in shots.get_shot(shot_b["id"])["assets"]], [asset_b["id"]])

    def test_cross_project_relationships_are_rejected_without_corrupting_valid_data(self):
        project_a, scene_a, asset_a, shot_a = self._create_production("A")
        project_b, scene_b, asset_b, _shot_b = self._create_production("B")

        with self.assertRaisesRegex(ValueError, "סצנה מפרויקט אחר"):
            shots.create_shot({
                "project_id": project_a["id"],
                "scene_id": scene_b["id"],
                "shot_number": 2,
                "title": "cross-project shot",
            })

        with self.assertRaisesRegex(ValueError, "סצנה מפרויקט אחר"):
            shots.update_shot(shot_a["id"], {"scene_id": scene_b["id"]})

        with self.assertRaisesRegex(ValueError, "נכס מפרויקט אחר"):
            shots.set_shot_assets(shot_a["id"], [asset_b["id"]])

        current = shots.get_shot(shot_a["id"])
        self.assertEqual(current["scene_id"], scene_a["id"])
        self.assertEqual([item["id"] for item in current["assets"]], [asset_a["id"]])
        self.assertEqual(len(shots.list_shots(project_a["id"])), 1)
        self.assertEqual(len(shots.list_shots(project_b["id"])), 1)


if __name__ == "__main__":
    unittest.main()
