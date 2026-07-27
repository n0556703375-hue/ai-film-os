import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.jobs import JobCompleteRequest, complete_job
from app.services.video_result_ingestion import ingest_completed_video_job


class VideoResultIngestionTests(unittest.TestCase):
    def setUp(self):
        self.job = {
            "id": 17,
            "shot_id": 8,
            "job_type": "video",
            "payload": {
                "source_image_media_id": 4,
                "prompt_version_id": 6,
                "selected_model_profile": "cinematic",
                "model_selection_reason": "long_or_complex_motion",
                "duration_seconds": 12,
                "camera_motion": "slow orbit",
                "audio_mode": "ambient",
                "aspect_ratio": "16:9",
            },
        }

    @patch("app.services.video_result_ingestion.shots.create_media_result")
    @patch("app.services.video_result_ingestion.shots.list_media_results", return_value=[])
    def test_creates_draft_video_media_with_trace_metadata(self, _list_media, create_media):
        create_media.return_value = {"id": 31, "status": "טיוטה"}

        result = ingest_completed_video_job(
            self.job,
            {"url": "https://cdn.example.com/video.mp4", "provider": "provider", "model": "model-v1"},
        )

        self.assertEqual(result["id"], 31)
        payload = create_media.call_args.args[1]
        self.assertEqual(payload["media_type"], "video")
        self.assertEqual(payload["status"], "טיוטה")
        self.assertEqual(payload["prompt_version_id"], 6)
        self.assertEqual(payload["metadata"]["generation_job_id"], 17)
        self.assertEqual(payload["metadata"]["source_image_media_id"], 4)

    @patch("app.services.video_result_ingestion.shots.create_media_result")
    @patch("app.services.video_result_ingestion.shots.list_media_results")
    def test_repeated_callback_reuses_existing_media_result(self, list_media, create_media):
        existing = {
            "id": 31,
            "media_type": "video",
            "metadata": {"generation_job_id": 17},
        }
        list_media.return_value = [existing]

        result = ingest_completed_video_job(self.job, {"url": "https://cdn.example.com/video.mp4"})

        self.assertEqual(result, existing)
        create_media.assert_not_called()

    def test_rejects_missing_or_unsafe_result_url(self):
        with self.assertRaises(ValueError):
            ingest_completed_video_job(self.job, {"url": "file:///tmp/video.mp4"})

    @patch("app.api.jobs.repo.complete_job")
    @patch("app.api.jobs.ingest_completed_video_job")
    @patch("app.api.jobs.repo.get_job")
    def test_completion_returns_stored_media_result(self, get_job, ingest, complete):
        get_job.return_value = self.job
        ingest.return_value = {"id": 31, "status": "טיוטה"}
        complete.return_value = {**self.job, "status": "completed"}

        response = complete_job(
            17,
            JobCompleteRequest(result={"url": "https://cdn.example.com/video.mp4"}),
        )

        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["media_result"]["id"], 31)

    @patch("app.api.jobs.repo.complete_job")
    @patch("app.api.jobs.ingest_completed_video_job", side_effect=ValueError("bad result"))
    @patch("app.api.jobs.repo.get_job")
    def test_invalid_video_result_does_not_complete_job(self, get_job, _ingest, complete):
        get_job.return_value = self.job

        with self.assertRaises(HTTPException) as raised:
            complete_job(17, JobCompleteRequest(result={}))

        self.assertEqual(raised.exception.status_code, 409)
        complete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
