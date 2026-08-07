"""Contract-fixture tests for app/services/kling_provider.py

Every test is deterministic and offline: HTTP is faked, time is injected,
and no real credentials or paid API calls are used. Fixtures mirror the
documented Kling open-platform contract:

  auth      — HS256 JWT, iss=AccessKey, exp=+1800s, nbf=-5s, Bearer header
  submit    — POST {base}/v1/videos/image2video with model_name/image/...
  poll      — GET  {base}/v1/videos/image2video/{task_id}
  envelope  — {code, message, request_id, data}
  status    — submitted | processing | succeed | failed
"""
import base64
import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

import httpx

from app.core.config import settings
from app.services.video_provider import (
    VideoGenerationRequest,
    VideoProviderNotConfigured,
)

ACCESS_KEY = "test-access-key"
SECRET_KEY = "test-secret-key"
BASE_URL = "https://api-singapore.klingai.com"

# Values that must never leak into an exception message.
SIGNED_MEDIA_URL = "https://cdn.klingai.com/output.mp4?sig=SECRETSIGNATURE&exp=999"
PROVIDER_MESSAGE = "internal provider stack trace do-not-print"


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


def _resp(status_code: int, body, *, method: str = "POST", json_body: bool = True):
    content = json.dumps(body).encode() if json_body else body
    return httpx.Response(
        status_code,
        content=content,
        headers={"content-type": "application/json" if json_body else "text/html"},
        request=httpx.Request(method, f"{BASE_URL}/v1/videos/image2video"),
    )


class _RecordingClient:
    """Fake httpx.Client capturing the outbound call for contract assertions."""

    calls: list = []

    def __init__(self, response, timeout=None):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, *, json=None, headers=None):
        type(self).calls.append({"method": "POST", "url": url, "json": json, "headers": headers})
        return self._response

    def get(self, url, *, headers=None):
        type(self).calls.append({"method": "GET", "url": url, "json": None, "headers": headers})
        return self._response


def _client_factory(response):
    _RecordingClient.calls = []

    def factory(timeout=None):
        return _RecordingClient(response, timeout=timeout)

    return factory


class _KlingTestCase(unittest.TestCase):
    """Installs deterministic credentials and base URL for each test."""

    def setUp(self):
        self._saved = (
            settings.kling_access_key,
            settings.kling_secret_key,
            settings.kling_api_base,
            settings.kling_default_model,
        )
        settings.kling_access_key = ACCESS_KEY
        settings.kling_secret_key = SECRET_KEY
        settings.kling_api_base = BASE_URL
        settings.kling_default_model = "kling-v2-master"

    def tearDown(self):
        (
            settings.kling_access_key,
            settings.kling_secret_key,
            settings.kling_api_base,
            settings.kling_default_model,
        ) = self._saved


# ---------------------------------------------------------------------------
# Authentication claims and expiration
# ---------------------------------------------------------------------------

def _decode_segment(segment: str) -> dict:
    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


