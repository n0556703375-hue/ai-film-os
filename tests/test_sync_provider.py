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

    def test_failed_status_returns_sanitized_category_not_provider_text(self):
        from app.services.sync_provider import SyncErrorCategory, check_sync_job
        resp = _get_resp(200, {"status": "FAILED", "error": "audio too short"})
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = check_sync_job("job-123")
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["error_category"], SyncErrorCategory.JOB_FAILED)
        self.assertNotIn("audio too short", result["error"])
        self.assertNotIn("audio too short", str(result))

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

    def test_configured_key_is_indeterminate_not_connected(self):
        from app.services.sync_provider import check_sync_connection
        settings.sync_api_key = "test-key"

        result = check_sync_connection()

        self.assertFalse(result["connected"])
        self.assertEqual(result["status"], "indeterminate")

    def test_connection_check_never_claims_connected(self):
        from app.services.sync_provider import check_sync_connection

        for key in ("", "test-key", "bad-key"):
            with self.subTest(key=bool(key)):
                settings.sync_api_key = key
                result = check_sync_connection()
                self.assertFalse(result["connected"])
                self.assertNotEqual(result["status"], "connected")

    def test_fabricated_probe_404_can_no_longer_prove_credentials(self):
        """A 404 for an invented job ID must never read as a valid key."""
        from app.services.sync_provider import check_sync_connection
        settings.sync_api_key = "revoked-key"
        resp = _get_resp(404, {}, job_id="probe-ai-film-os")

        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = check_sync_connection()

        self.assertFalse(result["connected"])
        self.assertEqual(result["status"], "indeterminate")

    def test_connection_check_makes_no_network_call(self):
        """Fail-closed means no probe at all — and no risk of a billable call."""
        from app.services.sync_provider import check_sync_connection
        settings.sync_api_key = "test-key"

        calls = []

        class _ForbiddenClient:
            def __init__(self, **kwargs):
                calls.append("constructed")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url, *, headers=None):
                calls.append(url)
                raise AssertionError("check_sync_connection must not perform HTTP")

            def post(self, url, *, json=None, headers=None):
                calls.append(url)
                raise AssertionError("check_sync_connection must not perform HTTP")

        with patch("app.services.sync_provider.httpx.Client", _ForbiddenClient):
            check_sync_connection()

        self.assertEqual(calls, [])


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


# ---------------------------------------------------------------------------
# Sentinel redaction: nothing sensitive may reach exceptions, logs or results
# ---------------------------------------------------------------------------

# Distinctive sentinels. If any appears in an exception message, a log record
# or returned failure data, redaction has regressed.
SENTINEL_API_KEY = "sk-SENTINEL-APIKEY-do-not-leak"
SENTINEL_VIDEO_URL = "https://cdn.kling.example/SENTINEL-VIDEO.mp4?sig=SENTINELVIDEOSIG"
SENTINEL_AUDIO_URL = "https://cdn.audio.example/SENTINEL-AUDIO.mp3?sig=SENTINELAUDIOSIG"
SENTINEL_OUTPUT_URL = "https://cdn.sync.so/SENTINEL-OUTPUT.mp4?sig=SENTINELOUTSIG"
SENTINEL_BODY = "SENTINEL-PROVIDER-BODY-stack-trace-do-not-print"

_ALL_SENTINELS = (
    SENTINEL_API_KEY,
    SENTINEL_VIDEO_URL,
    SENTINEL_AUDIO_URL,
    SENTINEL_OUTPUT_URL,
    SENTINEL_BODY,
    "SENTINELVIDEOSIG",
    "SENTINELAUDIOSIG",
    "sig=",
)


class _SentinelBase(unittest.TestCase):
    def setUp(self):
        self._orig_key = settings.sync_api_key
        self._orig_base = settings.sync_api_base
        settings.sync_api_key = SENTINEL_API_KEY
        settings.sync_api_base = "https://api.sync.so"

    def tearDown(self):
        settings.sync_api_key = self._orig_key
        settings.sync_api_base = self._orig_base

    def assertNoSentinels(self, text: str, *, allow=()):
        for sentinel in _ALL_SENTINELS:
            if sentinel in allow:
                continue
            self.assertNotIn(sentinel, text)


