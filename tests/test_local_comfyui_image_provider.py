"""Coverage for the local ComfyUI image provider (app.services.providers.
local_comfyui_image_provider) and its wiring into app/worker.py's
_process_image_job draft_mode branch. Uses httpx.MockTransport — no real
ComfyUI instance or GPU involved.
"""

import io
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import httpx
from PIL import Image

from app.core.config import settings
from app.services.providers.local_comfyui_image_provider import LocalComfyUIImageProvider

_REAL_HTTPX_CLIENT = httpx.Client
_WORKFLOW = {
    "1": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}, "_meta": {"title": "AIFilmOS_Prompt"}},
}


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


class LocalComfyUIImageProviderTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_endpoint = settings.comfyui_endpoint
        self.original_sdxl_path = settings.comfyui_workflow_sdxl_path
        self.original_media_path = settings.generated_media_path
        settings.comfyui_endpoint = "http://localhost:8188"
        settings.generated_media_path = Path(self.tempdir.name) / "generated"

        workflow_path = Path(self.tempdir.name) / "sdxl.json"
        workflow_path.write_text(json.dumps(_WORKFLOW), encoding="utf-8")
        settings.comfyui_workflow_sdxl_path = str(workflow_path)

        self.provider = LocalComfyUIImageProvider()

    def tearDown(self):
        settings.comfyui_endpoint = self.original_endpoint
        settings.comfyui_workflow_sdxl_path = self.original_sdxl_path
        settings.generated_media_path = self.original_media_path
        self.tempdir.cleanup()

    def _patch_client(self, handler):
        return unittest.mock.patch(
            "app.services.providers.comfyui_client.httpx.Client",
            lambda **kwargs: _REAL_HTTPX_CLIENT(transport=_mock_transport(handler), **kwargs),
        )

    def test_submit_returns_in_progress_task(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.assertIn("a cat", body["prompt"]["1"]["inputs"]["text"])
            return httpx.Response(200, json={"prompt_id": "img-task-1"})

        with self._patch_client(handler):
            result = self.provider.submit({"prompt": "a cat"}, instructions="", model="sdxl")
        self.assertEqual(result["task_id"], "img-task-1")
        self.assertEqual(result["status"], "IN_PROGRESS")
        self.assertEqual(result["provider"], "local_comfyui_image")

    def test_submit_appends_instructions_to_prompt(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            text = body["prompt"]["1"]["inputs"]["text"]
            self.assertIn("a cat", text)
            self.assertIn("closer shot", text)
            return httpx.Response(200, json={"prompt_id": "img-task-2"})

        with self._patch_client(handler):
            self.provider.submit({"prompt": "a cat"}, instructions="closer shot", model="sdxl")

    def test_check_task_in_progress_while_no_history_entry(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        with self._patch_client(handler):
            status = self.provider.check_task("img-task-1", shot_id=1)
        self.assertEqual(status["status"], "IN_PROGRESS")
        self.assertEqual(status["generated"], [])

    def test_check_task_failed_on_error_status(self):
        entry = {"status": {"status_str": "error"}, "outputs": {}}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"img-task-1": entry})

        with self._patch_client(handler):
            status = self.provider.check_task("img-task-1", shot_id=1)
        self.assertEqual(status["status"], "FAILED")

    def test_check_task_completed_downloads_and_persists_image(self):
        entry = {
            "status": {"completed": True},
            "outputs": {"9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}},
        }
        png_bytes = _png_bytes()

        def handler(request: httpx.Request) -> httpx.Response:
            if "/view" in str(request.url):
                return httpx.Response(200, content=png_bytes)
            return httpx.Response(200, json={"img-task-1": entry})

        with self._patch_client(handler):
            status = self.provider.check_task("img-task-1", shot_id=7)

        self.assertEqual(status["status"], "COMPLETED")
        self.assertEqual(len(status["generated"]), 1)
        self.assertTrue(status["generated"][0].startswith("/generated/uploads/shot-7/"))
        self.assertEqual(status["has_nsfw"], [False])

        stored_path = settings.generated_media_path / status["generated"][0].removeprefix("/generated/")
        self.assertTrue(stored_path.exists())
        self.assertEqual(stored_path.read_bytes(), png_bytes)


if __name__ == "__main__":
    unittest.main()
