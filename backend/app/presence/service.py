from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

from app.core.config import settings
from app.presence.store import PresenceStore


@dataclass
class ActivePresence:
    session_id: int
    identity_id: str
    identity_name: str
    tracker_id: int
    started_at: datetime
    last_seen_at: datetime
    identity_score: float | None
    last_persisted_monotonic: float
    lost_event_emitted: bool = False


class PresenceManager:
    """Turns confirmed identities and temporal track states into durable sessions."""

    def __init__(self) -> None:
        self.store = PresenceStore(settings.resolved_presence_db_path)
        self._active: dict[str, ActivePresence] = {}
        self._lock = Lock()

    def reset(self, close_reason: str = "camera_reset") -> None:
        with self._lock:
            for active in list(self._active.values()):
                self.store.close_session(
                    session_id=active.session_id,
                    identity_id=active.identity_id,
                    tracker_id=active.tracker_id,
                    ended_at=active.last_seen_at,
                    close_reason=close_reason,
                )
            self._active.clear()

    def update(self, tracks: list[dict]) -> list[dict]:
        with self._lock:
            now = datetime.now(timezone.utc)
            now_monotonic = monotonic()
            grouped = self._best_confirmed_track_by_identity(tracks)

            for identity_id, track in grouped.items():
                status = track.get("status")
                active = self._active.get(identity_id)

                if status == "out":
                    if active is not None:
                        self._close(active, track, reason="out_of_scene")
                    continue

                if active is None:
                    active = self._open(track, now, now_monotonic)
                    self._active[identity_id] = active

                self._update_active(active, track, now, now_monotonic)

            return [self._decorate(track) for track in tracks]

    def history(self, session_limit: int | None = None, event_limit: int | None = None) -> dict:
        session_limit = session_limit or settings.presence_history_limit
        event_limit = event_limit or settings.presence_event_limit
        return {
            "sessions": self.store.list_sessions(session_limit),
            "events": self.store.list_events(event_limit),
        }

    def _open(
        self,
        track: dict,
        now: datetime,
        now_monotonic: float,
    ) -> ActivePresence:
        identity_id = str(track["identity_id"])
        identity_name = str(track["identity_name"])
        tracker_id = int(track["tracker_id"])
        started_at = _as_datetime(track["first_seen_at"])
        last_seen_at = _as_datetime(track["last_seen_at"])
        score = _optional_float(track.get("identity_score"))

        session_id = self.store.create_session(
            identity_id=identity_id,
            identity_name=identity_name,
            tracker_id=tracker_id,
            started_at=started_at,
            last_seen_at=last_seen_at,
            identified_at=now,
            identity_score=score,
        )

        return ActivePresence(
            session_id=session_id,
            identity_id=identity_id,
            identity_name=identity_name,
            tracker_id=tracker_id,
            started_at=started_at,
            last_seen_at=last_seen_at,
            identity_score=score,
            last_persisted_monotonic=now_monotonic,
        )

    def _update_active(
        self,
        active: ActivePresence,
        track: dict,
        now: datetime,
        now_monotonic: float,
    ) -> None:
        tracker_id = int(track["tracker_id"])
        tracker_changed = tracker_id != active.tracker_id
        active.tracker_id = tracker_id
        active.identity_name = str(track["identity_name"])
        active.identity_score = _optional_float(track.get("identity_score"))

        if track.get("detected_now"):
            candidate_last_seen = _as_datetime(track["last_seen_at"])
            if candidate_last_seen > active.last_seen_at:
                active.last_seen_at = candidate_last_seen

        status = track.get("status")
        event_written = False

        if status == "lost" and not active.lost_event_emitted:
            self.store.add_event(
                session_id=active.session_id,
                identity_id=active.identity_id,
                tracker_id=active.tracker_id,
                event_type="LOST",
                occurred_at=now,
                details={"last_seen_at": active.last_seen_at.isoformat()},
            )
            active.lost_event_emitted = True
            event_written = True

        if track.get("detected_now") and active.lost_event_emitted:
            self.store.add_event(
                session_id=active.session_id,
                identity_id=active.identity_id,
                tracker_id=active.tracker_id,
                event_type="RETURNED",
                occurred_at=now,
                details={"tracker_changed": tracker_changed},
            )
            active.lost_event_emitted = False
            event_written = True

        should_persist = (
            tracker_changed
            or event_written
            or now_monotonic - active.last_persisted_monotonic
            >= settings.presence_persist_interval_seconds
        )

        if should_persist:
            self.store.touch_session(
                session_id=active.session_id,
                tracker_id=active.tracker_id,
                last_seen_at=active.last_seen_at,
                identity_score=active.identity_score,
                updated_at=now,
            )
            active.last_persisted_monotonic = now_monotonic

    def _close(self, active: ActivePresence, track: dict, reason: str) -> None:
        ended_at = _as_datetime(track.get("last_seen_at", active.last_seen_at))
        if ended_at < active.started_at:
            ended_at = active.last_seen_at

        self.store.close_session(
            session_id=active.session_id,
            identity_id=active.identity_id,
            tracker_id=active.tracker_id,
            ended_at=ended_at,
            close_reason=reason,
        )
        self._active.pop(active.identity_id, None)

    def _decorate(self, track: dict) -> dict:
        enriched = dict(track)
        identity_id = enriched.get("identity_id")
        active = self._active.get(str(identity_id)) if identity_id else None

        if active is None:
            enriched["presence_session_id"] = None
            enriched["presence_started_at"] = None
            return enriched

        enriched["presence_session_id"] = active.session_id
        enriched["presence_started_at"] = active.started_at
        return enriched

    @staticmethod
    def _best_confirmed_track_by_identity(tracks: list[dict]) -> dict[str, dict]:
        grouped: dict[str, dict] = {}

        for track in tracks:
            if track.get("identity_status") != "confirmed" or not track.get("identity_id"):
                continue

            identity_id = str(track["identity_id"])
            current = grouped.get(identity_id)
            if current is None or _track_priority(track) > _track_priority(current):
                grouped[identity_id] = track

        return grouped


def _track_priority(track: dict) -> tuple[int, int, float, float]:
    status_rank = {"visible": 3, "lost": 2, "out": 1}.get(str(track.get("status")), 0)
    detected_rank = 1 if track.get("detected_now") else 0
    identity_score = _optional_float(track.get("identity_score")) or 0.0
    confidence = _optional_float(track.get("confidence")) or 0.0
    return status_rank, detected_rank, identity_score, confidence


def _as_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


presence_manager = PresenceManager()
