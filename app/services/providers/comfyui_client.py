"""Low-level HTTP client for a local ComfyUI instance's API.

Shared by app.services.providers.local_comfyui_provider (video, LTX/Wan) and
app.services.providers.local_comfyui_image_provider (image, SDXL/Flux) — both
talk to the same ComfyUI server (COMFYUI_ENDPOINT), just with different
workflow files and node overrides, so the HTTP mechanics live in one place.

Never reaches outside the local network: COMFYUI_ENDPOINT is expected to be
http://localhost:8188 or another host on the operator's own LAN, set up per
the setup notes produced by installing ComfyUI locally (see the repo root
README's local-draft-provider section). Nothing here calls out to the public
internet.

## Workflow file convention

A "workflow" is a ComfyUI API-format prompt export — a JSON object mapping
node id -> {"class_type": ..., "inputs": {...}, "_meta": {"title": ...}}
(the format ComfyUI's web UI produces via "Save (API Format)", with node
titles/metadata enabled in export settings). This client never constructs a
node graph itself — it only loads one from disk and overwrites specific
input values on specific nodes, located by an exact ``_meta.title`` match:

    AIFilmOS_Prompt   — a CLIPTextEncode (or similar) node; its "text" input
                        is set to the request's prompt.
    AIFilmOS_Image    — a LoadImage node; its "image" input is set to the
                        filename returned by uploading the reference image
                        first (see upload_image()). Omit this node from a
                        text-only workflow.
    AIFilmOS_Seed     — any node with a "seed" or "noise_seed" input; set to
                        a fresh random seed per request. Optional.
    AIFilmOS_Frames   — any node with a "length"/"frame_count" input (video
                        only); set from the request's duration. Optional —
                        skipped if the workflow doesn't have this node.

A workflow file with none of these titled nodes still submits successfully
(nothing gets overridden), but the request's prompt/image/duration would
then be silently ignored — the workflow's own hardcoded values run instead.
This is deliberate: a missing marker node is not treated as an error, since
it may be an intentional fixed-parameter workflow.
"""

from __future__ import annotations

import json
import random
import uuid
from pathlib import Path

import httpx

from app.core.config import settings

_REQUEST_TIMEOUT_SECONDS = 30.0
_UPLOAD_TIMEOUT_SECONDS = 60.0
_HISTORY_TIMEOUT_SECONDS = 15.0
_DOWNLOAD_TIMEOUT_SECONDS = 120.0

NODE_TITLE_PROMPT = "AIFilmOS_Prompt"
NODE_TITLE_IMAGE = "AIFilmOS_Image"
NODE_TITLE_SEED = "AIFilmOS_Seed"
NODE_TITLE_FRAMES = "AIFilmOS_Frames"


class ComfyUIError(RuntimeError):
    """A stable, sanitized reason a local ComfyUI operation failed.

    Every reason that means "the local setup isn't ready" points the
    operator at SETUP_NOTES.md (produced by the local installation — see the
    project README) rather than surfacing a generic/opaque exception.
    """

    NOT_CONFIGURED = "not_configured"
    ENDPOINT_UNREACHABLE = "endpoint_unreachable"
    WORKFLOW_NOT_CONFIGURED = "workflow_not_configured"
    WORKFLOW_NOT_FOUND = "workflow_not_found"
    WORKFLOW_INVALID = "workflow_invalid"
    SUBMIT_FAILED = "submit_failed"
    UPLOAD_FAILED = "upload_failed"
    GENERATION_FAILED = "generation_failed"
    OUTPUT_NOT_FOUND = "output_not_found"

    _SETUP_HINT = (
        "See SETUP_NOTES.md (produced when the local ComfyUI environment was "
        "installed) for how to install/start ComfyUI and configure "
        "COMFYUI_ENDPOINT / COMFYUI_WORKFLOW_*_PATH."
    )

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        message = f"local_comfyui_error: {reason}"
        if detail:
            message = f"{message} ({detail})"
        if reason in {
            self.NOT_CONFIGURED,
            self.ENDPOINT_UNREACHABLE,
            self.WORKFLOW_NOT_CONFIGURED,
            self.WORKFLOW_NOT_FOUND,
        }:
            message = f"{message}. {self._SETUP_HINT}"
        super().__init__(message)


def is_configured() -> bool:
    return bool(settings.comfyui_endpoint)


def _require_configured() -> None:
    if not is_configured():
        raise ComfyUIError(ComfyUIError.NOT_CONFIGURED)


def load_workflow(workflow_path: str) -> dict:
    if not workflow_path:
        raise ComfyUIError(ComfyUIError.WORKFLOW_NOT_CONFIGURED)
    path = Path(workflow_path)
    if not path.is_file():
        raise ComfyUIError(ComfyUIError.WORKFLOW_NOT_FOUND, workflow_path)
    try:
        workflow = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComfyUIError(ComfyUIError.WORKFLOW_INVALID, workflow_path) from exc
    if not isinstance(workflow, dict) or not workflow:
        raise ComfyUIError(ComfyUIError.WORKFLOW_INVALID, workflow_path)
    return workflow


def _find_node_by_title(workflow: dict, title: str) -> dict | None:
    for node in workflow.values():
        if isinstance(node, dict) and node.get("_meta", {}).get("title") == title:
            return node
    return None


