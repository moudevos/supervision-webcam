from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter

from app.core.config import settings


@dataclass
class TrackState:
    tracker_id: int
    first_seen_monotonic: float
    last_seen_monotonic: float
    first_seen_at: datetime
    last_seen_at: datetime
    confidence: float


class TrackStateManager:
    """Maintains short-lived temporal state for ByteTrack IDs."""

    def __init__(
        self,
        visible_grace_seconds: float,
        lost_threshold_seconds: float,
        retention_seconds: float,
    ) -> None:
        self.visible_grace_seconds = visible_grace_seconds
        self.lost_threshold_seconds = lost_threshold_seconds
        self.retention_seconds = retention_seconds
        self._tracks: dict[int, TrackState] = {}

    def reset(self) -> None:
        self._tracks.clear()

    def update(self, detections: list[dict]) -> list[dict]:
        now_monotonic = perf_counter()
        now_wall = datetime.now(timezone.utc)
        detected_ids: set[int] = set()

        for detection in detections:
            tracker_id = detection.get("tracker_id")
            if tracker_id is None:
                continue

            tracker_id = int(tracker_id)
            detected_ids.add(tracker_id)
            confidence = float(detection.get("confidence", 0.0))

            state = self._tracks.get(tracker_id)
            if state is None:
                self._tracks[tracker_id] = TrackState(
                    tracker_id=tracker_id,
                    first_seen_monotonic=now_monotonic,
                    last_seen_monotonic=now_monotonic,
                    first_seen_at=now_wall,
                    last_seen_at=now_wall,
                    confidence=confidence,
                )
                continue

            state.last_seen_monotonic = now_monotonic
            state.last_seen_at = now_wall
            state.confidence = confidence

        self._prune_old_tracks(now_monotonic)

        summaries = [
            self._serialize(state, now_monotonic, state.tracker_id in detected_ids)
            for state in self._tracks.values()
        ]
        summaries.sort(key=lambda item: item["tracker_id"])
        return summaries

    def _status_for(self, seconds_since_seen: float, detected_now: bool) -> str:
        if detected_now or seconds_since_seen <= self.visible_grace_seconds:
            return "visible"
        if seconds_since_seen <= self.lost_threshold_seconds:
            return "lost"
        return "out"

    def _serialize(
        self,
        state: TrackState,
        now_monotonic: float,
        detected_now: bool,
    ) -> dict:
        seconds_since_seen = max(0.0, now_monotonic - state.last_seen_monotonic)
        session_seconds = max(0.0, state.last_seen_monotonic - state.first_seen_monotonic)

        return {
            "tracker_id": state.tracker_id,
            "status": self._status_for(seconds_since_seen, detected_now),
            "confidence": state.confidence,
            "first_seen_at": state.first_seen_at,
            "last_seen_at": state.last_seen_at,
            "session_seconds": round(session_seconds, 2),
            "last_seen_seconds_ago": round(seconds_since_seen, 2),
            "detected_now": detected_now,
        }

    def _prune_old_tracks(self, now_monotonic: float) -> None:
        remove_after = self.lost_threshold_seconds + self.retention_seconds
        stale_ids = [
            tracker_id
            for tracker_id, state in self._tracks.items()
            if now_monotonic - state.last_seen_monotonic > remove_after
        ]

        for tracker_id in stale_ids:
            del self._tracks[tracker_id]


track_state_manager = TrackStateManager(
    visible_grace_seconds=settings.track_visible_grace_seconds,
    lost_threshold_seconds=settings.track_lost_threshold_seconds,
    retention_seconds=settings.track_retention_seconds,
)
