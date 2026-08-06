"""Tests for app/services/sync_provider.py

Covers: submit_sync_job(), check_sync_job(), apply_lip_sync(),
and check_sync_connection().
No real API keys are used — all HTTP calls are mocked.
"""
import json
import unittest
from unittest.mock import patch

import httpx

from app.core.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post_resp(status_code: int, body: dict) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        request=httpx.Request("POST", "https://api.sync.so/v2/generate"),
    )


def _get_resp(status_code: int, body: dict, job_id: str = "job-123") -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", f"https://api.sync.so/v2/generate/{job_id}"),
    )


class _FakeHttpClient:
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
# submit_sync_job()
# ---------------------------------------------------------------------------

class SubmitSyncJobTests(unittest.TestCase):
    def setUp(self):
        self._orig_key = settings.sync_api_key
        self._orig_base = settings.sync_api_base
        settings.sync_api_key = "test-sync-key"
        settings.sync_api_base = "https://api.sync.so"

    def tearDown(self):
        settings.sync_api_key = self._orig_key
        settings.sync_api_base = self._orig_base

    def test_missing_key_raises_not_configured(self):
        from app.services.sync_provider import SyncProviderNotConfigured, submit_sync_job
        settings.sync_api_key = ""
        with self.assertRaises(SyncProviderNotConfigured):
            submit_sync_job("https://video.example.com/v.mp4", "https://audio.example.com/a.mp3")

    def test_successful_submit_returns_job_id(self):
        from app.services.sync_provider import submit_sync_job
        resp = _post_resp(202, {"id": "job-abc"})
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            job_id = submit_sync_job("https://v.example.com/v.mp4", "https://a.example.com/a.mp3")
        self.assertEqual(job_id, "job-abc")

    def test_job_id_field_alternative_accepted(self):
        from app.services.sync_provider import submit_sync_job
        resp = _post_resp(200, {"job_id": "job-alt"})
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            job_id = submit_sync_job("https://v.example.com/v.mp4", "https://a.example.com/a.mp3")
        self.assertEqual(job_id, "job-alt")

    def test_401_raises_not_configured(self):
        from app.services.sync_provider import SyncProviderNotConfigured, submit_sync_job
        resp = _post_resp(401, {"error": "unauthorized"})
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            with self.assertRaises(SyncProviderNotConfigured):
                submit_sync_job("https://v.example.com/v.mp4", "https://a.example.com/a.mp3")

    def test_500_raises_runtime_error(self):
        from app.services.sync_provider import submit_sync_job
        resp = _post_resp(500, {"error": "server error"})
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            with self.assertRaises(RuntimeError):
                submit_sync_job("https://v.example.com/v.mp4", "https://a.example.com/a.mp3")

    def test_missing_job_id_in_response_raises(self):
        from app.services.sync_provider import submit_sync_job
        resp = _post_resp(202, {})
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            with self.assertRaises(RuntimeError):
                submit_sync_job("https://v.example.com/v.mp4", "https://a.example.com/a.mp3")


# ---------------------------------------------------------------------------
# check_sync_job()
# ---------------------------------------------------------------------------

class CheckSyncJobTests(unittest.TestCase):
    def setUp(self):
        self._orig_key = settings.sync_api_key
        self._orig_base = settings.sync_api_base
        settings.sync_api_key = "test-sync-key"
        settings.sync_api_base = "https://api.sync.so"

    def tearDown(self):
        settings.sync_api_key = self._orig_key
        settings.sync_api_base = self._orig_base

    def test_completed_status_returns_output_url(self):
        from app.services.sync_provider import check_sync_job
        resp = _get_resp(200, {"status": "COMPLETED", "outputUrl": "https://cdn.sync.so/out.mp4"})
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = check_sync_job("job-123")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["output_url"], "https://cdn.sync.so/out.mp4")

    def test_completed_with_snake_case_field(self):
        from app.services.sync_provider import check_sync_job
        resp = _get_resp(200, {"status": "COMPLETED", "output_url": "https://cdn.sync.so/out2.mp4"})
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = check_sync_job("job-123")
        self.assertEqual(result["output_url"], "https://cdn.sync.so/out2.mp4")

    def test_pending_status_returns_pending(self):
        from app.services.sync_provider import check_sync_job
        resp = _get_resp(200, {"status": "PROCESSING"})
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = check_sync_job("job-123")
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["output_url"], "")

    def test_failed_status_returns_error(self):
        from app.services.sync_provider import check_sync_job
        resp = _get_resp(200, {"status": "FAILED", "error": "audio too short"})
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = check_sync_job("job-123")
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("audio too short", result["error"])

    def test_error_status_treated_as_failed(self):
        from app.services.sync_provider import check_sync_job
        resp = _get_resp(200, {"status": "ERROR", "error": "server crash"})
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = check_sync_job("job-123")
        self.assertEqual(result["status"], "FAILED")

    def test_non_200_response_raises_runtime_error(self):
        from app.services.sync_provider import check_sync_job
        resp = _get_resp(503, {})
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            with self.assertRaises(RuntimeError):
                check_sync_job("job-123")

    def test_completed_without_url_raises(self):
        from app.services.sync_provider import check_sync_job
        resp = _get_resp(200, {"status": "COMPLETED"})
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            with self.assertRaises(RuntimeError):
                check_sync_job("job-123")


