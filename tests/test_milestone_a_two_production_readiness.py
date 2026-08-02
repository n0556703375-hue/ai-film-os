import tempfile
import unittest
from pathlib import Path

from app.api.scenes import get_scene_preview_manifest
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import approvals, assets, issues, projects, scenes, shots


class MilestoneATwoProductionReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _create_production(self, name: str, marker: str):
        project = projects.create_project({
            "name": name,
            "description": "",
            "visual_style": marker,
            "rules": "",
        })
        scene = scenes.create_scene({
            "project_id": project["id"],
            "scene_number": 1,
            "title": f"{marker} scene",
            "status": "מתוכנן",
            "story_goal": "",
            "emotion": "",
            "conflict": "",
            "beginning": "",
            "ending": "",
            "notes": "",
        })
        shot = shots.create_shot({
            "project_id": project["id"],
            "scene_id": scene["id"],
            "shot_number": 1,
            "title": f"{marker} shot",
            "status": "פרומפט מוכן",
            "duration_seconds": 4,
        })
        asset = assets.create_asset({
            "project_id": project["id"],
            "asset_type": "אביזר",
            "name": f"{marker} prop",
            "description": marker,
        })
        shots.set_shot_assets(shot["id"], [asset["id"]])
        image = shots.create_media_result(shot["id"], {
            "media_type": "image",
            "url": f"https://example.com/{marker}.jpg",
            "status": "טיוטה",
        })
        video = shots.create_media_result(shot["id"], {
            "media_type": "video",
            "url": f"https://example.com/{marker}.mp4",
            "status": "טיוטה",
        })
        approvals.decide_media(shot["id"], image["id"], "approve", project["id"])
        approvals.decide_media(shot["id"], video["id"], "approve", project["id"])
        return {
            "project": project,
            "scene": scene,
            "shot": shot,
            "asset": asset,
            "image": image,
            "video": video,
        }

    def test_two_productions_remain_isolated_across_links_approvals_and_manifests(self):
        first = self._create_production("First Production", "first")
        second = self._create_production("Second Production", "second")

        with self.assertRaisesRegex(ValueError, "נכס מפרויקט אחר"):
            shots.set_shot_assets(first["shot"]["id"], [second["asset"]["id"]])
        with self.assertRaisesRegex(ValueError, "סצנה מפרויקט אחר"):
            shots.update_shot(first["shot"]["id"], {"scene_id": second["scene"]["id"]})
        with self.assertRaisesRegex(ValueError, "אינה שייכת לשוט"):
            approvals.decide_media(
                first["shot"]["id"], second["video"]["id"], "approve", first["project"]["id"]
            )

        first_after_rejections = shots.get_shot(first["shot"]["id"])
        self.assertEqual(first_after_rejections["scene_id"], first["scene"]["id"])
        self.assertEqual(
            {asset["id"] for asset in first_after_rejections["assets"]},
            {first["asset"]["id"]},
        )

        first_manifest = get_scene_preview_manifest(first["scene"]["id"])
        second_manifest = get_scene_preview_manifest(second["scene"]["id"])
        self.assertEqual(
            [item["shot_id"] for item in first_manifest["timeline"]],
            [first["shot"]["id"]],
        )
        self.assertEqual(
            [item["shot_id"] for item in second_manifest["timeline"]],
            [second["shot"]["id"]],
        )
        self.assertEqual(first_manifest["timeline"][0]["video_url"], first["video"]["url"])
        self.assertEqual(second_manifest["timeline"][0]["video_url"], second["video"]["url"])

        issues.create_issue({
            "project_id": second["project"]["id"],
            "shot_id": second["shot"]["id"],
            "severity": "critical",
            "category": "continuity",
            "message": "Second production blocker",
            "status": "פתוח",
        })

        first_preview = approvals.preview_batch_finalize(
            [first["shot"]["id"]], first["project"]["id"]
        )
        second_preview = approvals.preview_batch_finalize(
            [second["shot"]["id"]], second["project"]["id"]
        )
        self.assertEqual(first_preview["eligible"], 1)
        self.assertEqual(second_preview["eligible"], 0)

        finalized = approvals.finalize_shot(
            first["shot"]["id"], first["project"]["id"], "milestone A"
        )
        self.assertEqual(finalized["status"], "סופי")
        self.assertEqual(approvals.get_pipeline(second["shot"]["id"])["status"], "וידאו מאושר")

        self.assertEqual(
            {shot["id"] for shot in shots.list_shots(project_id=first["project"]["id"])},
            {first["shot"]["id"]},
        )
        self.assertEqual(
            {shot["id"] for shot in shots.list_shots(project_id=second["project"]["id"])},
            {second["shot"]["id"]},
        )


if __name__ == "__main__":
    unittest.main()
