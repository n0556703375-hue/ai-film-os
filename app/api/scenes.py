from fastapi import APIRouter, HTTPException
from app.models.schemas import SceneCreate, SceneUpdate, ShotMapRequest, ScriptImportRequest
from app.repositories import scenes as repo
from app.repositories import assets as asset_repo
from app.repositories import projects as project_repo
from app.repositories import shots as shot_repo
from app.services.generation import GenerationNotConfigured
from app.services.prompt_builder import build_prompt
from app.services.scene_assembly import build_scene_preview_manifest
from app.services.scene_bible import generate_scene_bible
from app.services.shot_map import generate_shot_map
from app.services.screenplay_breakdown import breakdown_screenplay

router = APIRouter(prefix="/api/scenes", tags=["scenes"])


def _import_progress_detail(message, progress, *, code, retryable):
    return {
        "message": message,
        "code": code,
        "retryable": retryable,
        "completed_stages": list(progress["completed_stages"]),
        "failed_stage": progress["failed_stage"],
        "scenes_created": progress["scenes_created"],
        "shots_created": progress["shots_created"],
        "failed_scene_id": progress.get("failed_scene_id"),
        "failed_scene_number": progress.get("failed_scene_number"),
    }


@router.get("")
def list_scenes(project_id: int | None = None):
    return repo.list_scenes(project_id)


@router.post("")
def create_scene(scene: SceneCreate):
    try:
        return repo.create_scene(scene.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post(
    "/import-script",
    deprecated=True,
    include_in_schema=False,
)
def import_script(request: ScriptImportRequest):
    """Legacy single-request import, superseded by the resumable /api/import-runs flow.

    Not called by the current UI (app/templates/script_import.html) or by
    scripts/deployment_smoke.py, and excluded from the OpenAPI schema so it can't
    be mistaken for the documented import entry point. Kept only because
    tests/test_script_import_counts.py still exercises this function directly;
    do not wire any new client to this path.
    """
    project = project_repo.get_project(request.project_id)
    if not project:
        raise HTTPException(404, "הפרויקט לא נמצא.")
    assets = [a for a in asset_repo.list_assets(request.project_id) if a["approved"]]
    progress = {
        "completed_stages": [],
        "failed_stage": "screenplay_breakdown",
        "scenes_created": 0,
        "shots_created": 0,
        "failed_scene_id": None,
        "failed_scene_number": None,
    }
    try:
        breakdown = breakdown_screenplay(
            project,
            request.screenplay,
            request.target_shots_per_minute,
        )
        progress["completed_stages"].append("screenplay_breakdown")
        progress["failed_stage"] = "scene_persistence"
        created = repo.import_scenes(request.project_id, breakdown, request.replace_existing)
        progress["scenes_created"] = len(created)
        progress["completed_stages"].append("scene_persistence")
        progress["failed_stage"] = "shot_map_generation" if request.generate_shot_maps else None
        if request.generate_shot_maps:
            for scene_meta in created:
                progress["failed_scene_id"] = scene_meta["id"]
                progress["failed_scene_number"] = scene_meta.get("scene_number")
                scene = repo.get_scene(scene_meta["id"])
                count = scene_meta["recommended_shot_count"]
                generated = generate_shot_map(scene, project, assets, count)
                result = repo.create_generated_shots(scene["id"], generated, False)
                for item in result["shots"]:
                    shot = shot_repo.get_shot(item["id"])
                    prompt = build_prompt(shot)
                    shot_repo.save_prompt_version(item["id"], prompt, shot.get("negative_prompt", ""), "script-import")
                    shot_repo.update_shot(item["id"], {"prompt": prompt, "status": "פרומפט מוכן"})
                progress["shots_created"] += len(result["shots"])
            progress["completed_stages"].append("shot_map_generation")
            progress["failed_scene_id"] = None
            progress["failed_scene_number"] = None
        progress["failed_stage"] = None
        return {
            "project_id": request.project_id,
            "scenes_created": progress["scenes_created"],
            "shots_created": progress["shots_created"],
            "completed_stages": progress["completed_stages"],
            "failed_stage": None,
            "retryable": False,
            "imported_scenes": created,
            "scenes": repo.list_scenes(request.project_id),
        }
    except GenerationNotConfigured:
        raise HTTPException(
            503,
            _import_progress_detail(
                "שירות היצירה אינו מוגדר כרגע.",
                progress,
                code="generation_not_configured",
                retryable=False,
            ),
        )
    except ValueError as exc:
        raise HTTPException(
            409,
            _import_progress_detail(
                str(exc),
                progress,
                code="import_conflict",
                retryable=False,
            ),
        )
    except Exception:
        raise HTTPException(
            502,
            _import_progress_detail(
                "ייבוא התסריט נעצר עקב תקלה זמנית.",
                progress,
                code="import_upstream_failure",
                retryable=True,
            ),
        )


@router.get("/{scene_id}/preview-manifest")
def get_scene_preview_manifest(scene_id: int):
    manifest = build_scene_preview_manifest(scene_id)
    if not manifest:
        raise HTTPException(404, "הסצנה לא נמצאה.")
    return manifest


@router.get("/{scene_id}")
def get_scene(scene_id: int):
    scene = repo.get_scene(scene_id)
    if not scene:
        raise HTTPException(404, "הסצנה לא נמצאה.")
    return scene


@router.patch("/{scene_id}")
def update_scene(scene_id: int, update: SceneUpdate):
    fields = update.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "לא התקבלו שדות לעדכון.")
    scene = repo.update_scene(scene_id, fields)
    if not scene:
        raise HTTPException(404, "הסצנה לא נמצאה.")
    return scene


