from typing import Any, Literal
from pydantic import BaseModel, Field

ShotStatus = Literal[
    "מתוכנן", "רפרנס", "פרומפט מוכן", "תמונה מאושרת",
    "וידאו מוכן", "וידאו מאושר", "אודיו", "QA", "סופי"
]

ShotType = Literal[
    "רגיל", "Establishing", "Close-up", "Medium", "Wide",
    "Insert", "POV", "Reaction", "Transition"
]

AssetType = Literal["דמות", "לוקיישן", "אביזר", "לבוש", "כלל", "סגנון"]
AssetLockStatus = Literal["draft", "review", "locked"]

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=10000)
    visual_style: str = Field(default="", max_length=10000)
    rules: str = Field(default="", max_length=10000)

class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=300)
    description: str | None = Field(None, max_length=10000)
    visual_style: str | None = Field(None, max_length=10000)
    rules: str | None = Field(None, max_length=10000)

class ShotUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    scene_id: int | None = None
    shot_number: int | None = Field(None, ge=1)
    shot_type: ShotType | None = None
    status: ShotStatus | None = None
    duration_seconds: float | None = Field(None, ge=0.1, le=600)
    notes: str | None = Field(None, max_length=10000)
    camera: str | None = Field(None, max_length=2000)
    camera_angle: str | None = Field(None, max_length=1000)
    composition: str | None = Field(None, max_length=3000)
    action: str | None = Field(None, max_length=5000)
    lens: str | None = Field(None, max_length=1000)
    lighting: str | None = Field(None, max_length=3000)
    movement: str | None = Field(None, max_length=3000)
    mood: str | None = Field(None, max_length=3000)
    color_palette: str | None = Field(None, max_length=2000)
    audio: str | None = Field(None, max_length=5000)
    dialogue: str | None = Field(None, max_length=10000)
    prompt: str | None = Field(None, max_length=30000)
    negative_prompt: str | None = Field(None, max_length=20000)

class ShotCreate(ShotUpdate):
    project_id: int = Field(default=1, ge=1)
    scene_id: int
    shot_number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300)

class AssetCreate(BaseModel):
    project_id: int = Field(default=1, ge=1)
    asset_type: AssetType
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    visual_rules: str = Field(default="", max_length=10000)
    master_prompt: str = Field(default="", max_length=30000)
    negative_prompt: str = Field(default="", max_length=20000)
    reference_url: str = Field(default="", max_length=2000)
    approved: bool = False

class AssetUpdate(BaseModel):
    asset_type: AssetType | None = None
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=10000)
    visual_rules: str | None = Field(None, max_length=10000)
    master_prompt: str | None = Field(None, max_length=30000)
    negative_prompt: str | None = Field(None, max_length=20000)
    reference_url: str | None = Field(None, max_length=2000)
    approved: bool | None = None
    lock_status: AssetLockStatus | None = None

class AssetLockRequest(BaseModel):
    master_reference_id: int = Field(ge=1)

class ReferenceApprovalRequest(BaseModel):
    approved: bool = True

class AssetLinkRequest(BaseModel):
    asset_ids: list[int]

class SceneUpdate(BaseModel):
    scene_number: int | None = Field(None, ge=1)
    status: str | None = Field(None, max_length=100)
    title: str | None = Field(None, max_length=300)
    story_goal: str | None = Field(None, max_length=10000)
    emotion: str | None = Field(None, max_length=3000)
    conflict: str | None = Field(None, max_length=10000)
    beginning: str | None = Field(None, max_length=10000)
    ending: str | None = Field(None, max_length=10000)
    notes: str | None = Field(None, max_length=10000)

class SceneCreate(BaseModel):
    project_id: int = Field(default=1, ge=1)
    scene_number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300)
    status: str = Field(default="מתוכנן", max_length=100)
    story_goal: str = Field(default="", max_length=10000)
    emotion: str = Field(default="", max_length=3000)
    conflict: str = Field(default="", max_length=10000)
    beginning: str = Field(default="", max_length=10000)
    ending: str = Field(default="", max_length=10000)
    notes: str = Field(default="", max_length=10000)

class ScriptImportRequest(BaseModel):
    project_id: int = Field(ge=1)
    screenplay: str = Field(min_length=50, max_length=500000)
    replace_existing: bool = False
    generate_shot_maps: bool = True
    target_shots_per_minute: float = Field(default=5.0, ge=1.0, le=12.0)

class MediaResultCreate(BaseModel):
    media_type: Literal["image", "video"]
    url: str = Field(min_length=1, max_length=4000)
    provider: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)
    prompt_version_id: int | None = None
    status: str = Field(default="טיוטה", max_length=100)
    notes: str = Field(default="", max_length=10000)
    metadata: dict[str, Any] = Field(default_factory=dict)

class GenerationRequest(BaseModel):
    media_type: Literal["text", "image", "video"]
    instructions: str = Field(default="", max_length=5000)
    size: Literal["1024x1024", "1536x1024", "1024x1536"] = "1536x1024"
    quality: Literal["low", "medium", "high"] = "medium"

class ShotMapRequest(BaseModel):
    shot_count: int = Field(default=6, ge=1, le=60)
    replace_existing: bool = False

class CharacterReferenceRequest(BaseModel):
    view_type: Literal["portrait", "full_body", "three_quarter"] = "portrait"
    instructions: str = Field(default="", max_length=3000)

class ContinuityIssueCreate(BaseModel):
    project_id: int = Field(default=1, ge=1)
    shot_id: int | None = None
    asset_id: int | None = None
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    category: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=5000)
    status: Literal["פתוח", "בטיפול", "נפתר", "אושר כחריגה"] = "פתוח"
    expected: str = Field(default="", max_length=5000)
    observed: str = Field(default="", max_length=5000)
    resolution: str = Field(default="", max_length=5000)

class ContinuityIssueUpdate(BaseModel):
    severity: Literal["low", "medium", "high", "critical"] | None = None
    category: str | None = Field(None, min_length=1, max_length=200)
    message: str | None = Field(None, min_length=1, max_length=5000)
    status: Literal["פתוח", "בטיפול", "נפתר", "אושר כחריגה"] | None = None
    expected: str | None = Field(None, max_length=5000)
    observed: str | None = Field(None, max_length=5000)
    resolution: str | None = Field(None, max_length=5000)
