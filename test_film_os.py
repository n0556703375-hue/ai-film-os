import sqlite3
import tempfile
import unittest
from pathlib import Path

import main


class FilmOSV3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        main.DB_PATH = Path(self.tmp.name) / "film_os.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_v2_database_is_migrated_without_losing_data(self):
        conn = sqlite3.connect(main.DB_PATH)
        conn.executescript("""
        CREATE TABLE shots (
          id INTEGER PRIMARY KEY,title TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'מתוכנן',
          notes TEXT NOT NULL DEFAULT '',prompt TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE assets (
          id INTEGER PRIMARY KEY AUTOINCREMENT,asset_type TEXT NOT NULL,name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',visual_rules TEXT NOT NULL DEFAULT '',
          reference_url TEXT NOT NULL DEFAULT '',approved INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE shot_assets (shot_id INTEGER NOT NULL,asset_id INTEGER NOT NULL,PRIMARY KEY(shot_id,asset_id));
        INSERT INTO shots (id,title,notes,prompt) VALUES (1,'שוט קיים','הערה קיימת','פרומפט קיים');
        INSERT INTO assets (asset_type,name) VALUES ('אביזר','נכס קיים');
        """)
        conn.commit()
        conn.close()

        main.init_db()

        conn = sqlite3.connect(main.DB_PATH)
        conn.row_factory = sqlite3.Row
        shot = conn.execute("SELECT * FROM shots WHERE id=1").fetchone()
        self.assertEqual(shot["notes"], "הערה קיימת")
        self.assertEqual(shot["prompt"], "פרומפט קיים")
        self.assertIsNotNone(shot["scene_id"])
        self.assertEqual(conn.execute("SELECT name FROM assets WHERE id=1").fetchone()[0], "נכס קיים")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM prompt_versions WHERE shot_id=1").fetchone()[0], 1)
        conn.close()

    def test_prompt_media_and_continuity_versions(self):
        main.init_db()
        scene_id = main.list_scenes()[0]["id"]
        created = main.create_shot(main.ShotCreate(
            title="שוט חדש", scene_id=scene_id, shot_number=21,
            shot_type="קלוז־אפ", duration_seconds=3.5,
        ))
        self.assertEqual(created["scene_id"], scene_id)
        self.assertEqual(created["shot_type"], "קלוז־אפ")
        main.update_shot(1, main.ShotUpdate(prompt="גרסה ראשונה", negative_prompt="ללא טקסט"))
        main.update_shot(1, main.ShotUpdate(prompt="גרסה שנייה"))
        prompts = main.list_prompt_versions(1)
        self.assertEqual([item["version"] for item in prompts], [2, 1])

        first = main.create_media_result(1, main.MediaResultCreate(media_type="image", url="https://example.com/1.jpg"))
        second = main.create_media_result(1, main.MediaResultCreate(media_type="image", url="https://example.com/2.jpg"))
        self.assertEqual((first["version"], second["version"]), (1, 2))

        check = main.create_continuity_check(1, main.ContinuityCreate(category="צבע", issue="גוון שונה"))
        updated = main.update_continuity_check(check["id"], main.ContinuityUpdate(status="נפתר", resolution="תוקן"))
        self.assertEqual(updated["status"], "נפתר")


if __name__ == "__main__":
    unittest.main()
