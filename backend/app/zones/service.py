from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

from app.core.config import settings
from app.zones.store import ZoneStore


@dataclass
class ActiveZone:
    zone_session_id: int
    presence_session_id: int
    identity_id: str
    tracker_id: int
    zone_id: str
    zone_name: str
    entered_at: datetime
    last_seen_at: datetime
    last_persisted_monotonic: float


class ZoneManager:
    """Assigns tracked people to normalized polygons and persists dwell sessions."""

    def __init__(self) -> None:
        self.store = ZoneStore(settings.resolved_presence_db_path)
        self._zones = self.store.list_zones(enabled_only=True)
        self._active: dict[int, ActiveZone] = {}
        self._lock = Lock()

    def list_zones(self) -> list[dict]:
        with self._lock:
            return [dict(zone) for zone in self._zones]

    def create_zone(self, name: str, polygon: list[list[float]]) -> dict:
        clean_name = " ".join(name.strip().split())
        if len(clean_name) < 2:
            raise ValueError("Ingresa un nombre de zona válido.")

        clean_polygon = _validate_polygon(polygon)
        with self._lock:
            if any(zone["name"].casefold() == clean_name.casefold() for zone in self._zones):
                raise ValueError("Ya existe una zona activa con ese nombre.")
            zone = self.store.create_zone(clean_name, clean_polygon, datetime.now(timezone.utc))
            self._reload_zones()
            return zone

    def disable_zone(self, zone_id: str) -> bool:
        with self._lock:
            now = datetime.now(timezone.utc)
            for active in list(self._active.values()):
                if active.zone_id == zone_id:
                    self._close(active, now, "zone_disabled")
            changed = self.store.disable_zone(zone_id, now)
            self._reload_zones()
            return changed

    def reset(self, reason: str = "camera_reset") -> None:
        with self._lock:
            for active in list(self._active.values()):
                self._close(active, active.last_seen_at, reason)
            self._active.clear()

    def update(
        self,
        detections: list[dict],
        tracks: list[dict],
        image_width: int,
        image_height: int,
    ) -> list[dict]:
        with self._lock:
            now = datetime.now(timezone.utc)
            now_monotonic = monotonic()
            positions = _positions_by_tracker(detections, image_width, image_height)
            seen_presence_sessions: set[int] = set()

            for track in tracks:
                presence_session_id = track.get("presence_session_id")
                tracker_id = track.get("tracker_id")
                if tracker_id is None:
                    continue

                tracker_id = int(tracker_id)
                if presence_session_id is None:
                    continue

                presence_session_id = int(presence_session_id)
                seen_presence_sessions.add(presence_session_id)
                active = self._active.get(presence_session_id)

                if track.get("status") == "out":
                    if active is not None:
                        self._close(active, active.last_seen_at, "out_of_scene")
                    continue

                point = positions.get(tracker_id)
                if not track.get("detected_now") or point is None:
                    continue

                zone = self._zone_for_point(point)

                if active is not None and (zone is None or zone["id"] != active.zone_id):
                    self._close(active, now, "zone_change" if zone else "left_zone")
                    active = None

                if zone is not None and active is None and track.get("identity_id"):
                    active = self._open(track, zone, now, now_monotonic)
                    self._active[presence_session_id] = active

                if active is not None:
                    active.tracker_id = tracker_id
                    active.last_seen_at = now
                    if (
                        now_monotonic - active.last_persisted_monotonic
                        >= settings.zone_persist_interval_seconds
                    ):
                        self.store.touch_zone_session(
                            zone_session_id=active.zone_session_id,
                            tracker_id=tracker_id,
                            last_seen_at=now,
                            updated_at=now,
                        )
                        active.last_persisted_monotonic = now_monotonic

            for presence_session_id, active in list(self._active.items()):
                if presence_session_id not in seen_presence_sessions:
                    self._close(active, active.last_seen_at, "presence_missing")

            return [self._decorate(track, positions, now) for track in tracks]

    def history(self, session_limit: int = 50, event_limit: int = 120) -> dict:
        return {
            "sessions": self.store.list_zone_sessions(session_limit),
            "events": self.store.list_zone_events(event_limit),
        }

    def _open(
        self,
        track: dict,
        zone: dict,
        now: datetime,
        now_monotonic: float,
    ) -> ActiveZone:
        presence_session_id = int(track["presence_session_id"])
        identity_id = str(track["identity_id"])
        tracker_id = int(track["tracker_id"])
        zone_session_id = self.store.create_zone_session(
            presence_session_id=presence_session_id,
            identity_id=identity_id,
            tracker_id=tracker_id,
            zone_id=str(zone["id"]),
            entered_at=now,
        )
        return ActiveZone(
            zone_session_id=zone_session_id,
            presence_session_id=presence_session_id,
            identity_id=identity_id,
            tracker_id=tracker_id,
            zone_id=str(zone["id"]),
            zone_name=str(zone["name"]),
            entered_at=now,
            last_seen_at=now,
            last_persisted_monotonic=now_monotonic,
        )

    def _close(self, active: ActiveZone, at: datetime, reason: str) -> None:
        self.store.close_zone_session(
            zone_session_id=active.zone_session_id,
            presence_session_id=active.presence_session_id,
            identity_id=active.identity_id,
            tracker_id=active.tracker_id,
            zone_id=active.zone_id,
            exited_at=at,
            close_reason=reason,
        )
        self._active.pop(active.presence_session_id, None)

    def _decorate(
        self,
        track: dict,
        positions: dict[int, tuple[float, float]],
        now: datetime,
    ) -> dict:
        enriched = dict(track)
        enriched.update(
            {
                "current_zone_id": None,
                "current_zone_name": None,
                "zone_session_id": None,
                "zone_entered_at": None,
                "zone_seconds": None,
            }
        )

        presence_session_id = enriched.get("presence_session_id")
        if presence_session_id is not None:
            active = self._active.get(int(presence_session_id))
            if active is not None:
                enriched.update(
                    {
                        "current_zone_id": active.zone_id,
                        "current_zone_name": active.zone_name,
                        "zone_session_id": active.zone_session_id,
                        "zone_entered_at": active.entered_at,
                        "zone_seconds": round(max(0.0, (now - active.entered_at).total_seconds()), 2),
                    }
                )
                return enriched

        tracker_id = enriched.get("tracker_id")
        if tracker_id is not None and enriched.get("detected_now"):
            point = positions.get(int(tracker_id))
            if point is not None:
                zone = self._zone_for_point(point)
                if zone is not None:
                    enriched["current_zone_id"] = str(zone["id"])
                    enriched["current_zone_name"] = str(zone["name"])

        return enriched

    def _zone_for_point(self, point: tuple[float, float]) -> dict | None:
        candidates = [
            zone for zone in self._zones if _point_in_polygon(point, zone["polygon"])
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda zone: _polygon_area(zone["polygon"]))
        return candidates[0]

    def _reload_zones(self) -> None:
        self._zones = self.store.list_zones(enabled_only=True)