# ---------------------------------------------------------------------------
# apply_lip_sync()
# ---------------------------------------------------------------------------

class ApplyLipSyncTests(unittest.TestCase):
    def setUp(self):
        self._orig_key = settings.sync_api_key
        self._orig_base = settings.sync_api_base
        settings.sync_api_key = "test-sync-key"
        settings.sync_api_base = "https://api.sync.so"

    def tearDown(self):
        settings.sync_api_key = self._orig_key
        settings.sync_api_base = self._orig_base

    def test_successful_sync_returns_synced_url(self):
        from app.services.sync_provider import apply_lip_sync

        submit_resp = _post_resp(202, {"id": "job-sync-1"})
        poll_resp = _get_resp(200, {"status": "COMPLETED", "outputUrl": "https://cdn.sync.so/synced.mp4"})

        class _TwoPhaseClient:
            _calls = 0

            def __init__(self, timeout=None):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, *, json=None, headers=None):
                return submit_resp

            def get(self, url, *, headers=None):
                return poll_resp

        with patch("app.services.sync_provider.httpx.Client", _TwoPhaseClient):
            url = apply_lip_sync(
                "https://v.example.com/v.mp4",
                "https://a.example.com/a.mp3",
                sleep=lambda _: None,
            )

        self.assertEqual(url, "https://cdn.sync.so/synced.mp4")

    def test_failed_job_raises_runtime_error(self):
        from app.services.sync_provider import apply_lip_sync

        submit_resp = _post_resp(202, {"id": "job-fail"})
        poll_resp = _get_resp(200, {"status": "FAILED", "error": "mismatch"})

        class _FailClient:
            def __init__(self, timeout=None):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, *, json=None, headers=None):
                return submit_resp

            def get(self, url, *, headers=None):
                return poll_resp

        with patch("app.services.sync_provider.httpx.Client", _FailClient):
            with self.assertRaises(RuntimeError):
                apply_lip_sync(
                    "https://v.example.com/v.mp4",
                    "https://a.example.com/a.mp3",
                    sleep=lambda _: None,
                )

    def test_missing_key_raises_not_configured(self):
        from app.services.sync_provider import SyncProviderNotConfigured, apply_lip_sync
        settings.sync_api_key = ""
        with self.assertRaises(SyncProviderNotConfigured):
            apply_lip_sync("https://v.example.com/v.mp4", "https://a.example.com/a.mp3")


# ---------------------------------------------------------------------------
# check_sync_connection()
# ---------------------------------------------------------------------------