class KlingJwtAuthTests(_KlingTestCase):
    def test_jwt_header_declares_hs256(self):
        from app.services.kling_provider import encode_jwt

        token = encode_jwt(ACCESS_KEY, SECRET_KEY, now=1_700_000_000)
        header = _decode_segment(token.split(".")[0])
        self.assertEqual(header, {"alg": "HS256", "typ": "JWT"})

    def test_jwt_claims_match_documented_contract(self):
        from app.services.kling_provider import encode_jwt

        now = 1_700_000_000
        payload = _decode_segment(encode_jwt(ACCESS_KEY, SECRET_KEY, now=now).split(".")[1])
        self.assertEqual(payload["iss"], ACCESS_KEY)
        self.assertEqual(payload["exp"], now + 1800)
        self.assertEqual(payload["nbf"], now - 5)

    def test_token_is_short_lived_thirty_minutes(self):
        from app.services.kling_provider import encode_jwt

        now = 1_700_000_000
        payload = _decode_segment(encode_jwt(ACCESS_KEY, SECRET_KEY, now=now).split(".")[1])
        self.assertEqual(payload["exp"] - payload["nbf"], 1805)
        self.assertLessEqual(payload["exp"] - now, 1800)

    def test_signature_is_hmac_sha256_over_signing_input(self):
        from app.services.kling_provider import encode_jwt

        token = encode_jwt(ACCESS_KEY, SECRET_KEY, now=1_700_000_000)
        header_b64, payload_b64, signature_b64 = token.split(".")
        expected = hmac.new(
            SECRET_KEY.encode(),
            f"{header_b64}.{payload_b64}".encode(),
            hashlib.sha256,
        ).digest()
        expected_b64 = base64.urlsafe_b64encode(expected).rstrip(b"=").decode()
        self.assertEqual(signature_b64, expected_b64)

    def test_secret_key_never_appears_inside_the_token(self):
        from app.services.kling_provider import encode_jwt

        token = encode_jwt(ACCESS_KEY, SECRET_KEY, now=1_700_000_000)
        self.assertNotIn(SECRET_KEY, token)
        self.assertNotIn(SECRET_KEY, _decode_segment(token.split(".")[1]).get("iss", ""))

    def test_tokens_are_minted_per_request_not_cached(self):
        from app.services.kling_provider import encode_jwt

        early = encode_jwt(ACCESS_KEY, SECRET_KEY, now=1_700_000_000)
        later = encode_jwt(ACCESS_KEY, SECRET_KEY, now=1_700_000_600)
        self.assertNotEqual(early, later)

    def test_missing_credentials_raise_not_configured(self):
        from app.services.kling_provider import KlingProvider

        settings.kling_access_key = ""
        with self.assertRaises(VideoProviderNotConfigured):
            KlingProvider().submit(_req())

    def test_partial_credentials_raise_not_configured(self):
        from app.services.kling_provider import KlingProvider

        settings.kling_secret_key = ""
        with self.assertRaises(VideoProviderNotConfigured):
            KlingProvider().submit(_req())

    def test_authorization_header_uses_bearer_jwt(self):
        from app.services.kling_provider import KlingProvider

        response = _resp(200, {"code": 0, "data": {"task_id": "task-1"}})
        with patch("httpx.Client", _client_factory(response)):
            KlingProvider().submit(_req())

        header = _RecordingClient.calls[0]["headers"]["Authorization"]
        self.assertTrue(header.startswith("Bearer "))
        token = header.split(" ", 1)[1]
        self.assertEqual(len(token.split(".")), 3)
        self.assertEqual(_decode_segment(token.split(".")[1])["iss"], ACCESS_KEY)


# ---------------------------------------------------------------------------
# Submit endpoint and payload
# ---------------------------------------------------------------------------

