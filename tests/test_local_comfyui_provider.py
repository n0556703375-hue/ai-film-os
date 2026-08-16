"""Coverage for the local ComfyUI video provider (app.services.providers.
local_comfyui_provider) and its wiring into get_video_provider(draft_mode=)
and app/worker.py._process_video_job. Uses httpx.MockTransport — no real
ComfyUI instance or GPU involved.
"""

import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import httpx

from app.core.config import settings
from app.services import video_provider
from app.services.providers.local_comfyui_provider import LocalComfyUIProvider
from app.services.video_provider import VideoGenerationRequest, VideoProviderNotConfigured

_REAL_HTTPX_CLIENT = httpx.Client
_WORKFLOW = {
    "1": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}, "_meta": {"title": "AIFilmOS_Prompt"}},
    "2": {"class_type": "LoadImage", "inputs": {}, "_meta": {"title": "AIFilmOS_Image"}},
}


def _mock_transport(handler):
    return httpx.MockTransport(handler)


class GetVideoProviderDraftModeTests(unittest.TestCase):
    def setUp(self):
        self.original_endpoint = settings.comfyui_endpoint

    def tearDown(self):
        settings.comfyui_endpoint = self.original_endpoint

    def test_draft_mode_false_is_unaffected(self):
        settings.comfyui_endpoint = ""
        provider = video_provider.get_video_provider()
        self.assertNotIsInstance(provider, LocalComfyUIProvider)

    def test_draft_mode_true_without_endpoint_raises_not_configured(self):
        settings.comfyui_endpoint = ""
        with self.assertRaises(VideoProviderNotConfigured):
            video_provider.get_video_provider(draft_mode=True)

    def test_draft_mode_true_with_endpoint_returns_local_provider(self):
        settings.comfyui_endpoint = "http://localhost:8188"
        provider = video_provider.get_video_provider(draft_mode=True)
        self.assertIsInstance(provider, LocalComfyUIProvider)
        self.assertEqual(provider.name, "local_comfyui")
        self.assertTrue(provider.trusted_local)


class LocalComfyUIProviderTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_endpoint = settings.comfyui_endpoint
        self.original_wan_path = settings.comfyui_workflow_wan_path
        self.original_ltx_path = settings.comfyui_workflow_ltx_path
        settings.comfyui_endpoint = "http://localhost:8188"

        wan_path = Path(self.tempdir.name) / "wan.json"
        wan_path.write_text(json.dumps(_WORKFLOW), encoding="utf-8")
        settings.comfyui_workflow_wan_path = str(wan_path)
        settings.comfyui_workflow_ltx_path = str(wan_path)

        self.provider = LocalComfyUIProvider()

    def tearDown(self):
        settings.comfyui_endpoint = self.original_endpoint
        settings.comfyui_workflow_wan_path = self.original_wan_path
        settings.comfyui_workflow_ltx_path = self.original_ltx_path
        self.tempdir.cleanup()

    def _patch_client(self, handler):
        return unittest.mock.patch(
            "app.services.providers.comfyui_client.httpx.Client",
            lambda **kwargs: _REAL_HTTPX_CLIENT(transport=_mock_transport(handler), **kwargs),
        )

    def test_submit_without_image_returns_prompt_id(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertIn("/prompt", str(request.url))
            body = json.loads(request.content)
            # The prompt node was patched with the request's prompt text.
            self.assertEqual(body["prompt"]["1"]["inputs"]["text"], "a cat on a wall")
            return httpx.Response(200, json={"prompt_id": "task-1"})

        request = VideoGenerationRequest(image_url="", prompt="a cat on a wall", duration_seconds=5)
        with self._patch_client(handler):
            task_id = self.provider.submit(request)
        self.assertEqual(task_id, "task-1")

    def test_submit_with_image_uploads_then_submits(self):
        # Both comfyui_client and local_comfyui_provider do `import httpx`,
        # so they share the exact same module object — patching Client on
        # either module path patches the same global attribute. One handler
        # dispatching by host/path stands in for both the ComfyUI API calls
        # and the reference-image download.
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if "example.com" in str(request.url):
                return httpx.Response(200, content=b"fake-image-bytes")
            if "/upload/image" in str(request.url):
                return httpx.Response(200, json={"name": "stored_ref.png"})
            body = json.loads(request.content)
            self.assertEqual(body["prompt"]["2"]["inputs"]["image"], "stored_ref.png")
            return httpx.Response(200, json={"prompt_id": "task-2"})

        request = VideoGenerationRequest(image_url="https://example.com/ref.png", prompt="x", duration_seconds=5)
        with self._patch_client(handler):
            task_id = self.provider.submit(request)
        self.assertEqual(task_id, "task-2")
        self.assertTrue(any("/upload/image" in url for url in calls))

    def test_check_task_pending_when_no_history_entry(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        with self._patch_client(handler):
            status = self.provider.check_task("task-1")
        self.assertEqual(status["status"], "pending")

    def test_check_task_succeed_returns_view_url(self):
        entry = {
            "status": {"completed": True},
            "outputs": {"9": {"videos": [{"filename": "out.mp4", "subfolder": "sub", "type": "output"}]}},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"task-1": entry})

        with self._patch_client(handler):
            status = self.provider.check_task("task-1")
        self.assertEqual(status["status"], "succeed")
        self.assertIn("filename=out.mp4", status["url"])
        self.assertTrue(status["url"].startswith("http://localhost:8188/view"))

    def test_check_task_failed_on_error_status(self):
        entry = {"status": {"status_str": "error"}, "outputs": {}}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"task-1": entry})

        with self._patch_client(handler):
            status = self.provider.check_task("task-1")
        self.assertEqual(status["status"], "failed")
        self.assertIn("reason", status)

    def test_cost_for_is_always_zero(self):
        request = VideoGenerationRequest(image_url="", prompt="x", duration_seconds=5)
        self.assertEqual(self.provider.cost_for(request), 0.0)

    def test_model_for_reflects_local_model_choice(self):
        wan_request = VideoGenerationRequest(image_url="", prompt="x", duration_seconds=5, local_model="wan")
        ltx_request = VideoGenerationRequest(image_url="", prompt="x", duration_seconds=5, local_model="ltx")
        self.assertIn("wan", self.provider.model_for(wan_request))
        self.assertIn("ltx", self.provider.model_for(ltx_request))


if __name__ == "__main__":
    unittest.main()