class CheckSyncConnectionTests(unittest.TestCase):
    def setUp(self):
        self._orig_key = settings.sync_api_key
        self._orig_base = settings.sync_api_base
        settings.sync_api_base = "https://api.sync.so"

    def tearDown(self):
        settings.sync_api_key = self._orig_key
        settings.sync_api_base = self._orig_base

    def test_missing_key_returns_not_configured(self):
        from app.services.sync_provider import check_sync_connection
        settings.sync_api_key = ""
        result = check_sync_connection()
        self.assertFalse(result["connected"])
        self.assertEqual(result["status"], "not_configured")

    def test_404_probe_confirms_connection(self):
        from app.services.sync_provider import check_sync_connection
        settings.sync_api_key = "test-key"
        resp = _get_resp(404, {}, job_id="probe-ai-film-os")

        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = check_sync_connection()

        self.assertTrue(result["connected"])
        self.assertEqual(result["status"], "connected")

    def test_200_probe_confirms_connection(self):
        from app.services.sync_provider import check_sync_connection
        settings.sync_api_key = "test-key"
        resp = _get_resp(200, {}, job_id="probe-ai-film-os")

        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = check_sync_connection()

        self.assertTrue(result["connected"])

    def test_401_probe_marks_invalid_key(self):
        from app.services.sync_provider import check_sync_connection
        settings.sync_api_key = "bad-key"
        resp = _get_resp(401, {}, job_id="probe-ai-film-os")

        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = check_sync_connection()

        self.assertFalse(result["connected"])
        self.assertEqual(result["status"], "invalid_key")

    def test_403_probe_marks_invalid_key(self):
        from app.services.sync_provider import check_sync_connection
        settings.sync_api_key = "bad-key"
        resp = _get_resp(403, {}, job_id="probe-ai-film-os")

        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = check_sync_connection()

        self.assertFalse(result["connected"])
        self.assertEqual(result["status"], "invalid_key")

    def test_500_returns_provider_error(self):
        from app.services.sync_provider import check_sync_connection
        settings.sync_api_key = "test-key"
        resp = _get_resp(500, {}, job_id="probe-ai-film-os")

        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = check_sync_connection()

        self.assertFalse(result["connected"])
        self.assertEqual(result["status"], "provider_error")

    def test_network_error_returns_network_error(self):
        from app.services.sync_provider import check_sync_connection
        settings.sync_api_key = "test-key"

        class _NetworkErrorClient:
            def __init__(self, timeout=None):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url, *, headers=None):
                raise httpx.ConnectError("connection refused", request=httpx.Request("GET", url))

        with patch("app.services.sync_provider.httpx.Client", _NetworkErrorClient):
            result = check_sync_connection()

        self.assertFalse(result["connected"])
        self.assertEqual(result["status"], "network_error")


# ---------------------------------------------------------------------------
# Worker integration: _maybe_apply_sync
# ---------------------------------------------------------------------------

class MaybeApplySyncTests(unittest.TestCase):
    def setUp(self):
        self._orig_key = settings.sync_api_key
        settings.sync_api_key = "test-sync-key"

    def tearDown(self):
        settings.sync_api_key = self._orig_key

    def test_non_dialogue_mode_skips_sync(self):
        from app.worker import _maybe_apply_sync
        result = _maybe_apply_sync(
            "https://kling.example.com/v.mp4",
            {"audio_mode": "none", "audio_url": "https://audio.example.com/a.mp3"},
        )
        self.assertEqual(result, "https://kling.example.com/v.mp4")

    def test_dialogue_without_audio_url_skips_sync(self):
        from app.worker import _maybe_apply_sync
        result = _maybe_apply_sync(
            "https://kling.example.com/v.mp4",
            {"audio_mode": "dialogue", "audio_url": ""},
        )
        self.assertEqual(result, "https://kling.example.com/v.mp4")

    def test_dialogue_without_sync_key_skips_sync(self):
        from app.worker import _maybe_apply_sync
        settings.sync_api_key = ""
        result = _maybe_apply_sync(
            "https://kling.example.com/v.mp4",
            {"audio_mode": "dialogue", "audio_url": "https://audio.example.com/a.mp3"},
        )
        self.assertEqual(result, "https://kling.example.com/v.mp4")

    def test_sync_failure_returns_original_kling_url(self):
        from app.worker import _maybe_apply_sync

        def _fail(*a, **kw):
            raise RuntimeError("Sync.so server exploded")

        with patch("app.services.sync_provider.apply_lip_sync", _fail):
            result = _maybe_apply_sync(
                "https://kling.example.com/v.mp4",
                {"audio_mode": "dialogue", "audio_url": "https://audio.example.com/a.mp3"},
            )

        self.assertEqual(result, "https://kling.example.com/v.mp4")

    def test_successful_sync_returns_synced_url(self):
        from app.worker import _maybe_apply_sync

        def _ok(video_url, audio_url, **kw):
            return "https://cdn.sync.so/synced.mp4"

        with patch("app.services.sync_provider.apply_lip_sync", _ok):
            result = _maybe_apply_sync(
                "https://kling.example.com/v.mp4",
                {"audio_mode": "dialogue", "audio_url": "https://audio.example.com/a.mp3"},
            )

        self.assertEqual(result, "https://cdn.sync.so/synced.mp4")


if __name__ == "__main__":
    unittest.main()
