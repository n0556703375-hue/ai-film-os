"""Local ComfyUI video provider — a third, free/local draft-quality option
alongside Kling and Seedance (see app/services/video_provider.py). Never
reaches the public internet: every request goes to COMFYUI_ENDPOINT, which
is expected to be the operator's own machine (default http://localhost:8188).

Implements the exact non-blocking submit()/check_task() contract Kling and
Seedance already implement (see app/worker.py's _wait_for_provider_task /
_submit_or_resume_task) — no new orchestration mechanism, same resumable-job
pattern, same polling loop. The one deliberate difference from those two:
`trusted_local = True` tells app.worker._process_video_job it's safe to
persist a plain-http/localhost result URL (see
app.services.video_persistence.persist_remote_video's allow_private_host
parameter) — Kling/Seedance URLs are untouched, still required to be public
HTTPS, since a private-host response from a genuine external SaaS provider
would be a red flag, not the expected case.

Model selection: request.local_model is "ltx" or "wan" (default "wan"),
plumbed through app.services.video_provider.VideoGenerationRequest. Which
workflow JSON file backs each is configured via COMFYUI_WORKFLOW_LTX_PATH /
COMFYUI_WORKFLOW_WAN_PATH — see app/services/providers/comfyui_client.py's
module docstring for the workflow file convention those JSON files must
follow (node titles the client overrides by exact match).
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.services.providers import comfyui_client
from app.services.video_provider import VideoGenerationRequest

_IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 30.0
_MAX_REFERENCE_IMAGE_BYTES = 25 * 1024 * 1024

_MODEL_LABELS = {
    "ltx": "ltx-2.3-distilled",
    "wan": "wan-2.2-14b",
}
_WORKFLOW_PATH_BY_MODEL = {
    "ltx": lambda: settings.comfyui_workflow_ltx_path,
    "wan": lambda: settings.comfyui_workflow_wan_path,
}

# LTX-2.3 and Wan 2.2 workflows in this codebase's convention are assumed to
# target 24fps — the frame-count node (see comfyui_client.NODE_TITLE_FRAMES)
# is derived from the request's duration at that rate. A workflow authored
# for a different fps can simply omit that titled node and keep its own
# fixed frame count instead (see comfyui_client's docstring).
_ASSUMED_FPS = 24


def _download_reference_image(image_url: str) -> bytes:
    try:
        with httpx.Client(timeout=_IMAGE_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = client.get(image_url)
    except httpx.RequestError as exc:
        raise comfyui_client.ComfyUIError(comfyui_client.ComfyUIError.UPLOAD_FAILED, "reference image unreachable") from exc
    if response.status_code >= 300:
        raise comfyui_client.ComfyUIError(comfyui_client.ComfyUIError.UPLOAD_FAILED, f"reference image status={response.status_code}")
    content = response.content
    if len(content) > _MAX_REFERENCE_IMAGE_BYTES:
        raise comfyui_client.ComfyUIError(comfyui_client.ComfyUIError.UPLOAD_FAILED, "reference image too large")
    return content


class LocalComfyUIProvider:
    name = "local_comfyui"
    trusted_local = True

    def submit(self, request: VideoGenerationRequest) -> str:
        model = request.local_model if request.local_model in _WORKFLOW_PATH_BY_MODEL else "wan"
        workflow_path = _WORKFLOW_PATH_BY_MODEL[model]()
        workflow = comfyui_client.load_workflow(workflow_path)

        image_filename = None
        if request.image_url:
            content = _download_reference_image(request.image_url)
            image_filename = comfyui_client.upload_image(content, f"aifilmos_{model}_reference.png")

        frame_count = max(1, round(request.duration_seconds * _ASSUMED_FPS))
        patched = comfyui_client.apply_overrides(
            workflow,
            prompt=request.prompt,
            image_filename=image_filename,
            frame_count=frame_count,
        )
        return comfyui_client.submit_workflow(patched)

    def check_task(self, task_id: str) -> dict:
        history_entry = comfyui_client.poll_history(task_id)
        if history_entry is None:
            return {"status": "pending"}

        status = comfyui_client.history_status(history_entry)
        if status == "pending":
            return {"status": "pending"}
        if status == "failed":
            return {"status": "failed", "reason": comfyui_client.ComfyUIError.GENERATION_FAILED}

        output = comfyui_client.extract_first_output(history_entry)
        url = (
            f"{settings.comfyui_endpoint}/view"
            f"?filename={output['filename']}&subfolder={output.get('subfolder', '')}&type={output.get('type', 'output')}"
        )
        return {"status": "succeed", "url": url}

    def model_for(self, request: VideoGenerationRequest) -> str:
        model = request.local_model if request.local_model in _MODEL_LABELS else "wan"
        return _MODEL_LABELS[model]

    def cost_for(self, request: VideoGenerationRequest) -> float:
        # Local compute on the operator's own hardware — no per-request
        # provider billing, unlike Kling/Seedance.
        return 0.0
