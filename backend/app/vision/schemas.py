from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DetectionItem(BaseModel):
    class_name: str
    class_id: int
    confidence: float = Field(ge=0.0, le=1.0)
    box: tuple[float, float, float, float]
    tracker_id: int | None = None


class SceneObjectItem(BaseModel):
    class_name: str
    class_id: int
    confidence: float = Field(ge=0.0, le=1.0)
    box: tuple[float, float, float, float]


class InteractionLiveItem(BaseModel):
    interaction_session_id: int
    other_tracker_id: int
    other_identity_id: str | None = None
    other_identity_name: str | None = None
    zone_id: str | None = None
    zone_name: str | None = None
    started_at: datetime
    confirmed_at: datetime
    duration_seconds: float = Field(ge=0.0)
    distance_ratio: float = Field(ge=0.0)


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
    zone_position_eligible: bool | None = None
    person_height_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    in_operational_module: bool = False
    at_counter: bool = False
    phone_visible_now: bool = False
    phone_visible_seconds: float = Field(default=0.0, ge=0.0)
    phone_use_long: bool = False
    phone_incident_id: int | None = None
    interaction_candidate_count: int = Field(default=0, ge=0)
    active_interactions: list[InteractionLiveItem] = Field(default_factory=list)


class DetectionResponse(BaseModel):
    ready: bool
    image_width: int
    image_height: int
    inference_ms: float
    detections: list[DetectionItem]
    objects: list[SceneObjectItem] = Field(default_factory=list)
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


class InteractionSessionItem(BaseModel):
    id: int
    presence_session_id: int
    identity_id: str
    identity_name: str
    employee_tracker_id: int | None = None
    other_tracker_id: int
    other_identity_id: str | None = None
    other_identity_name: str | None = None
    zone_id: str | None = None
    zone_name: str | None = None
    started_at: datetime
    confirmed_at: datetime
    last_seen_at: datetime
    ended_at: datetime | None = None
    duration_seconds: float = Field(ge=0.0)
    status: Literal["active", "closed"]
    min_distance_ratio: float = Field(ge=0.0)
    avg_distance_ratio: float = Field(ge=0.0)
    sample_count: int = Field(ge=1)
    close_reason: str | None = None


class InteractionEventItem(BaseModel):
    id: int
    interaction_session_id: int
    presence_session_id: int
    identity_id: str
    identity_name: str
    employee_tracker_id: int | None = None
    other_tracker_id: int
    other_identity_id: str | None = None
    other_identity_name: str | None = None
    zone_id: str | None = None
    zone_name: str | None = None
    event_type: Literal["INTERACTION_START", "INTERACTION_END"]
    occurred_at: datetime
    details: dict[str, Any] | None = None


class InteractionHistoryResponse(BaseModel):
    sessions: list[InteractionSessionItem]
    events: list[InteractionEventItem]


class ActiveInteractionResponse(BaseModel):
    interactions: list[InteractionLiveItem]


class OperationalEmployeeItem(BaseModel):
    identity_id: str
    identity_name: str
    tracker_id: int | None = None
    zone_id: str | None = None
    zone_name: str | None = None


class OperationalStatusResponse(BaseModel):
    monitored: bool
    module_zone_names: list[str]
    counter_zone_names: list[str]
    module_empty: bool
    module_empty_seconds: float = Field(ge=0.0)
    module_abandoned: bool
    active_incident_id: int | None = None
    employees_in_module: list[OperationalEmployeeItem]
    counter_occupied: bool
    employees_at_counter: list[OperationalEmployeeItem]
    updated_at: datetime | None = None


class OperationalIncidentItem(BaseModel):
    id: int
    incident_type: Literal["MODULE_ABANDONED"]
    started_at: datetime
    confirmed_at: datetime
    ended_at: datetime | None = None
    duration_seconds: float = Field(ge=0.0)
    status: Literal["active", "closed"]
    close_reason: str | None = None
    details: dict[str, Any] | None = None


class OperationalEventItem(BaseModel):
    id: int
    incident_id: int
    incident_type: Literal["MODULE_ABANDONED"]
    event_type: Literal["MODULE_ABANDONED_START", "MODULE_ABANDONED_END"]
    occurred_at: datetime
    details: dict[str, Any] | None = None


class OperationalHistoryResponse(BaseModel):
    incidents: list[OperationalIncidentItem]
    events: list[OperationalEventItem]


class BehaviorLiveItem(BaseModel):
    behavior_type: Literal["PHONE_USE_LONG"]
    identity_id: str
    identity_name: str
    tracker_id: int | None = None
    phone_visible_seconds: float = Field(ge=0.0)
    phone_visible_now: bool
    incident_id: int | None = None
    confirmed: bool
    confidence: float = Field(ge=0.0, le=1.0)


class BehaviorStatusResponse(BaseModel):
    signals: list[BehaviorLiveItem]


class BehaviorIncidentItem(BaseModel):
    id: int
    behavior_type: Literal["PHONE_USE_LONG"]
    identity_id: str
    identity_name: str
    tracker_id: int | None = None
    started_at: datetime
    confirmed_at: datetime
    last_seen_at: datetime
    ended_at: datetime | None = None
    duration_seconds: float = Field(ge=0.0)
    status: Literal["active", "closed"]
    close_reason: str | None = None
    details: dict[str, Any] | None = None


class BehaviorEventItem(BaseModel):
    id: int
    incident_id: int
    behavior_type: Literal["PHONE_USE_LONG"]
    identity_id: str
    identity_name: str
    tracker_id: int | None = None
    event_type: Literal["PHONE_USE_LONG_START", "PHONE_USE_LONG_END"]
    occurred_at: datetime
    details: dict[str, Any] | None = None


class BehaviorHistoryResponse(BaseModel):
    incidents: list[BehaviorIncidentItem]
    events: list[BehaviorEventItem]
