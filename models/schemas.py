from typing import Literal
from pydantic import BaseModel, Field

ShotStatus = Literal[
    "מתוכנן", "רפרנס", "פרומפט מוכן", "תמונה מאושרת",
    "וידאו מוכן", "וידאו מאושר", "אודיו", "QA", "סופי"
]

AssetType = Literal["דמות", "לוקיישן", "אביזר", "לבוש", "כלל", "סגנון"]

class ShotUpdate(BaseModel):
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
    description: str = ""
    visual_rules: str = ""
    master_prompt: str = ""
    negative_prompt: str = ""
    reference_url: str = ""
    approved: bool = False

class AssetLinkRequest(BaseModel):
    asset_ids: list[int]

class SceneUpdate(BaseModel):
    title: str | None = None
    story_goal: str | None = None
    emotion: str | None = None
    conflict: str | None = None
    beginning: str | None = None
    ending: str | None = None
    notes: str | None = None
