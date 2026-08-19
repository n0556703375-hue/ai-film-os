"""Coverage for app.services.shot_visual_continuity — resolving real shot
media into frame URLs and calling the AI visual continuity check, always
degrading to [] rather than raising when the check can't run.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import projects, scenes, shots
from app.services.shot_visual_continuity import visual_continuity_ai_issues


class VisualContinuityAiIssuesTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        self.original_key = settings.openai_api_key
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        self.project = projects.create_project(
            {"name": "VC", "description": "", "visual_style": "", "rules": ""}
        )
        scene = scenes.create_scene({
            "project_id": self.project["id"], "scene_number": 1, "title": "S",
            "status": "מתוכנן", "story_goal": "", "emotion": "", "conflict": "",
            "beginning": "", "ending": "", "notes": "",
        })
        self.shot_a = shots.create_shot({
            "project_id": self.project["id"], "scene_id": scene["id"],
            "shot_number": 1, "title": "A",
        })
        self.shot_b = shots.create_shot({
            "project_id": self.project["id"], "scene_id": scene["id"],
            "shot_number": 2, "title": "B",
        })

    def tearDown(self):
        settings.database_path = self.original_db
        settings.openai_api_key = self.original_key
        self.tempdir.cleanup()

    def test_returns_empty_when_no_api_key_and_no_adapter_given(self):
        settings.openai_api_key = ""
        self.assertEqual(visual_continuity_ai_issues(self.shot_a["id"]), [])

    def test_returns_empty_when_shot_missing(self):
        adapter = Mock()
        self.assertEqual(visual_continuity_ai_issues(999999, adapter=adapter), [])
        adapter.compare_continuity.assert_not_called()

    def test_returns_empty_when_neighbor_has_no_media(self):
        shots.create_media_result(self.shot_a["id"], {
            "media_type": "image", "url": "https://example.com/a.png", "status": "טיוטה",
        })
        adapter = Mock()
        issues = visual_continuity_ai_issues(self.shot_a["id"], adapter=adapter)
        self.assertEqual(issues, [])
        adapter.compare_continuity.assert_not_called()

    def test_calls_adapter_when_both_shots_have_images(self):
        shots.create_media_result(self.shot_a["id"], {
            "media_type": "image", "url": "https://example.com/a.png", "status": "טיוטה",
        })
        shots.create_media_result(self.shot_b["id"], {
            "media_type": "image", "url": "https://example.com/b.png", "status": "טיוטה",
        })
        adapter = Mock()
        adapter.compare_continuity.return_value = {
            "continuity_score": 0.3, "flags": ["wardrobe_changed"], "evidence": {},
            "provider": "openai", "model": "m",
        }
        issues = visual_continuity_ai_issues(self.shot_a["id"], adapter=adapter)
        self.assertEqual(len(issues), 1)
        adapter.compare_continuity.assert_called_once_with(
            current_url="https://example.com/a.png", neighbor_url="https://example.com/b.png",
        )

    def test_adapter_exception_is_swallowed(self):
        shots.create_media_result(self.shot_a["id"], {
            "media_type": "image", "url": "https://example.com/a.png", "status": "טיוטה",
        })
        shots.create_media_result(self.shot_b["id"], {
            "media_type": "image", "url": "https://example.com/b.png", "status": "טיוטה",
        })
        adapter = Mock()
        adapter.compare_continuity.side_effect = RuntimeError("boom")
        issues = visual_continuity_ai_issues(self.shot_a["id"], adapter=adapter)
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