def apply_overrides(
    workflow: dict,
    *,
    prompt: str | None = None,
    image_filename: str | None = None,
    frame_count: int | None = None,
    randomize_seed: bool = True,
) -> dict:
    """Return a copy of ``workflow`` with the titled marker nodes patched.

    Never mutates the input dict — callers may reuse the same loaded
    workflow across multiple requests.
    """
    patched = json.loads(json.dumps(workflow))  # cheap deep copy, JSON-safe by construction

    if prompt is not None:
        node = _find_node_by_title(patched, NODE_TITLE_PROMPT)
        if node is not None:
            node.setdefault("inputs", {})["text"] = prompt

    if image_filename is not None:
        node = _find_node_by_title(patched, NODE_TITLE_IMAGE)
        if node is not None:
            node.setdefault("inputs", {})["image"] = image_filename

    if frame_count is not None:
        node = _find_node_by_title(patched, NODE_TITLE_FRAMES)
        if node is not None:
            inputs = node.setdefault("inputs", {})
            key = "length" if "length" in inputs else "frame_count" if "frame_count" in inputs else "length"
            inputs[key] = frame_count

    if randomize_seed:
        node = _find_node_by_title(patched, NODE_TITLE_SEED)
        if node is not None:
            inputs = node.setdefault("inputs", {})
            key = "seed" if "seed" in inputs else "noise_seed" if "noise_seed" in inputs else "seed"
            inputs[key] = random.randint(0, 2**32 - 1)

    return patched


def submit_workflow(workflow: dict) -> str:
    """POST a patched workflow to ComfyUI's /prompt endpoint. Returns prompt_id."""
    _require_configured()
    client_id = uuid.uuid4().hex
    try:
        with httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = client.post(
                f"{settings.comfyui_endpoint}/prompt",
                json={"prompt": workflow, "client_id": client_id},
            )
    except httpx.RequestError as exc:
        raise ComfyUIError(ComfyUIError.ENDPOINT_UNREACHABLE) from exc

    if response.status_code >= 300:
        raise ComfyUIError(ComfyUIError.SUBMIT_FAILED, f"status={response.status_code}")
    data = response.json()
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise ComfyUIError(ComfyUIError.SUBMIT_FAILED, "no prompt_id in response")
    return prompt_id


def poll_history(prompt_id: str) -> dict | None:
    """GET /history/{prompt_id}. Returns None while the job is still queued/running."""
    _require_configured()
    try:
        with httpx.Client(timeout=_HISTORY_TIMEOUT_SECONDS) as client:
            response = client.get(f"{settings.comfyui_endpoint}/history/{prompt_id}")
    except httpx.RequestError as exc:
        raise ComfyUIError(ComfyUIError.ENDPOINT_UNREACHABLE) from exc
    if response.status_code >= 300:
        raise ComfyUIError(ComfyUIError.ENDPOINT_UNREACHABLE, f"status={response.status_code}")
    data = response.json()
    return data.get(prompt_id)


def upload_image(content: bytes, filename: str) -> str:
    """POST /upload/image. Returns the filename ComfyUI stored it under,
    for use as a LoadImage node's "image" input."""
    _require_configured()
    try:
        with httpx.Client(timeout=_UPLOAD_TIMEOUT_SECONDS) as client:
            response = client.post(
                f"{settings.comfyui_endpoint}/upload/image",
                files={"image": (filename, content)},
            )
    except httpx.RequestError as exc:
        raise ComfyUIError(ComfyUIError.ENDPOINT_UNREACHABLE) from exc
    if response.status_code >= 300:
        raise ComfyUIError(ComfyUIError.UPLOAD_FAILED, f"status={response.status_code}")
    data = response.json()
    stored_name = data.get("name")
    if not stored_name:
        raise ComfyUIError(ComfyUIError.UPLOAD_FAILED, "no name in response")
    return stored_name


def fetch_output_bytes(filename: str, subfolder: str, output_type: str) -> bytes:
    """GET /view — download one output file ComfyUI produced."""
    _require_configured()
    try:
        with httpx.Client(timeout=_DOWNLOAD_TIMEOUT_SECONDS) as client:
            response = client.get(
                f"{settings.comfyui_endpoint}/view",
                params={"filename": filename, "subfolder": subfolder, "type": output_type},
            )
    except httpx.RequestError as exc:
        raise ComfyUIError(ComfyUIError.ENDPOINT_UNREACHABLE) from exc
    if response.status_code >= 300:
        raise ComfyUIError(ComfyUIError.OUTPUT_NOT_FOUND, f"status={response.status_code}")
    return response.content


# ComfyUI groups completed outputs under history[prompt_id]["outputs"][node_id]
# by media kind — different node types populate different keys. Checked in
# this order so a workflow producing more than one kind still picks its
# primary output deterministically.
_OUTPUT_LIST_KEYS = ("videos", "gifs", "images")


def extract_first_output(history_entry: dict) -> dict | None:
    """Return the first output file descriptor ({"filename","subfolder","type"})
    from a completed history entry, or None if it produced no media."""
    outputs = history_entry.get("outputs", {})
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        for key in _OUTPUT_LIST_KEYS:
            items = node_output.get(key)
            if items:
                return items[0]
    return None


def history_status(history_entry: dict) -> str:
    """Return "succeed"/"failed"/"pending" from a history entry's status block."""
    status_block = history_entry.get("status", {})
    if status_block.get("status_str") == "error":
        return "failed"
    if status_block.get("completed"):
        return "succeed" if extract_first_output(history_entry) else "failed"
    return "pending"
