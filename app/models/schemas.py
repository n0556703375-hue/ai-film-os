from typing import Literal
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

class ShotUpdate(BaseModel):
    shot_type: ShotType | None = None
    status: ShotStatus | None = None
    notes: str | None = Field(None, max_length=10000)
    camera: str | None = Field(None, max_length=2000)
    lens: str | None = Field(None, max_length=1000)
    lighting: str | None = Field(None, max_length=3000)
    movement: str | None = Field(None, max_length=3000)
    mood: str | None = Field(None, max_length=3000)
    dialogue: str | None = Field(None, max_length=10000)

class AssetCreate(BaseModel):
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

class AssetLinkRequest(BaseModel):
    asset_ids: list[int]

class SceneUpdate(BaseModel):
    title: str | None = Field(None, max_length=300)
    story_goal: str | None = Field(None, max_length=10000)
    emotion: str | None = Field(None, max_length=3000)
    conflict: str | None = Field(None, max_length=10000)
    beginning: str | None = Field(None, max_length=10000)
    ending: str | None = Field(None, max_length=10000)
    notes: str | None = Field(None, max_length=10000)
