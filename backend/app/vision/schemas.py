from datetime import datetime
from typing import Any, Literal

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
    identity_status: Literal["unknown", "candidate", "confirmed"] = "unknown"
    identity_id: str | None = None
    identity_name: str | None = None
    identity_score: float | None = None
    presence_session_id: int | None = None
    presence_started_at: datetime | None = None
    current_zone_id: str | None = None
    current_zone_name: str | None = None
    zone_session_id: int | None = None
    zone_entered_at: datetime | None = None
    zone_seconds: float | None = Field(default=None, ge=0.0)


class DetectionResponse(BaseModel):
    ready: bool
    image_width: int
    image_height: int
    inference_ms: float
    detections: list[DetectionItem]
    tracks: list[TrackStateItem]


class FaceRegistrationResponse(BaseModel):
    identity_id: str
    name: str
    sample_count: int


class FaceIdentityItem(BaseModel):
    identity_id: str
    name: str
    sample_count: int


class FaceRegistryResponse(BaseModel):
    ready: bool
    identities: list[FaceIdentityItem]


class PresenceSessionItem(BaseModel):
    id: int
    identity_id: str
    identity_name: str
    tracker_id: int | None = None
    started_at: datetime
    last_seen_at: datetime
    ended_at: datetime | None = None
    duration_seconds: float = Field(ge=0.0)
    status: Literal["active", "closed"]
    identity_score: float | None = None
    close_reason: str | None = None


class PresenceEventItem(BaseModel):
    id: int
    session_id: int
    identity_id: str
    identity_name: str
    tracker_id: int | None = None
    event_type: Literal["ENTER", "IDENTIFIED", "LOST", "RETURNED", "EXIT"]
    occurred_at: datetime
    details: dict[str, Any] | None = None


class PresenceHistoryResponse(BaseModel):
    sessions: list[PresenceSessionItem]
    events: list[PresenceEventItem]


class ZoneCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=30)


class ZoneItem(BaseModel):
    id: str
    name: str
    polygon: list[tuple[float, float]]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ZoneListResponse(BaseModel):
    zones: list[ZoneItem]


class ZoneSessionItem(BaseModel):
    id: int
    presence_session_id: int
    identity_id: str
    identity_name: str
    tracker_id: int | None = None
    zone_id: str
    zone_name: str
    entered_at: datetime
    last_seen_at: datetime
    exited_at: datetime | None = None
    duration_seconds: float = Field(ge=0.0)
    status: Literal["active", "closed"]
    close_reason: str | None = None


class ZoneEventItem(BaseModel):
    id: int
    zone_session_id: int
    presence_session_id: int
    identity_id: str
    identity_name: str
    tracker_id: int | None = None
    zone_id: str
    zone_name: str
    event_type: Literal["ENTER_ZONE", "EXIT_ZONE"]
    occurred_at: datetime
    details: dict[str, Any] | None = None


class ZoneHistoryResponse(BaseModel):
    sessions: list[ZoneSessionItem]
    events: list[ZoneEventItem]