class KlingSubmitContractTests(_KlingTestCase):
    def _submit(self, request=None, body=None):
        response = _resp(200, body or {"code": 0, "data": {"task_id": "task-1"}})
        with patch("httpx.Client", _client_factory(response)):
            return KlingProviderFactory().submit(request or _req())

    def test_submit_targets_documented_image2video_endpoint(self):
        self._submit()
        self.assertEqual(
            _RecordingClient.calls[0]["url"],
            f"{BASE_URL}/v1/videos/image2video",
        )

    def test_default_base_url_is_the_international_host(self):
        from app.core.config import KLING_DEFAULT_API_BASE

        self.assertEqual(KLING_DEFAULT_API_BASE, "https://api-singapore.klingai.com")

    def test_default_model_is_a_supported_identifier(self):
        from app.core.config import KLING_FALLBACK_MODEL
        from app.services.kling_provider import SUPPORTED_MODELS

        self.assertIn(KLING_FALLBACK_MODEL, SUPPORTED_MODELS)

    def test_payload_uses_documented_field_names(self):
        self._submit()
        payload = _RecordingClient.calls[0]["json"]
        self.assertIn("model_name", payload)
        self.assertIn("image", payload)
        self.assertNotIn("model", payload)
        self.assertNotIn("image_url", payload)
        self.assertNotIn("aspect_ratio", payload)
        self.assertNotIn("with_audio", payload)

    def test_duration_is_snapped_to_supported_string_values(self):
        self._submit(_req(duration_seconds=5.0))
        self.assertEqual(_RecordingClient.calls[0]["json"]["duration"], "5")
        self._submit(_req(duration_seconds=12.0))
        self.assertEqual(_RecordingClient.calls[0]["json"]["duration"], "10")

    def test_model_profiles_map_to_supported_model_identifiers(self):
        from app.services.kling_provider import SUPPORTED_MODELS, _model_for

        for profile in ("fast", "cinematic", "high_fidelity", "auto"):
            with self.subTest(profile=profile):
                self.assertIn(_model_for(profile), SUPPORTED_MODELS)

    def test_unknown_profile_falls_back_to_supported_model(self):
        from app.services.kling_provider import SUPPORTED_MODELS, _model_for

        settings.kling_default_model = "kling-v3-does-not-exist"
        self.assertIn(_model_for("nonexistent"), SUPPORTED_MODELS)

    def test_camera_control_omitted_when_no_motion_requested(self):
        self._submit(_req(camera_motion=""))
        self.assertNotIn("camera_control", _RecordingClient.calls[0]["json"])

    def test_camera_control_uses_documented_shape(self):
        self._submit(_req(camera_motion="orbit"))
        self.assertEqual(
            _RecordingClient.calls[0]["json"]["camera_control"],
            {"type": "left_turn_forward"},
        )
        self._submit(_req(camera_motion="zoom in"))
        control = _RecordingClient.calls[0]["json"]["camera_control"]
        self.assertEqual(control["type"], "simple")
        self.assertIn("zoom", control["config"])

    def test_submit_returns_task_id_from_envelope(self):
        self.assertEqual(self._submit(), "task-1")

    def test_missing_task_id_raises_without_echoing_body(self):
        with self.assertRaises(RuntimeError) as captured:
            self._submit(body={"code": 0, "message": PROVIDER_MESSAGE, "data": {}})
        self.assertNotIn(PROVIDER_MESSAGE, str(captured.exception))


def KlingProviderFactory():
    from app.services.kling_provider import KlingProvider

    return KlingProvider()


# ---------------------------------------------------------------------------
# Polling endpoint and status parsing
# ---------------------------------------------------------------------------

class KlingPollContractTests(_KlingTestCase):
    def _check(self, body, status_code=200, json_body=True):
        response = _resp(status_code, body, method="GET", json_body=json_body)
        with patch("httpx.Client", _client_factory(response)):
            return KlingProviderFactory().check_task("task-1")

    def test_poll_targets_documented_task_endpoint(self):
        self._check({"code": 0, "data": {"task_status": "processing"}})
        self.assertEqual(
            _RecordingClient.calls[0]["url"],
            f"{BASE_URL}/v1/videos/image2video/task-1",
        )
        self.assertEqual(_RecordingClient.calls[0]["method"], "GET")

    def test_submitted_status_is_pending(self):
        result = self._check({"code": 0, "data": {"task_status": "submitted"}})
        self.assertEqual(result["status"], "pending")

    def test_processing_status_is_pending(self):
        result = self._check({"code": 0, "data": {"task_status": "processing"}})
        self.assertEqual(result["status"], "pending")

    def test_succeed_status_returns_video_url(self):
        result = self._check(
            {
                "code": 0,
                "data": {
                    "task_status": "succeed",
                    "task_result": {"videos": [{"id": "v1", "url": SIGNED_MEDIA_URL}]},
                },
            }
        )
        self.assertEqual(result["status"], "succeed")
        self.assertEqual(result["url"], SIGNED_MEDIA_URL)

    def test_failed_status_is_reported_without_provider_text(self):
        result = self._check(
            {
                "code": 0,
                "data": {"task_status": "failed", "task_status_msg": PROVIDER_MESSAGE},
            }
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["url"], "")
        self.assertNotIn(PROVIDER_MESSAGE, result["reason"])

    def test_succeed_without_videos_raises_without_leaking_body(self):
        with self.assertRaises(RuntimeError) as captured:
            self._check(
                {
                    "code": 0,
                    "message": PROVIDER_MESSAGE,
                    "data": {"task_status": "succeed", "task_result": {"videos": []}},
                }
            )
        self.assertNotIn(PROVIDER_MESSAGE, str(captured.exception))

    def test_unknown_status_raises(self):
        with self.assertRaises(RuntimeError):
            self._check({"code": 0, "data": {"task_status": "teleported"}})


