import unittest
from unittest.mock import call, patch

from app.api.jobs import JobCreateRequest, enqueue_job
from app.services.video_result_ingestion import ingest_completed_video_job


class VideoJobProjectIsolationTests(unittest.TestCase):
    @patch("app.api.jobs.repo.enqueue_job")
    def test_two_projects_enqueue_jobs_under_their_own_shots(self, enqueue):
        jobs = {
            (7, 701): {
                "id": 71,
                "project_id": 7,
                "shot_id": 701,
                "job_type": "video",
                "status": "queued",
            },
            (8, 801): {
                "id": 81,
                "project_id": 8,
                "shot_id": 801,
                "job_type": "video",
                "status": "queued",
            },
        }

        def persist(
            project_id,
            shot_id,
            job_type,
            payload,
            idempotency_key,
            max_attempts,
            estimated_cost_usd,
        ):
            self.assertEqual(job_type, "video")
            self.assertEqual(payload["project_marker"], project_id)
            self.assertIn(str(project_id), idempotency_key)
            self.assertEqual(max_attempts, 3)
            self.assertEqual(estimated_cost_usd, 0)
            return jobs[(project_id, shot_id)], True

        enqueue.side_effect = persist

        first = enqueue_job(
            JobCreateRequest(
                project_id=7,
                shot_id=701,
                job_type="video",
                payload={"project_marker": 7, "source_image_media_id": 7001},
                idempotency_key="project-7-shot-701-video",
            )
        )
        second = enqueue_job(
            JobCreateRequest(
                project_id=8,
                shot_id=801,
                job_type="video",
                payload={"project_marker": 8, "source_image_media_id": 8001},
                idempotency_key="project-8-shot-801-video",
            )
        )

        self.assertEqual(first["job"]["project_id"], 7)
        self.assertEqual(first["job"]["shot_id"], 701)
        self.assertEqual(second["job"]["project_id"], 8)
        self.assertEqual(second["job"]["shot_id"], 801)
        self.assertEqual(enqueue.call_args_list[0].args[:2], (7, 701))
        self.assertEqual(enqueue.call_args_list[1].args[:2], (8, 801))

    @patch("app.services.video_result_ingestion.shots.create_media_result")
    @patch("app.services.video_result_ingestion.shots.list_media_results")
    @patch("app.services.video_result_ingestion.shots.get_shot")
    def test_completed_results_stay_with_the_originating_project_shot(
        self,
        get_shot,
        list_media_results,
        create_media_result,
    ):
        shots = {
            701: {"id": 701, "project_id": 7},
            801: {"id": 801, "project_id": 8},
        }
        get_shot.side_effect = lambda shot_id: shots.get(shot_id)
        list_media_results.side_effect = lambda shot_id: []
        create_media_result.side_effect = lambda shot_id, data: {
            "id": shot_id * 10 + 1,
            "shot_id": shot_id,
            **data,
        }

        first = ingest_completed_video_job(
            {
                "id": 71,
                "project_id": 7,
                "shot_id": 701,
                "job_type": "video",
                "payload": {"source_image_media_id": 7001},
            },
            {"url": "https://cdn.example.com/project-7.mp4"},
        )
        second = ingest_completed_video_job(
            {
                "id": 81,
                "project_id": 8,
                "shot_id": 801,
                "job_type": "video",
                "payload": {"source_image_media_id": 8001},
            },
            {"url": "https://cdn.example.com/project-8.mp4"},
        )

        self.assertEqual(get_shot.call_args_list, [call(701), call(801)])
        self.assertEqual(list_media_results.call_args_list, [call(701), call(801)])
        self.assertEqual(create_media_result.call_args_list[0].args[0], 701)
        self.assertEqual(create_media_result.call_args_list[1].args[0], 801)
        self.assertEqual(first["shot_id"], 701)
        self.assertEqual(second["shot_id"], 801)
        self.assertEqual(first["metadata"]["generation_job_id"], 71)
        self.assertEqual(second["metadata"]["generation_job_id"], 81)
        self.assertEqual(first["metadata"]["source_image_media_id"], 7001)
        self.assertEqual(second["metadata"]["source_image_media_id"], 8001)


if __name__ == "__main__":
    unittest.main()
