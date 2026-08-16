"""Coverage for the low-level local ComfyUI HTTP client
(app.services.providers.comfyui_client), shared by the local video and
image providers. Uses httpx.MockTransport rather than a real ComfyUI
instance — none of this suite depends on ComfyUI actually being installed.
"""

import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import httpx

from app.core.config import settings
from app.services.providers import comfyui_client

_REAL_HTTPX_CLIENT = httpx.Client


def _mock_transport(handler):
    return httpx.MockTransport(handler)


class ComfyUIConfigTests(unittest.TestCase):
    def setUp(self):
        self.original_endpoint = settings.comfyui_endpoint

    def tearDown(self):
        settings.comfyui_endpoint = self.original_endpoint

    def test_is_configured_false_when_endpoint_empty(self):
        settings.comfyui_endpoint = ""
        self.assertFalse(comfyui_client.is_configured())

    def test_is_configured_true_when_endpoint_set(self):
        settings.comfyui_endpoint = "http://localhost:8188"
        self.assertTrue(comfyui_client.is_configured())

    def test_submit_workflow_raises_not_configured_error_mentioning_setup_notes(self):
        settings.comfyui_endpoint = ""
        with self.assertRaises(comfyui_client.ComfyUIError) as ctx:
            comfyui_client.submit_workflow({})
        self.assertEqual(ctx.exception.reason, comfyui_client.ComfyUIError.NOT_CONFIGURED)
        self.assertIn("SETUP_NOTES.md", str(ctx.exception))


class WorkflowLoadingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_load_workflow_raises_when_path_not_configured(self):
        with self.assertRaises(comfyui_client.ComfyUIError) as ctx:
            comfyui_client.load_workflow("")
        self.assertEqual(ctx.exception.reason, comfyui_client.ComfyUIError.WORKFLOW_NOT_CONFIGURED)

    def test_load_workflow_raises_when_file_missing(self):
        missing = str(Path(self.tempdir.name) / "nope.json")
        with self.assertRaises(comfyui_client.ComfyUIError) as ctx:
            comfyui_client.load_workflow(missing)
        self.assertEqual(ctx.exception.reason, comfyui_client.ComfyUIError.WORKFLOW_NOT_FOUND)

    def test_load_workflow_raises_on_invalid_json(self):
        path = Path(self.tempdir.name) / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(comfyui_client.ComfyUIError) as ctx:
            comfyui_client.load_workflow(str(path))
        self.assertEqual(ctx.exception.reason, comfyui_client.ComfyUIError.WORKFLOW_INVALID)

    def test_load_workflow_returns_parsed_dict(self):
        workflow = {"1": {"class_type": "X", "inputs": {}, "_meta": {"title": "AIFilmOS_Prompt"}}}
        path = Path(self.tempdir.name) / "good.json"
        path.write_text(json.dumps(workflow), encoding="utf-8")
        self.assertEqual(comfyui_client.load_workflow(str(path)), workflow)


class ApplyOverridesTests(unittest.TestCase):
    def test_prompt_override_sets_titled_node_text(self):
        workflow = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}, "_meta": {"title": "AIFilmOS_Prompt"}}}
        patched = comfyui_client.apply_overrides(workflow, prompt="new prompt")
        self.assertEqual(patched["1"]["inputs"]["text"], "new prompt")

    def test_original_workflow_is_never_mutated(self):
        workflow = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}, "_meta": {"title": "AIFilmOS_Prompt"}}}
        comfyui_client.apply_overrides(workflow, prompt="new prompt")
        self.assertEqual(workflow["1"]["inputs"]["text"], "old")

    def test_missing_titled_node_is_silently_skipped(self):
        workflow = {"1": {"class_type": "X", "inputs": {}, "_meta": {"title": "SomethingElse"}}}
        patched = comfyui_client.apply_overrides(workflow, prompt="new prompt")
        self.assertEqual(patched, workflow)

    def test_image_override_sets_loadimage_node(self):
        workflow = {"2": {"class_type": "LoadImage", "inputs": {}, "_meta": {"title": "AIFilmOS_Image"}}}
        patched = comfyui_client.apply_overrides(workflow, image_filename="uploaded.png")
        self.assertEqual(patched["2"]["inputs"]["image"], "uploaded.png")

    def test_frame_count_override_prefers_existing_length_key(self):
        workflow = {"3": {"class_type": "X", "inputs": {"length": 16}, "_meta": {"title": "AIFilmOS_Frames"}}}
        patched = comfyui_client.apply_overrides(workflow, frame_count=120)
        self.assertEqual(patched["3"]["inputs"]["length"], 120)

    def test_seed_override_randomizes_when_enabled(self):
        workflow = {"4": {"class_type": "X", "inputs": {"seed": 0}, "_meta": {"title": "AIFilmOS_Seed"}}}
        patched_a = comfyui_client.apply_overrides(workflow, randomize_seed=True)
        patched_b = comfyui_client.apply_overrides(workflow, randomize_seed=True)
        # Astronomically unlikely to collide twice in a row if truly randomized.
        self.assertNotEqual(patched_a["4"]["inputs"]["seed"], patched_b["4"]["inputs"]["seed"])

    def test_seed_override_skipped_when_disabled(self):
        workflow = {"4": {"class_type": "X", "inputs": {"seed": 42}, "_meta": {"title": "AIFilmOS_Seed"}}}
        patched = comfyui_client.apply_overrides(workflow, randomize_seed=False)
        self.assertEqual(patched["4"]["inputs"]["seed"], 42)


