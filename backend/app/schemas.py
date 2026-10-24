"""Strict, versioned edit-plan schema. LLM output is only ever parsed into these models."""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

HEX = r"^#[0-9a-fA-F]{6}$"


class SubStyle(BaseModel):
    font: str = Field("Nirmala UI", pattern=r"^[\w .-]{1,60}$")
    size: int = Field(56, ge=10, le=140)
    color: str = Field("#FFFFFF", pattern=HEX)
    highlight: str = Field("#FFD54A", pattern=HEX)
    outline: str = Field("#000000", pattern=HEX)
    outline_width: int = Field(3, ge=0, le=12)
    position: Literal["bottom", "center", "top"] = "bottom"
    background: bool = False


class Segment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    enabled: bool = True


class EditPlan(BaseModel):
    version: int = 1
    aspect: Literal["9:16", "16:9", "1:1"] = "16:9"
    resolution: Literal[720, 1080] = 720
    fps: int = Field(30, ge=12, le=60)
    codec: Literal["libx264", "h264_amf", "libx265"] = "libx264"
    trim_start: float = Field(0, ge=0)
    trim_end: Optional[float] = Field(None, gt=0)
    segments: Optional[List[Segment]] = None
    remove_silence: bool = False
    silence_db: float = Field(-35, ge=-60, le=-15)
    silence_min: float = Field(0.6, ge=0.2, le=3)
    zoom: Literal["none", "in", "out"] = "none"
    zoom_amount: float = Field(0.1, ge=0.02, le=0.3)
    fade_in: float = Field(0, ge=0, le=3)
    fade_out: float = Field(0, ge=0, le=3)
    audio_fade: bool = True
    speed: float = Field(1.0, ge=0.5, le=2.0)
    brightness: float = Field(0, ge=-0.3, le=0.3)
    contrast: float = Field(1, ge=0.5, le=2)
    saturation: float = Field(1, ge=0, le=2)
    normalize_audio: bool = True
    noise_reduction: bool = False
    subtitles: bool = False
    karaoke: bool = False
    language: Optional[Literal["bn", "en"]] = None
    subtitle_style: SubStyle = SubStyle()


class PlanPatch(BaseModel):
    """What the LLM / rule parser may change. Unknown keys are ignored."""
    aspect: Optional[Literal["9:16", "16:9", "1:1"]] = None
    resolution: Optional[Literal[720, 1080]] = None
    remove_silence: Optional[bool] = None
    zoom: Optional[Literal["none", "in", "out"]] = None
    fade_in: Optional[float] = Field(None, ge=0, le=3)
    fade_out: Optional[float] = Field(None, ge=0, le=3)
    speed: Optional[float] = Field(None, ge=0.5, le=2.0)
    noise_reduction: Optional[bool] = None
    normalize_audio: Optional[bool] = None
    subtitles: Optional[bool] = None
    karaoke: Optional[bool] = None
    language: Optional[Literal["bn", "en"]] = None
    brightness: Optional[float] = Field(None, ge=-0.3, le=0.3)
    contrast: Optional[float] = Field(None, ge=0.5, le=2)
    saturation: Optional[float] = Field(None, ge=0, le=2)


class Word(BaseModel):
    w: str = Field(max_length=100)
    s: float
    e: float


class Cue(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str = Field(max_length=600)
    words: List[Word] = []


class ProjectCreate(BaseModel):
    name: str = Field("Untitled", min_length=1, max_length=120)
    media_id: Optional[str] = Field(None, pattern=r"^[0-9a-f]{12}$")
    preset: Optional[str] = None


class ProjectUpdate(BaseModel):
    media_id: Optional[str] = Field(None, pattern=r"^[0-9a-f]{12}$")
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    plan: Optional[EditPlan] = None
    subtitles: Optional[List[Cue]] = None


class PlanRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)
    base_plan: Optional[EditPlan] = None


class TranscribeRequest(BaseModel):
    project_id: str = Field(pattern=r"^[0-9a-f]{12}$")
    language: Optional[Literal["bn", "en"]] = None


class RenderRequest(BaseModel):
    project_id: str = Field(pattern=r"^[0-9a-f]{12}$")


class ModelDownload(BaseModel):
    id: str = Field(max_length=60)


class SettingsPatch(BaseModel):
    whisper_model: Optional[Literal["base", "small"]] = None
    ollama_model: Optional[str] = Field(None, pattern=r"^[\w.:-]{1,60}$")
    default_resolution: Optional[Literal[720, 1080]] = None
    default_codec: Optional[Literal["libx264", "h264_amf", "libx265"]] = None
    subtitle_font: Optional[str] = Field(None, pattern=r"^[\w .-]{1,60}$")