@router.post(
    "/{scene_id}/generate-bible",
    summary="Fill in a scene's dramatic-purpose fields (Scene Bible) from its screenplay text using AI",
    description=(
        "Reads the scene's raw imported screenplay text and asks OpenAI to draft "
        "story_goal, emotion, conflict, beginning and ending. Saves the result onto "
        "the scene and returns it. Overwrites any existing values in those fields — "
        "the caller is expected to warn the user before calling this on a scene that "
        "already has bible content filled in."
    ),
)
def generate_bible(scene_id: int):
    scene = repo.get_scene(scene_id)
    if not scene:
        raise HTTPException(404, "הסצנה לא נמצאה.")
    if not (scene.get("raw_scene_text") or "").strip():
        raise HTTPException(409, "לסצנה הזו אין טקסט תסריט גולמי לנתח.")
    project = project_repo.get_project(scene["project_id"])
    try:
        fields = generate_scene_bible(scene, project)
        return repo.update_scene(scene_id, fields)
    except GenerationNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"מילוי ה-Scene Bible נכשל: {exc}")


@router.post(
    "/{scene_id}/shot-map",
    summary="Generate the shot map for one scene (final step of a screenplay import)",
    description=(
        "Called once per scene after POST /api/import-runs/persist, for every "
        "scene that does not already have shots. Refuses to run when the scene "
        "already has shots unless `replace_existing` is explicitly set, so a "
        "retried import never overwrites an existing shot map."
    ),
)
def create_shot_map(scene_id: int, request: ShotMapRequest):
    scene = repo.get_scene(scene_id)
    if not scene:
        raise HTTPException(404, "הסצנה לא נמצאה.")
    project = project_repo.get_project(scene["project_id"])
    assets = [a for a in asset_repo.list_assets(scene["project_id"]) if a["approved"]]
    try:
        generated = generate_shot_map(scene, project, assets, request.shot_count)
        result = repo.create_generated_shots(scene_id, generated, request.replace_existing)
        for item in result["shots"]:
            shot = shot_repo.get_shot(item["id"])
            prompt = build_prompt(shot)
            shot_repo.save_prompt_version(item["id"], prompt, shot.get("negative_prompt", ""), "shot-map")
            shot_repo.update_shot(item["id"], {"prompt": prompt, "status": "פרומפט מוכן"})
        return repo.get_scene(scene_id)
    except GenerationNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"יצירת מפת השוטים נכשלה: {exc}")