class SyncExceptionRedactionTests(_SentinelBase):
    """Raised exceptions must never carry secrets, URLs or provider bodies."""

    def _submit_failure(self, status_code, body):
        from app.services.sync_provider import submit_sync_job

        resp = _post_resp(status_code, body)
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            with self.assertRaises(Exception) as captured:
                submit_sync_job(SENTINEL_VIDEO_URL, SENTINEL_AUDIO_URL)
        return captured.exception

    def test_provider_error_exception_is_clean(self):
        exc = self._submit_failure(500, {"error": SENTINEL_BODY})
        self.assertNoSentinels(str(exc))
        self.assertIn("500", str(exc))

    def test_invalid_credentials_exception_is_clean(self):
        exc = self._submit_failure(401, {"error": SENTINEL_BODY})
        self.assertNoSentinels(str(exc))

    def test_missing_job_id_exception_is_clean(self):
        exc = self._submit_failure(200, {"message": SENTINEL_BODY})
        self.assertNoSentinels(str(exc))

    def test_malformed_body_exception_is_clean(self):
        from app.services.sync_provider import submit_sync_job

        resp = httpx.Response(
            200,
            content=f"<html>{SENTINEL_BODY}</html>".encode(),
            headers={"content-type": "text/html"},
            request=httpx.Request("POST", "https://api.sync.so/v2/generate"),
        )
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            with self.assertRaises(Exception) as captured:
                submit_sync_job(SENTINEL_VIDEO_URL, SENTINEL_AUDIO_URL)
        self.assertNoSentinels(str(captured.exception))

    def test_network_error_exception_does_not_leak_request_url(self):
        from app.services.sync_provider import submit_sync_job

        class _NetworkErrorClient:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, *, json=None, headers=None):
                raise httpx.ConnectError(
                    f"connection refused for {SENTINEL_VIDEO_URL}",
                    request=httpx.Request("POST", url),
                )

        with patch("app.services.sync_provider.httpx.Client", _NetworkErrorClient):
            with self.assertRaises(Exception) as captured:
                submit_sync_job(SENTINEL_VIDEO_URL, SENTINEL_AUDIO_URL)

        self.assertNoSentinels(str(captured.exception))

    def test_apply_lip_sync_job_failure_exception_is_clean(self):
        from app.services.sync_provider import apply_lip_sync

        submit = _post_resp(200, {"id": "job-1"})
        failed = _get_resp(200, {"status": "FAILED", "error": SENTINEL_BODY})

        class _SeqClient:
            _responses = [submit, failed]

            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, *, json=None, headers=None):
                return type(self)._responses[0]

            def get(self, url, *, headers=None):
                return type(self)._responses[1]

        with patch("app.services.sync_provider.httpx.Client", _SeqClient):
            with self.assertRaises(Exception) as captured:
                apply_lip_sync(
                    SENTINEL_VIDEO_URL, SENTINEL_AUDIO_URL, sleep=lambda _s: None
                )

        self.assertNoSentinels(str(captured.exception))

    def test_exception_text_is_safe_for_media_jobs_last_error(self):
        """process_one_job persists str(exc); that string must stay sanitized."""
        exc = self._submit_failure(500, {"error": SENTINEL_BODY})
        persisted = str(exc)
        self.assertNoSentinels(persisted)
        self.assertNotIn(settings.sync_api_key, persisted)


class SyncReturnedDataRedactionTests(_SentinelBase):
    """Returned failure data must carry only stable categories."""

    def test_failed_result_contains_no_provider_text(self):
        from app.services.sync_provider import SyncErrorCategory, check_sync_job

        resp = _get_resp(200, {"status": "FAILED", "error": SENTINEL_BODY})
        with patch("app.services.sync_provider.httpx.Client",
                   lambda **kw: _FakeHttpClient(resp)):
            result = check_sync_job("job-1")

        self.assertEqual(result["error_category"], SyncErrorCategory.JOB_FAILED)
        self.assertNoSentinels(str(result))

    def test_connection_check_result_contains_no_api_key(self):
        from app.services.sync_provider import check_sync_connection

        result = check_sync_connection()
        self.assertNoSentinels(str(result))


class SyncLogRedactionTests(_SentinelBase):
    """_maybe_apply_sync must log only a stable sanitized category."""

    def _run_with_failure(self, exc_to_raise):
        from app.worker import _maybe_apply_sync

        def _boom(video_url, audio_url, **kwargs):
            raise exc_to_raise

        with patch("app.services.sync_provider.apply_lip_sync", _boom):
            with self.assertLogs("app.worker", level="WARNING") as captured:
                result = _maybe_apply_sync(
                    SENTINEL_VIDEO_URL,
                    {"audio_mode": "dialogue", "audio_url": SENTINEL_AUDIO_URL},
                    sleep=lambda _s: None,
                )
        return result, "\n".join(captured.output)

    def test_log_records_never_contain_sentinels(self):
        from app.services.sync_provider import SyncErrorCategory, SyncProviderError

        cases = [
            SyncProviderError(SyncErrorCategory.PROVIDER_ERROR, status_code=500),
            SyncProviderError(SyncErrorCategory.NETWORK_ERROR),
            RuntimeError(f"raw provider text {SENTINEL_BODY} {SENTINEL_VIDEO_URL}"),
            TimeoutError(f"timed out fetching {SENTINEL_OUTPUT_URL}"),
        ]
        for exc in cases:
            with self.subTest(exc=type(exc).__name__):
                result, logs = self._run_with_failure(exc)
                self.assertEqual(result, SENTINEL_VIDEO_URL)  # video preserved
                self.assertNoSentinels(logs)
                self.assertIn("category=", logs)

    def test_unexpected_exception_logs_stable_category(self):
        from app.services.sync_provider import SyncErrorCategory

        _, logs = self._run_with_failure(RuntimeError(SENTINEL_BODY))
        self.assertIn(SyncErrorCategory.UNEXPECTED_ERROR, logs)

    def test_timeout_logs_timeout_category(self):
        from app.services.sync_provider import SyncErrorCategory

        _, logs = self._run_with_failure(TimeoutError(SENTINEL_BODY))
        self.assertIn(SyncErrorCategory.TIMEOUT, logs)

    def test_sanitized_provider_error_logs_its_own_category(self):
        from app.services.sync_provider import SyncErrorCategory, SyncProviderError

        _, logs = self._run_with_failure(
            SyncProviderError(SyncErrorCategory.JOB_FAILED)
        )
        self.assertIn(SyncErrorCategory.JOB_FAILED, logs)


if __name__ == "__main__":
    unittest.main()
