"""Tests for app/services/kling_provider.py

Covers: submit(), check_task(), helpers (_model_for, _camera_motion_to_kling,
_estimate_cost), and the get_video_provider() Kling routing path.
No real API keys are used — all HTTP calls are mocked.
"""
import json
import os
import unittest
from unittest.mock import patch

import httpx

from app.core.config import settings
from app.services.video_provider import VideoGenerationRequest, VideoProviderNotConfigured


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _req(**kwargs):
    defaults = dict(
        image_url="https://example.com/frame.jpg",
        prompt="Desert sunset, golden hour",
        duration_seconds=5.0,
        camera_motion="pan",
        audio_mode="none",
        aspect_ratio="16:9",
        model_profile="cinematic",
    )
    defaults.update(kwargs)
    return VideoGenerationRequest(**defaults)


def _post_resp(status_code: int, body: dict) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        request=httpx.Request("POST", "https://api.klingai.com/v1/videos/image2video"),
    )


def _get_resp(status_code: int, body: dict, task_id: str = "task-123") -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        request=httpx.Request(
            "GET",
            f"https://api.klingai.com/v1/videos/image2video/{task_id}",
        ),
    )


class _FakeHttpClient:
    """Fake httpx.Client that returns a canned response for any verb."""

    def __init__(self, response: httpx.Response, timeout=None):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, *, json=None, headers=None):
        return self._response

    def get(self, url, *, headers=None):
        return self._response


# ---------------------------------------------------------------------------
# Model profile mapping
# ---------------------------------------------------------------------------

class KlingModelProfileTests(unittest.TestCase):
    def test_fast_maps_to_v2(self):
        from app.services.kling_provider import _model_for
        self.assertEqual(_model_for("fast"), "kling-v2")

    def test_cinematic_maps_to_v3(self):
        from app.services.kling_provider import _model_for
        self.assertEqual(_model_for("cinematic"), "kling-v3")

    def test_high_fidelity_maps_to_v3_omni(self):
        from app.services.kling_provider import _model_for
        self.assertEqual(_model_for("high_fidelity"), "kling-v3-omni")

    def test_auto_maps_to_v3(self):
        from app.services.kling_provider import _model_for
        self.assertEqual(_model_for("auto"), "kling-v3")

    def test_unknown_profile_falls_back_to_default_model_setting(self):
        from app.services.kling_provider import _model_for
        orig = settings.kling_default_model
        settings.kling_default_model = "kling-v3"
        try:
            self.assertEqual(_model_for("nonexistent_profile"), "kling-v3")
        finally:
            settings.kling_default_model = orig


# ---------------------------------------------------------------------------
# Camera motion mapping
# ---------------------------------------------------------------------------

class KlingCameraMotionTests(unittest.TestCase):
    def _motion(self, value):
        from app.services.kling_provider import _camera_motion_to_kling
        return _camera_motion_to_kling(value)

    def test_tracking_maps_to_move_forward(self):
        self.assertEqual(self._motion("tracking shot"), "move_forward")

    def test_orbit_maps_to_orbit_left(self):
        self.assertEqual(self._motion("orbit"), "orbit_left")

    def test_crane_maps_to_move_up(self):
        self.assertEqual(self._motion("crane"), "move_up")

    def test_drone_maps_to_move_up(self):
        self.assertEqual(self._motion("drone shot"), "move_up")

    def test_handheld_maps_to_shake(self):
        self.assertEqual(self._motion("handheld"), "shake")

    def test_zoom_maps_to_zoom_in(self):
        self.assertEqual(self._motion("zoom"), "zoom_in")

    def test_pan_maps_to_pan_left(self):
        self.assertEqual(self._motion("pan"), "pan_left")

    def test_tilt_maps_to_tilt_up(self):
        self.assertEqual(self._motion("tilt"), "tilt_up")

    def test_unknown_motion_defaults_to_static(self):
        self.assertEqual(self._motion("random dolly xyz"), "static")

    def test_empty_string_defaults_to_static(self):
        self.assertEqual(self._motion(""), "static")


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