def _positions_by_tracker(
    detections: list[dict],
    image_width: int,
    image_height: int,
) -> dict[int, tuple[float, float]]:
    if image_width <= 0 or image_height <= 0:
        return {}

    positions: dict[int, tuple[float, float]] = {}
    for detection in detections:
        tracker_id = detection.get("tracker_id")
        if tracker_id is None:
            continue
        x1, _, x2, y2 = detection["box"]
        x = ((float(x1) + float(x2)) / 2.0) / image_width
        y = float(y2) / image_height
        positions[int(tracker_id)] = (_clamp01(x), _clamp01(y))
    return positions


def _validate_polygon(polygon: list[list[float]]) -> list[list[float]]:
    if len(polygon) < 3:
        raise ValueError("Una zona necesita al menos 3 puntos.")
    if len(polygon) > 30:
        raise ValueError("Una zona admite como máximo 30 puntos.")

    clean: list[list[float]] = []
    for point in polygon:
        if len(point) != 2:
            raise ValueError("Cada punto debe tener coordenadas x/y.")
        x = float(point[0])
        y = float(point[1])
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError("Las coordenadas de zona deben estar entre 0 y 1.")
        clean.append([round(x, 6), round(y, 6)])

    if _polygon_area(clean) < 0.0005:
        raise ValueError("La zona dibujada es demasiado pequeña o degenerada.")
    return clean


def _point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    x, y = point
    inside = False
    count = len(polygon)
    j = count - 1
    for i in range(count):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _polygon_area(polygon: list[list[float]]) -> float:
    area = 0.0
    for index, point in enumerate(polygon):
        next_point = polygon[(index + 1) % len(polygon)]
        area += point[0] * next_point[1] - next_point[0] * point[1]
    return abs(area) / 2.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


zone_manager = ZoneManager()
