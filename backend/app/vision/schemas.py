from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DetectionItem(BaseModel):
    class_name: str
    class_id: int
    confidence: float = Field(ge=0.0, le=1.0)
    box: tuple[float, float, float, float]
    tracker_id: int | None = None


class TrackStateItem(BaseModel):
    tracker_id: int
    status: Literal["visible", "lost", "out"]
    confidence: float = Field(ge=0.0, le=1.0)
    first_seen_at: datetime
    last_seen_at: datetime
    session_seconds: float = Field(ge=0.0)
    last_seen_seconds_ago: float = Field(ge=0.0)
    detected_now: bool


class DetectionResponse(BaseModel):
    ready: bool
    image_width: int
    image_height: int
    inference_ms: float
    detections: list[DetectionItem]
    tracks: list[TrackStateItem]
