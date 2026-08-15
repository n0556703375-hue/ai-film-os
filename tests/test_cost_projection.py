"""Coverage for the project-wide cost projection surfaced in
GET /api/jobs/cost-summary (app/api/jobs.py) and its underlying helper
(app/services/video_provider.estimate_default_shot_cost_usd).

The existing estimated_cost_usd/actual_cost_usd fields only ever reflect
media_jobs rows that already exist, which is always zero for a project
that hasn't generated anything yet. This projection answers a different
question — "roughly what will this project cost" — from shot count alone,
before any job exists, and must never be confused with real job data.
"""

import os
import tempfile
import unittest
from pathlib import Path

from app.api.jobs import cost_summary
from app.core.config import settings
from app.database.connection import init_db
from app.repositories import projects, scenes, shots
from app.services.kling_provider import KlingProvider
from app.services.video_provider import (
    DisabledVideoProvider,
    VideoGenerationRequest,
    estimate_default_shot_cost_usd,
)


class _EnvIsolatedTestCase(unittest.TestCase):
    """get_video_provider() (app/services/video_provider.py) picks the
    provider *class* from the raw environment, but SeedanceProvider's own
    __init__ then reads settings.fal_api_key (a cached Settings attribute,
    not the environment) — both must be controlled for a deterministic
    provider selection *and* a successfully constructed instance.
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        self.original_fal_api_key = settings.fal_api_key
        self.original_fal_api_key_env = os.environ.get("FAL_API_KEY")
        self.original_kling_access_env = os.environ.get("KLING_ACCESS_KEY")
        self.original_kling_secret_env = os.environ.get("KLING_SECRET_KEY")
        settings.fal_api_key = ""
        os.environ.pop("FAL_API_KEY", None)
        os.environ.pop("KLING_ACCESS_KEY", None)
        os.environ.pop("KLING_SECRET_KEY", None)
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()

    def tearDown(self):
        settings.database_path = self.original_db
        settings.fal_api_key = self.original_fal_api_key
        for key, value in (
            ("FAL_API_KEY", self.original_fal_api_key_env),
            ("KLING_ACCESS_KEY", self.original_kling_access_env),
            ("KLING_SECRET_KEY", self.original_kling_secret_env),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tempdir.cleanup()

    def configure_seedance(self):
        settings.fal_api_key = "test-fal-key"
        os.environ["FAL_API_KEY"] = "test-fal-key"


class DefaultShotCostEstimateTests(_EnvIsolatedTestCase):
    def test_no_provider_configured_estimates_zero(self):
        self.assertEqual(estimate_default_shot_cost_usd(), 0.0)

    def test_seedance_configured_estimates_using_its_per_second_rate(self):
        self.configure_seedance()
        # 5s default duration at the cinematic model's $0.3034/s rate.
        self.assertAlmostEqual(estimate_default_shot_cost_usd(), 1.517)

    def test_kling_configured_estimates_using_its_per_video_rate(self):
        os.environ["KLING_ACCESS_KEY"] = "test-access"
        os.environ["KLING_SECRET_KEY"] = "test-secret"
        # Kling prices per 5s unit, not per second; 5s is exactly one unit
        # of the cinematic model's (kling-v2-master) $0.045 rate.
        self.assertAlmostEqual(estimate_default_shot_cost_usd(), 0.045)

    def test_kling_provider_cost_for_matches_its_own_estimator(self):
        provider = KlingProvider()
        request = VideoGenerationRequest(image_url="", prompt="", duration_seconds=5.0)
        self.assertGreater(provider.cost_for(request), 0)

    def test_disabled_provider_never_invents_a_cost(self):
        provider = DisabledVideoProvider()
        request = VideoGenerationRequest(image_url="", prompt="", duration_seconds=5.0)
        self.assertEqual(provider.cost_for(request), 0.0)


class CostSummaryProjectionTests(_EnvIsolatedTestCase):
    def setUp(self):
        super().setUp()
        project = projects.create_project(
            {"name": "Projection", "description": "", "visual_style": "", "rules": ""}
        )
        scene = scenes.create_scene({
            "project_id": project["id"],
            "scene_number": 1,
            "title": "Scene",
            "status": "מתוכנן",
            "story_goal": "", "emotion": "", "conflict": "",
            "beginning": "", "ending": "", "notes": "",
        })
        self.project_id = project["id"]
        for number in range(1, 4):
            shots.create_shot({
                "project_id": project["id"],
                "scene_id": scene["id"],
                "shot_number": number,
                "title": f"Shot {number}",
            })

    def test_projection_scales_with_shot_count_and_provider_rate(self):
        self.configure_seedance()
        summary = cost_summary(self.project_id)
        self.assertEqual(summary["shot_count"], 3)
        self.assertAlmostEqual(summary["projected_shot_cost_usd"], 1.517)
        self.assertAlmostEqual(summary["projected_total_cost_usd"], 3 * 1.517)

    def test_projection_is_zero_with_no_provider_configured(self):
        summary = cost_summary(self.project_id)
        self.assertEqual(summary["shot_count"], 3)
        self.assertEqual(summary["projected_shot_cost_usd"], 0.0)
        self.assertEqual(summary["projected_total_cost_usd"], 0.0)

    def test_projection_never_touches_real_job_cost_fields(self):
        # The projection must be purely additive — it must never alter the
        # existing job-derived fields that reflect real media_jobs rows.
        summary = cost_summary(self.project_id)
        self.assertEqual(summary["job_count"], 0)
        self.assertEqual(summary["estimated_cost_usd"], 0)
        self.assertEqual(summary["actual_cost_usd"], 0)

    def test_project_with_no_shots_projects_zero(self):
        self.configure_seedance()
        empty_project = projects.create_project(
            {"name": "Empty", "description": "", "visual_style": "", "rules": ""}
        )
        summary = cost_summary(empty_project["id"])
        self.assertEqual(summary["shot_count"], 0)
        self.assertEqual(summary["projected_total_cost_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
