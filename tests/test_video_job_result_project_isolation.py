import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import jobs, projects, scenes, shots
from app.services.video_result_ingestion import ingest_completed_video_job


class VideoJobResultProjectIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()

        self.first = self._create_production("First")
        self.second = self._create_production("Second")

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()

    def _create_production(self, marker: str):
        project = projects.create_project({
            "name": f"{marker} Production",
            "description": "",
            "visual_style": "",
            "rules": "",
        })
        scene = scenes.create_scene({
            "project_id": project["id"],
            "scene_number": 1,
            "title": f"{marker} Scene",
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
            "title": f"{marker} Shot",
            "status": "תמונה מאושרת",
        })
        job, created = jobs.enqueue_job(
            project["id"],
            shot["id"],
            "video",
            {"selected_model_profile": "test-model"},
            f"{marker.lower()}-video-job-key",
        )
        self.assertTrue(created)
        return {"project": project, "scene": scene, "shot": shot, "job": job}

    def test_jobs_and_completed_results_remain_isolated_between_projects(self):
        first_media = ingest_completed_video_job(
            self.first["job"],
            {"url": "https://example.com/first.mp4", "provider": "test"},
        )
        second_media = ingest_completed_video_job(
            self.second["job"],
            {"url": "https://example.com/second.mp4", "provider": "test"},
        )

        self.assertEqual(
            {job["id"] for job in jobs.list_jobs(project_id=self.first["project"]["id"])},
            {self.first["job"]["id"]},
        )
        self.assertEqual(
            {job["id"] for job in jobs.list_jobs(project_id=self.second["project"]["id"])},
            {self.second["job"]["id"]},
        )
        self.assertEqual(
            {media["id"] for media in shots.list_media_results(self.first["shot"]["id"])},
            {first_media["id"]},
        )
        self.assertEqual(
            {media["id"] for media in shots.list_media_results(self.second["shot"]["id"])},
            {second_media["id"]},
        )

    def test_tampered_job_project_is_rejected_without_creating_media(self):
        tampered_job = {
            **self.first["job"],
            "project_id": self.second["project"]["id"],
        }

        with self.assertRaisesRegex(ValueError, "אינם שייכים לאותו פרויקט"):
            ingest_completed_video_job(
                tampered_job,
                {"url": "https://example.com/tampered.mp4"},
            )

        self.assertEqual(shots.list_media_results(self.first["shot"]["id"]), [])
        self.assertEqual(shots.list_media_results(self.second["shot"]["id"]), [])


if __name__ == "__main__":
    unittest.main()
