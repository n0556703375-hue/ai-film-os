import os
import unittest
import unittest.mock

import httpx

from app.services.public_media_url import (
    PublicMediaUrlError,
    normalize_public_media_url,
    preflight_check_public_image,
)


class _EnvVarTestCase(unittest.TestCase):
    def setUp(self):
        self._original = {
            "PUBLIC_BASE_URL": os.environ.get("PUBLIC_BASE_URL"),
            "RENDER_EXTERNAL_URL": os.environ.get("RENDER_EXTERNAL_URL"),
        }
        os.environ.pop("PUBLIC_BASE_URL", None)
        os.environ.pop("RENDER_EXTERNAL_URL", None)

    def tearDown(self):
        for key, value in self._original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class NormalizePublicMediaUrlTests(_EnvVarTestCase):
    def test_empty_url_rejected(self):
        with self.assertRaises(PublicMediaUrlError) as ctx:
            normalize_public_media_url("")
        self.assertEqual(ctx.exception.reason, PublicMediaUrlError.EMPTY)

    def test_relative_generated_path_expands_via_public_base_url(self):
        os.environ["PUBLIC_BASE_URL"] = "https://myapp.example.com"
        result = normalize_public_media_url("/generated/uploads/shot-1/x.png")
        self.assertEqual(result, "https://myapp.example.com/generated/uploads/shot-1/x.png")

    def test_relative_generated_path_falls_back_to_render_external_url(self):
        os.environ["RENDER_EXTERNAL_URL"] = "https://ai-film-os.onrender.com"
        result = normalize_public_media_url("/generated/x.png")
        self.assertEqual(result, "https://ai-film-os.onrender.com/generated/x.png")

    def test_public_base_url_takes_priority_over_render_external_url(self):
        os.environ["PUBLIC_BASE_URL"] = "https://explicit.example.com"
        os.environ["RENDER_EXTERNAL_URL"] = "https://ai-film-os.onrender.com"
        result = normalize_public_media_url("/generated/x.png")
        self.assertEqual(result, "https://explicit.example.com/generated/x.png")

    def test_relative_path_without_any_public_base_fails_safe(self):
        with self.assertRaises(PublicMediaUrlError) as ctx:
            normalize_public_media_url("/generated/x.png")
        self.assertEqual(ctx.exception.reason, PublicMediaUrlError.NO_PUBLIC_BASE_CONFIGURED)

    def test_non_https_schemes_rejected(self):
        for url in (
            "http://example.com/image.png",
            "data:image/png;base64,AAAA",
            "blob:https://example.com/uuid",
            "file:///etc/passwd",
            "ftp://example.com/image.png",
        ):
            with self.subTest(url=url):
                with self.assertRaises(PublicMediaUrlError) as ctx:
                    normalize_public_media_url(url)
                self.assertEqual(ctx.exception.reason, PublicMediaUrlError.NOT_HTTPS)

    def test_localhost_and_dot_local_rejected(self):
        for url in ("https://localhost/image.png", "https://myhost.local/image.png"):
            with self.subTest(url=url):
                with self.assertRaises(PublicMediaUrlError) as ctx:
                    normalize_public_media_url(url)
                self.assertEqual(ctx.exception.reason, PublicMediaUrlError.PRIVATE_HOST)

    def test_private_loopback_link_local_reserved_ips_rejected(self):
        for host in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.1.1", "[::1]"):
            with self.subTest(host=host):
                with self.assertRaises(PublicMediaUrlError) as ctx:
                    normalize_public_media_url(f"https://{host}/image.png")
                self.assertEqual(ctx.exception.reason, PublicMediaUrlError.PRIVATE_HOST)

    def test_valid_public_https_url_passes_through_unchanged(self):
        url = "https://cdn.example.com/image.png"
        self.assertEqual(normalize_public_media_url(url), url)


def _mock_transport(responses):
    """responses: list of (status_code, headers, body_bytes) consumed per request, in order."""
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        status, headers, body = responses[state["i"]]
        state["i"] += 1
        return httpx.Response(status, headers=headers, content=body, request=request)

    return httpx.MockTransport(handler)


_REAL_HTTPX_CLIENT = httpx.Client


