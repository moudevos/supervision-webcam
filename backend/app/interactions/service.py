from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import hypot
from threading import Lock
from time import monotonic

from app.core.config import settings
from app.interactions.store import InteractionStore


@dataclass
class PairObservation:
    identity_id: str
    identity_name: str
    presence_session_id: int
    employee_tracker_id: int
    other_tracker_id: int
    zone_id: str | None
    zone_name: str | None
    distance_ratio: float


@dataclass
class CandidateInteraction:
    identity_id: str
    identity_name: str
    presence_session_id: int
    employee_tracker_id: int
    other_tracker_id: int
    zone_id: str | None
    zone_name: str | None
    started_at: datetime
    last_near_at: datetime
    distance_ratio: float


@dataclass
class ActiveInteraction:
    session_id: int
    identity_id: str
    identity_name: str
    presence_session_id: int
    employee_tracker_id: int
    other_tracker_id: int
    zone_id: str | None
    zone_name: str | None
    started_at: datetime
    confirmed_at: datetime
    last_near_at: datetime
    distance_ratio: float
    last_persisted_monotonic: float


class InteractionManager:
    """Confirms sustained proximity between a known employee and an unknown track."""

    def __init__(self) -> None:
        self.store = InteractionStore(settings.resolved_presence_db_path)
        self._candidates: dict[tuple[str, int], CandidateInteraction] = {}
        self._active: dict[tuple[str, int], ActiveInteraction] = {}
        self._lock = Lock()

    def reset(self, reason: str = "camera_reset") -> None:
        with self._lock:
            for active in list(self._active.values()):
                self._close(active, active.last_near_at, reason)
            self._active.clear()
            self._candidates.clear()

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
            track_map = {
                int(track["tracker_id"]): track
                for track in tracks
                if track.get("tracker_id") is not None
            }
            observations = self._near_pairs(track_map, positions)
            observed_keys = set(observations)

            for key, observation in observations.items():
                active = self._active.get(key)
                if active is not None:
                    if active.presence_session_id != observation.presence_session_id:
                        self._close(active, active.last_near_at, "presence_session_changed")
                        active = None
                    else:
                        self._update_active(active, observation, now, now_monotonic)
                        continue

                candidate = self._candidates.get(key)
                if candidate is not None and candidate.presence_session_id != observation.presence_session_id:
                    self._candidates.pop(key, None)
                    candidate = None

                if candidate is None:
                    self._candidates[key] = CandidateInteraction(
                        identity_id=observation.identity_id,
                        identity_name=observation.identity_name,
                        presence_session_id=observation.presence_session_id,
                        employee_tracker_id=observation.employee_tracker_id,
                        other_tracker_id=observation.other_tracker_id,
                        zone_id=observation.zone_id,
                        zone_name=observation.zone_name,
                        started_at=now,
                        last_near_at=now,
                        distance_ratio=observation.distance_ratio,
                    )
                    continue

                candidate.employee_tracker_id = observation.employee_tracker_id
                candidate.zone_id = observation.zone_id
                candidate.zone_name = observation.zone_name
                candidate.last_near_at = now
                candidate.distance_ratio = observation.distance_ratio

                if (now - candidate.started_at).total_seconds() >= settings.interaction_confirm_seconds:
                    active = self._confirm(candidate, now, now_monotonic)
                    self._active[key] = active
                    self._candidates.pop(key, None)

            self._expire_candidates(observed_keys, now)
            self._expire_active(observed_keys, now)
            return [self._decorate(track, now) for track in tracks]

    def history(self, session_limit: int | None = None, event_limit: int | None = None) -> dict:
        return {
            "sessions": self.store.list_sessions(
                session_limit or settings.interaction_history_limit
            ),
            "events": self.store.list_events(
                event_limit or settings.interaction_event_limit
            ),
        }

    def active(self) -> list[dict]:
        with self._lock:
            now = datetime.now(timezone.utc)
            return [self._active_to_dict(active, now) for active in self._active.values()]

    def _near_pairs(
        self,
        track_map: dict[int, dict],
        positions: dict[int, tuple[float, float]],
    ) -> dict[tuple[str, int], PairObservation]:
        employees = [
            track
            for track in track_map.values()
            if track.get("identity_status") == "confirmed"
            and track.get("identity_id")
            and track.get("presence_session_id") is not None
            and track.get("detected_now")
            and track.get("status") == "visible"
        ]

        unknown_tracks = [
            track
            for track in track_map.values()
            if track.get("identity_status") != "confirmed"
            and track.get("detected_now")
            and track.get("status") == "visible"
        ]

        pairs: dict[tuple[str, int], PairObservation] = {}
        for employee in employees:
            employee_tracker_id = int(employee["tracker_id"])
            employee_position = positions.get(employee_tracker_id)
            if employee_position is None:
                continue

            for other in unknown_tracks:
                other_tracker_id = int(other["tracker_id"])
                if other_tracker_id == employee_tracker_id:
                    continue

                other_position = positions.get(other_tracker_id)
                if other_position is None:
                    continue

                employee_zone = employee.get("current_zone_id")
                other_zone = other.get("current_zone_id")
                if employee_zone and other_zone and employee_zone != other_zone:
                    continue

                distance_ratio = _distance(employee_position, other_position)
                if distance_ratio > settings.interaction_distance_threshold:
                    continue

                identity_id = str(employee["identity_id"])
                key = (identity_id, other_tracker_id)
                pairs[key] = PairObservation(
                    identity_id=identity_id,
                    identity_name=str(employee.get("identity_name") or identity_id),
                    presence_session_id=int(employee["presence_session_id"]),
                    employee_tracker_id=employee_tracker_id,
                    other_tracker_id=other_tracker_id,
                    zone_id=str(employee_zone) if employee_zone else None,
                    zone_name=(
                        str(employee.get("current_zone_name"))
                        if employee.get("current_zone_name")
                        else None
                    ),
                    distance_ratio=distance_ratio,
                )

        return pairs

    def _confirm(
        self,
        candidate: CandidateInteraction,
        now: datetime,
        now_monotonic: float,
    ) -> ActiveInteraction:
        session_id = self.store.create_session(
            presence_session_id=candidate.presence_session_id,
            identity_id=candidate.identity_id,
            employee_tracker_id=candidate.employee_tracker_id,
            other_tracker_id=candidate.other_tracker_id,
            other_identity_id=None,
            zone_id=candidate.zone_id,
            started_at=candidate.started_at,
            confirmed_at=now,
            distance_ratio=candidate.distance_ratio,
        )
        return ActiveInteraction(
            session_id=session_id,
            identity_id=candidate.identity_id,
            identity_name=candidate.identity_name,
            presence_session_id=candidate.presence_session_id,
            employee_tracker_id=candidate.employee_tracker_id,
            other_tracker_id=candidate.other_tracker_id,
            zone_id=candidate.zone_id,
            zone_name=candidate.zone_name,
            started_at=candidate.started_at,
            confirmed_at=now,
            last_near_at=now,
            distance_ratio=candidate.distance_ratio,
            last_persisted_monotonic=now_monotonic,
        )

    def _update_active(
        self,
        active: ActiveInteraction,
        observation: PairObservation,
        now: datetime,
        now_monotonic: float,
    ) -> None:
        active.employee_tracker_id = observation.employee_tracker_id
        active.zone_id = observation.zone_id
        active.zone_name = observation.zone_name
        active.last_near_at = now
        active.distance_ratio = observation.distance_ratio

        if (
            now_monotonic - active.last_persisted_monotonic
            >= settings.interaction_persist_interval_seconds
        ):
            self.store.touch_session(
                session_id=active.session_id,
                employee_tracker_id=active.employee_tracker_id,
                other_tracker_id=active.other_tracker_id,
                other_identity_id=None,
                zone_id=active.zone_id,
                last_seen_at=now,
                distance_ratio=active.distance_ratio,
            )
            active.last_persisted_monotonic = now_monotonic

    def _expire_candidates(
        self,
        observed_keys: set[tuple[str, int]],
        now: datetime,
    ) -> None:
        for key, candidate in list(self._candidates.items()):
            if key in observed_keys:
                continue
            if (
                now - candidate.last_near_at
            ).total_seconds() > settings.interaction_exit_grace_seconds:
                self._candidates.pop(key, None)

    def _expire_active(
        self,
        observed_keys: set[tuple[str, int]],
        now: datetime,
    ) -> None:
        for key, active in list(self._active.items()):
            if key in observed_keys:
                continue
            if (
                now - active.last_near_at
            ).total_seconds() > settings.interaction_exit_grace_seconds:
                self._close(active, active.last_near_at, "separated_or_missing")

    def _close(self, active: ActiveInteraction, ended_at: datetime, reason: str) -> None:
        self.store.close_session(
            session_id=active.session_id,
            presence_session_id=active.presence_session_id,
            identity_id=active.identity_id,
            employee_tracker_id=active.employee_tracker_id,
            other_tracker_id=active.other_tracker_id,
            other_identity_id=None,
            zone_id=active.zone_id,
            ended_at=ended_at,
            close_reason=reason,
        )
        self._active.pop((active.identity_id, active.other_tracker_id), None)

    def _decorate(self, track: dict, now: datetime) -> dict:
        enriched = dict(track)
        enriched["interaction_candidate_count"] = 0
        enriched["active_interactions"] = []

        identity_id = enriched.get("identity_id")
        if not identity_id:
            return enriched

        identity_id = str(identity_id)
        enriched["interaction_candidate_count"] = sum(
            1 for key in self._candidates if key[0] == identity_id
        )
        enriched["active_interactions"] = [
            self._active_to_dict(active, now)
            for active in self._active.values()
            if active.identity_id == identity_id
        ]
        return enriched

    @staticmethod
    def _active_to_dict(active: ActiveInteraction, now: datetime) -> dict:
        return {
            "interaction_session_id": active.session_id,
            "other_tracker_id": active.other_tracker_id,
            "other_identity_id": None,
            "other_identity_name": None,
            "zone_id": active.zone_id,
            "zone_name": active.zone_name,
            "started_at": active.started_at,
            "confirmed_at": active.confirmed_at,
            "duration_seconds": round(
                max(0.0, (now - active.started_at).total_seconds()), 2
            ),
            "distance_ratio": round(active.distance_ratio, 6),
        }


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
        foot_x = (float(x1) + float(x2)) / 2.0
        foot_y = float(y2)
        positions[int(tracker_id)] = (
            foot_x / image_width,
            foot_y / image_width,
        )
    return positions


def _distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return hypot(first[0] - second[0], first[1] - second[1])


interaction_manager = InteractionManager()