class ComfyUIRequestTests(unittest.TestCase):
    def setUp(self):
        self.original_endpoint = settings.comfyui_endpoint
        settings.comfyui_endpoint = "http://localhost:8188"

    def tearDown(self):
        settings.comfyui_endpoint = self.original_endpoint

    def _patch_client(self, handler):
        return unittest.mock.patch(
            "app.services.providers.comfyui_client.httpx.Client",
            lambda **kwargs: _REAL_HTTPX_CLIENT(transport=_mock_transport(handler), **kwargs),
        )

    def test_submit_workflow_returns_prompt_id(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "POST")
            self.assertTrue(str(request.url).endswith("/prompt"))
            body = json.loads(request.content)
            self.assertIn("prompt", body)
            self.assertIn("client_id", body)
            return httpx.Response(200, json={"prompt_id": "abc123"})

        with self._patch_client(handler):
            prompt_id = comfyui_client.submit_workflow({"1": {}})
        self.assertEqual(prompt_id, "abc123")

    def test_submit_workflow_raises_on_error_status(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "bad node"})

        with self._patch_client(handler):
            with self.assertRaises(comfyui_client.ComfyUIError) as ctx:
                comfyui_client.submit_workflow({"1": {}})
        self.assertEqual(ctx.exception.reason, comfyui_client.ComfyUIError.SUBMIT_FAILED)

    def test_submit_workflow_unreachable_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        with self._patch_client(handler):
            with self.assertRaises(comfyui_client.ComfyUIError) as ctx:
                comfyui_client.submit_workflow({"1": {}})
        self.assertEqual(ctx.exception.reason, comfyui_client.ComfyUIError.ENDPOINT_UNREACHABLE)

    def test_poll_history_returns_none_while_pending(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        with self._patch_client(handler):
            self.assertIsNone(comfyui_client.poll_history("abc123"))

    def test_poll_history_returns_entry_when_present(self):
        entry = {"outputs": {}, "status": {"completed": True}}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"abc123": entry})

        with self._patch_client(handler):
            self.assertEqual(comfyui_client.poll_history("abc123"), entry)

    def test_upload_image_returns_stored_filename(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertTrue(str(request.url).endswith("/upload/image"))
            return httpx.Response(200, json={"name": "stored123.png"})

        with self._patch_client(handler):
            name = comfyui_client.upload_image(b"fake-bytes", "ref.png")
        self.assertEqual(name, "stored123.png")

    def test_fetch_output_bytes_returns_content(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertIn("/view", str(request.url))
            return httpx.Response(200, content=b"video-bytes")

        with self._patch_client(handler):
            content = comfyui_client.fetch_output_bytes("out.mp4", "", "output")
        self.assertEqual(content, b"video-bytes")


class HistoryStatusTests(unittest.TestCase):
    def test_error_status_is_failed(self):
        entry = {"status": {"status_str": "error"}}
        self.assertEqual(comfyui_client.history_status(entry), "failed")

    def test_completed_with_output_is_succeed(self):
        entry = {
            "status": {"completed": True},
            "outputs": {"9": {"videos": [{"filename": "a.mp4", "subfolder": "", "type": "output"}]}},
        }
        self.assertEqual(comfyui_client.history_status(entry), "succeed")

    def test_completed_without_output_is_failed(self):
        entry = {"status": {"completed": True}, "outputs": {}}
        self.assertEqual(comfyui_client.history_status(entry), "failed")

    def test_not_completed_is_pending(self):
        entry = {"status": {"completed": False}}
        self.assertEqual(comfyui_client.history_status(entry), "pending")

    def test_extract_first_output_checks_videos_then_gifs_then_images(self):
        entry = {"outputs": {"1": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}}}
        output = comfyui_client.extract_first_output(entry)
        self.assertEqual(output["filename"], "a.png")

    def test_extract_first_output_returns_none_when_no_media(self):
        entry = {"outputs": {"1": {"text": ["not media"]}}}
        self.assertIsNone(comfyui_client.extract_first_output(entry))


if __name__ == "__main__":
    unittest.main()