# ---------------------------------------------------------------------------
# Error handling: 401/403, non-zero code, malformed payloads
# ---------------------------------------------------------------------------

class KlingErrorContractTests(_KlingTestCase):
    def _submit_response(self, status_code, body, json_body=True):
        response = _resp(status_code, body, json_body=json_body)
        with patch("httpx.Client", _client_factory(response)):
            return KlingProviderFactory().submit(_req())

    def test_401_raises_not_configured(self):
        with self.assertRaises(VideoProviderNotConfigured):
            self._submit_response(401, {"code": 1001, "message": PROVIDER_MESSAGE})

    def test_403_raises_not_configured(self):
        with self.assertRaises(VideoProviderNotConfigured):
            self._submit_response(403, {"code": 1002, "message": PROVIDER_MESSAGE})

    def test_401_message_does_not_leak_credentials_or_body(self):
        with self.assertRaises(VideoProviderNotConfigured) as captured:
            self._submit_response(401, {"code": 1001, "message": PROVIDER_MESSAGE})
        message = str(captured.exception)
        self.assertNotIn(PROVIDER_MESSAGE, message)
        self.assertNotIn(SECRET_KEY, message)
        self.assertNotIn(ACCESS_KEY, message)

    def test_server_error_reports_status_only(self):
        with self.assertRaises(RuntimeError) as captured:
            self._submit_response(500, {"code": 5000, "message": PROVIDER_MESSAGE})
        message = str(captured.exception)
        self.assertIn("500", message)
        self.assertNotIn(PROVIDER_MESSAGE, message)

    def test_non_zero_envelope_code_raises_with_code_only(self):
        with self.assertRaises(RuntimeError) as captured:
            self._submit_response(200, {"code": 1303, "message": PROVIDER_MESSAGE})
        message = str(captured.exception)
        self.assertIn("1303", message)
        self.assertNotIn(PROVIDER_MESSAGE, message)

    def test_malformed_json_raises_without_echoing_payload(self):
        with self.assertRaises(RuntimeError) as captured:
            self._submit_response(200, b"<html>upstream token=do-not-print</html>", json_body=False)
        message = str(captured.exception)
        self.assertNotIn("do-not-print", message)
        self.assertNotIn("<html>", message)

    def test_non_dict_json_body_raises(self):
        with self.assertRaises(RuntimeError):
            self._submit_response(200, ["unexpected", "list"])

    def test_request_id_is_surfaced_when_well_formed(self):
        with self.assertRaises(RuntimeError) as captured:
            self._submit_response(
                200, {"code": 1303, "message": PROVIDER_MESSAGE, "request_id": "abc123XYZ"}
            )
        self.assertIn("abc123XYZ", str(captured.exception))

    def test_untrusted_request_id_is_not_surfaced(self):
        with self.assertRaises(RuntimeError) as captured:
            self._submit_response(
                200,
                {"code": 1303, "request_id": "<script>alert(1)</script> " + PROVIDER_MESSAGE},
            )
        message = str(captured.exception)
        self.assertNotIn("<script>", message)
        self.assertNotIn(PROVIDER_MESSAGE, message)