class PreflightCheckPublicImageTests(unittest.TestCase):
    def _patch_client(self, transport):
        # Capture the real Client class before patching: patching the
        # attribute on the shared `httpx` module object patches it
        # everywhere the module is imported, so calling `httpx.Client(...)`
        # from inside this replacement would recurse into itself.
        return unittest.mock.patch(
            "app.services.public_media_url.httpx.Client",
            lambda **kwargs: _REAL_HTTPX_CLIENT(transport=transport, **kwargs),
        )

    def test_reachable_image_passes(self):
        transport = _mock_transport([
            (200, {"content-type": "image/png"}, b"\x89PNG..."),
        ])
        with self._patch_client(transport):
            preflight_check_public_image("https://cdn.example.com/image.png")

    def test_non_2xx_status_rejected(self):
        transport = _mock_transport([(404, {"content-type": "text/html"}, b"not found")])
        with self._patch_client(transport):
            with self.assertRaises(PublicMediaUrlError) as ctx:
                preflight_check_public_image("https://cdn.example.com/missing.png")
        self.assertEqual(ctx.exception.reason, PublicMediaUrlError.UNREACHABLE)

    def test_html_error_page_rejected_by_content_type(self):
        transport = _mock_transport([
            (200, {"content-type": "text/html; charset=utf-8"}, b"<html>error</html>"),
        ])
        with self._patch_client(transport):
            with self.assertRaises(PublicMediaUrlError) as ctx:
                preflight_check_public_image("https://cdn.example.com/image.png")
        self.assertEqual(ctx.exception.reason, PublicMediaUrlError.WRONG_CONTENT_TYPE)

    def test_oversized_content_length_rejected(self):
        transport = _mock_transport([
            (200, {"content-type": "image/png", "content-length": str(50 * 1024 * 1024)}, b"x"),
        ])
        with self._patch_client(transport):
            with self.assertRaises(PublicMediaUrlError) as ctx:
                preflight_check_public_image("https://cdn.example.com/huge.png", max_bytes=25 * 1024 * 1024)
        self.assertEqual(ctx.exception.reason, PublicMediaUrlError.TOO_LARGE)

    def test_redirect_to_private_host_rejected(self):
        transport = _mock_transport([
            (302, {"location": "https://127.0.0.1/internal.png"}, b""),
        ])
        with self._patch_client(transport):
            with self.assertRaises(PublicMediaUrlError) as ctx:
                preflight_check_public_image("https://cdn.example.com/redirect.png")
        self.assertEqual(ctx.exception.reason, PublicMediaUrlError.PRIVATE_HOST)

    def test_redirect_to_public_host_is_followed_and_validated(self):
        transport = _mock_transport([
            (302, {"location": "https://cdn2.example.com/final.png"}, b""),
            (200, {"content-type": "image/jpeg"}, b"\xff\xd8..."),
        ])
        with self._patch_client(transport):
            preflight_check_public_image("https://cdn.example.com/redirect.png")

    def test_too_many_redirects_rejected(self):
        responses = [(302, {"location": f"https://cdn.example.com/hop{i}"}, b"") for i in range(10)]
        transport = _mock_transport(responses)
        with self._patch_client(transport):
            with self.assertRaises(PublicMediaUrlError) as ctx:
                preflight_check_public_image("https://cdn.example.com/start", max_redirects=3)
        self.assertEqual(ctx.exception.reason, PublicMediaUrlError.TOO_MANY_REDIRECTS)

    def test_connection_error_is_unreachable(self):
        def handler(request):
            raise httpx.ConnectError("boom", request=request)

        transport = httpx.MockTransport(handler)
        with self._patch_client(transport):
            with self.assertRaises(PublicMediaUrlError) as ctx:
                preflight_check_public_image("https://cdn.example.com/image.png")
        self.assertEqual(ctx.exception.reason, PublicMediaUrlError.UNREACHABLE)

    def test_non_https_target_rejected_before_any_request(self):
        with self.assertRaises(PublicMediaUrlError) as ctx:
            preflight_check_public_image("http://cdn.example.com/image.png")
        self.assertEqual(ctx.exception.reason, PublicMediaUrlError.NOT_HTTPS)


if __name__ == "__main__":
    unittest.main()
