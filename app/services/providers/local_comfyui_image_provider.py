"""Local ComfyUI image provider — a free/local draft-quality alternative to
Magnific/Nano Banana Pro (app.services.generation.submit_magnific_image /
get_magnific_image). Never reaches the public internet: every request goes
to COMFYUI_ENDPOINT (see app/services/providers/comfyui_client.py).

There is no pre-existing Provider protocol for images the way
app.services.video_provider defines one for video — image generation today
is two plain module functions in app.services.generation, called directly
by app/worker.py._process_image_job. This class deliberately mirrors that
same submit()/poll() shape (status vocabulary: "IN_PROGRESS"/"COMPLETED"/
"FAILED", matching what get_magnific_image returns) rather than inventing a
different one, so _process_image_job's polling loop is unchanged — only
which submit/check functions it calls differs by draft_mode. The one
necessary difference: check_task() takes shot_id, because unlike Magnific
(which hosts the result itself), this provider must persist the generated
bytes itself once ComfyUI finishes — reusing the exact same validated-
upload-and-store path app.services.media_upload.validate_and_store_upload
already uses (object storage when configured, local disk otherwise).

Model selection: "sdxl" or "flux" (default "sdxl"), each backed by its own
workflow JSON file — COMFYUI_WORKFLOW_SDXL_PATH / COMFYUI_WORKFLOW_FLUX_PATH.
See comfyui_client's module docstring for the workflow file convention.
"""

from __future__ import annotations

from app.services.media_upload import validate_and_store_upload
from app.services.providers import comfyui_client

_MODEL_LABELS = {
    "sdxl": "sdxl-1.0",
    "flux": "flux.1-q4-gguf",
}


def _workflow_path(model: str) -> str:
    from app.core.config import settings

    return settings.comfyui_workflow_sdxl_path if model == "sdxl" else settings.comfyui_workflow_flux_path


class LocalComfyUIImageProvider:
    name = "local_comfyui_image"

    def submit(self, shot: dict, *, instructions: str = "", model: str = "sdxl") -> dict:
        resolved_model = model if model in _MODEL_LABELS else "sdxl"
        workflow = comfyui_client.load_workflow(_workflow_path(resolved_model))

        prompt = shot.get("prompt") or ""
        if instructions:
            prompt = f"{prompt}\n\nADDITIONAL DIRECTION\n{instructions}"

        # Image-to-image / reference continuity against the Story Bible isn't
        # wired up here yet — only text-to-image. A workflow file that titles
        # a LoadImage node AIFilmOS_Image and is given an image_filename would
        # already work via comfyui_client.apply_overrides; this provider
        # simply never has a reference image to pass in today.
        patched = comfyui_client.apply_overrides(workflow, prompt=prompt)
        task_id = comfyui_client.submit_workflow(patched)
        return {
            "task_id": task_id,
            "status": "IN_PROGRESS",
            "provider": "local_comfyui_image",
            "model": _MODEL_LABELS[resolved_model],
        }

    def check_task(self, task_id: str, *, shot_id: int) -> dict:
        history_entry = comfyui_client.poll_history(task_id)
        if history_entry is None:
            return {"task_id": task_id, "status": "IN_PROGRESS", "generated": [], "has_nsfw": []}

        status = comfyui_client.history_status(history_entry)
        if status == "pending":
            return {"task_id": task_id, "status": "IN_PROGRESS", "generated": [], "has_nsfw": []}
        if status == "failed":
            return {"task_id": task_id, "status": "FAILED", "generated": [], "has_nsfw": []}

        output = comfyui_client.extract_first_output(history_entry)
        content = comfyui_client.fetch_output_bytes(
            output["filename"], output.get("subfolder", ""), output.get("type", "output")
        )
        stored = validate_and_store_upload(shot_id, "image/png", content)
        return {
            "task_id": task_id,
            "status": "COMPLETED",
            "generated": [stored["url"]],
            "has_nsfw": [False],
        }