# ---------------------------------------------------------------------------
# Redaction proof: credentials and media URLs never reach exceptions
# ---------------------------------------------------------------------------

class KlingRedactionTests(_KlingTestCase):
    def test_no_exception_path_leaks_secret_or_prompt(self):
        from app.services.kling_provider import KlingProvider

        secret_prompt = "CONFIDENTIAL SCREENPLAY LINE"
        fixtures = [
            (401, {"code": 1001, "message": PROVIDER_MESSAGE}),
            (403, {"code": 1002, "message": PROVIDER_MESSAGE}),
            (500, {"code": 5000, "message": PROVIDER_MESSAGE}),
            (200, {"code": 1303, "message": PROVIDER_MESSAGE}),
            (200, {"code": 0, "message": PROVIDER_MESSAGE, "data": {}}),
        ]
        for status_code, body in fixtures:
            with self.subTest(status=status_code, code=body.get("code")):
                response = _resp(status_code, body)
                with patch("httpx.Client", _client_factory(response)):
                    with self.assertRaises((RuntimeError, VideoProviderNotConfigured)) as captured:
                        KlingProvider().submit(_req(prompt=secret_prompt))
                message = str(captured.exception)
                self.assertNotIn(SECRET_KEY, message)
                self.assertNotIn(ACCESS_KEY, message)
                self.assertNotIn(secret_prompt, message)
                self.assertNotIn(PROVIDER_MESSAGE, message)
                self.assertNotIn("Bearer", message)

    def test_signed_media_url_never_appears_in_failure_exception(self):
        from app.services.kling_provider import KlingProvider

        body = {
            "code": 0,
            "data": {
                "task_status": "succeed",
                "task_result": {"videos": [{"id": "v1"}]},
                "task_status_msg": SIGNED_MEDIA_URL,
            },
        }
        response = _resp(200, body, method="GET")
        with patch("httpx.Client", _client_factory(response)):
            with self.assertRaises(RuntimeError) as captured:
                KlingProvider().check_task("task-1")
        self.assertNotIn(SIGNED_MEDIA_URL, str(captured.exception))
        self.assertNotIn("sig=", str(captured.exception))

    def test_failure_reason_is_a_fixed_safe_string(self):
        from app.services.kling_provider import KlingProvider

        body = {
            "code": 0,
            "data": {"task_status": "failed", "task_status_msg": SIGNED_MEDIA_URL},
        }
        response = _resp(200, body, method="GET")
        with patch("httpx.Client", _client_factory(response)):
            result = KlingProvider().check_task("task-1")
        self.assertNotIn(SIGNED_MEDIA_URL, result["reason"])
        self.assertNotIn("sig=", result["reason"])


# ---------------------------------------------------------------------------
# Provider routing
# ---------------------------------------------------------------------------

class KlingRoutingTests(unittest.TestCase):
    def test_both_credentials_required_to_enable_kling(self):
        from app.services.video_provider import DisabledVideoProvider, get_video_provider

        with patch.dict("os.environ", {"KLING_ACCESS_KEY": "a", "KLING_SECRET_KEY": ""}, clear=False):
            self.assertIsInstance(get_video_provider(), DisabledVideoProvider)
        with patch.dict("os.environ", {"KLING_ACCESS_KEY": "", "KLING_SECRET_KEY": "b"}, clear=False):
            self.assertIsInstance(get_video_provider(), DisabledVideoProvider)

    def test_full_credential_pair_selects_kling(self):
        from app.services.kling_provider import KlingProvider
        from app.services.video_provider import get_video_provider

        with patch.dict("os.environ", {"KLING_ACCESS_KEY": "a", "KLING_SECRET_KEY": "b"}, clear=False):
            self.assertIsInstance(get_video_provider(), KlingProvider)


if __name__ == "__main__":
    unittest.main()