class KlingCostEstimateTests(unittest.TestCase):
    def _cost(self, dur, model):
        from app.services.kling_provider import _estimate_cost
        return _estimate_cost(dur, model)

    def test_v2_five_second_base_cost(self):
        self.assertAlmostEqual(self._cost(5.0, "kling-v2"), 0.028, places=4)

    def test_v3_five_second_base_cost(self):
        self.assertAlmostEqual(self._cost(5.0, "kling-v3"), 0.045, places=4)

    def test_v3_omni_five_second_base_cost(self):
        self.assertAlmostEqual(self._cost(5.0, "kling-v3-omni"), 0.065, places=4)

    def test_duration_below_five_clamps_to_one_unit(self):
        self.assertEqual(self._cost(1.0, "kling-v3"), self._cost(5.0, "kling-v3"))

    def test_ten_seconds_costs_twice_five_seconds(self):
        self.assertAlmostEqual(self._cost(10.0, "kling-v3"), 0.09, places=4)

    def test_unknown_model_uses_v3_fallback_rate(self):
        self.assertAlmostEqual(self._cost(5.0, "kling-future"), 0.045, places=4)


# ---------------------------------------------------------------------------
# KlingProvider.submit()
# ---------------------------------------------------------------------------

class KlingProviderSubmitTests(unittest.TestCase):
    def setUp(self):
        self._orig_key = settings.kling_api_key
        self._orig_base = settings.kling_api_base
        settings.kling_api_key = "test-key"
        settings.kling_api_base = "https://api.klingai.com"

    def tearDown(self):
        settings.kling_api_key = self._orig_key
        settings.kling_api_base = self._orig_base

    def test_missing_key_raises_not_configured(self):
        from app.services.kling_provider import KlingProvider
        settings.kling_api_key = ""
        provider = KlingProvider()
        with self.assertRaises(VideoProviderNotConfigured):
            provider.submit(_req())

    def test_successful_submit_returns_task_id(self):
        from app.services.kling_provider import KlingProvider
        resp = _post_resp(202, {"data": {"task_id": "task-abc"}})
        with patch("app.services.kling_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            task_id = KlingProvider().submit(_req())
        self.assertEqual(task_id, "task-abc")

    def test_task_id_at_top_level_is_accepted(self):
        from app.services.kling_provider import KlingProvider
        resp = _post_resp(200, {"task_id": "task-top"})
        with patch("app.services.kling_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            task_id = KlingProvider().submit(_req())
        self.assertEqual(task_id, "task-top")

    def test_401_raises_not_configured(self):
        from app.services.kling_provider import KlingProvider
        resp = _post_resp(401, {"error": "unauthorized"})
        with patch("app.services.kling_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            with self.assertRaises(VideoProviderNotConfigured):
                KlingProvider().submit(_req())

    def test_500_raises_runtime_error(self):
        from app.services.kling_provider import KlingProvider
        resp = _post_resp(500, {"error": "server error"})
        with patch("app.services.kling_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            with self.assertRaises(RuntimeError):
                KlingProvider().submit(_req())

    def test_missing_task_id_raises_runtime_error(self):
        from app.services.kling_provider import KlingProvider
        resp = _post_resp(202, {"data": {}})
        with patch("app.services.kling_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            with self.assertRaises(RuntimeError):
                KlingProvider().submit(_req())

    def test_dialogue_mode_includes_with_audio_flag(self):
        from app.services.kling_provider import KlingProvider
        captured = []

        class _CapturingClient:
            def __init__(self, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, *, json=None, headers=None):
                captured.append(json)
                return _post_resp(202, {"data": {"task_id": "t1"}})

        with patch("app.services.kling_provider.httpx.Client", _CapturingClient):
            KlingProvider().submit(_req(audio_mode="dialogue"))

        self.assertTrue(captured[0].get("with_audio"))

    def test_non_dialogue_mode_omits_with_audio(self):
        from app.services.kling_provider import KlingProvider
        captured = []

        class _CapturingClient:
            def __init__(self, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, *, json=None, headers=None):
                captured.append(json)
                return _post_resp(202, {"data": {"task_id": "t2"}})

        with patch("app.services.kling_provider.httpx.Client", _CapturingClient):
            KlingProvider().submit(_req(audio_mode="none"))

        self.assertNotIn("with_audio", captured[0])


# ---------------------------------------------------------------------------
# KlingProvider.check_task()
# ---------------------------------------------------------------------------

class KlingProviderCheckTaskTests(unittest.TestCase):
    def setUp(self):
        self._orig_key = settings.kling_api_key
        self._orig_base = settings.kling_api_base
        settings.kling_api_key = "test-key"
        settings.kling_api_base = "https://api.klingai.com"

    def tearDown(self):
        settings.kling_api_key = self._orig_key
        settings.kling_api_base = self._orig_base

    def test_succeed_status_returns_video_url(self):
        from app.services.kling_provider import KlingProvider
        resp = _get_resp(200, {
            "data": {
                "task_status": "succeed",
                "task_result": {"videos": [{"url": "https://cdn.kling.ai/video.mp4"}]},
            }
        })
        with patch("app.services.kling_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = KlingProvider().check_task("task-123")
        self.assertEqual(result["status"], "succeed")
        self.assertEqual(result["url"], "https://cdn.kling.ai/video.mp4")

    def test_pending_status_returns_pending(self):
        from app.services.kling_provider import KlingProvider
        resp = _get_resp(200, {"data": {"task_status": "processing"}})
        with patch("app.services.kling_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = KlingProvider().check_task("task-123")
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["url"], "")

    def test_failed_status_returns_reason(self):
        from app.services.kling_provider import KlingProvider
        resp = _get_resp(200, {
            "data": {"task_status": "failed", "task_status_msg": "out of quota"}
        })
        with patch("app.services.kling_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = KlingProvider().check_task("task-123")
        self.assertEqual(result["status"], "failed")
        self.assertIn("out of quota", result["reason"])

    def test_succeed_without_videos_raises(self):
        from app.services.kling_provider import KlingProvider
        resp = _get_resp(200, {
            "data": {"task_status": "succeed", "task_result": {"videos": []}}
        })
        with patch("app.services.kling_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            with self.assertRaises(RuntimeError):
                KlingProvider().check_task("task-123")

    def test_non_200_poll_raises_runtime_error(self):
        from app.services.kling_provider import KlingProvider
        resp = _get_resp(503, {})
        with patch("app.services.kling_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            with self.assertRaises(RuntimeError):
                KlingProvider().check_task("task-123")


# ---------------------------------------------------------------------------
# Provider name
# ---------------------------------------------------------------------------

class KlingProviderMetaTests(unittest.TestCase):
    def test_provider_name_attribute(self):
        from app.services.kling_provider import KlingProvider
        self.assertEqual(KlingProvider.name, "kling")


# ---------------------------------------------------------------------------
# get_video_provider() routing
# ---------------------------------------------------------------------------

class KlingGetVideoProviderRoutingTests(unittest.TestCase):
    def test_kling_provider_returned_when_env_key_is_set(self):
        with patch.dict(os.environ, {"KLING_API_KEY": "some-real-key"}):
            from importlib import reload
            import app.services.video_provider as vp
            reload(vp)
            provider = vp.get_video_provider()
        from app.services.kling_provider import KlingProvider
        self.assertIsInstance(provider, KlingProvider)

    def test_disabled_provider_returned_when_env_key_is_missing(self):
        env = {k: v for k, v in os.environ.items() if k != "KLING_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            from importlib import reload
            import app.services.video_provider as vp
            reload(vp)
            provider = vp.get_video_provider()
        from app.services.video_provider import DisabledVideoProvider
        self.assertIsInstance(provider, DisabledVideoProvider)


if __name__ == "__main__":
    unittest.main()
