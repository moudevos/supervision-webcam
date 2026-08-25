from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.core.config import settings
from app.vision.face_engine import face_engine
from app.vision.face_registry import face_registry


@dataclass
class TrackIdentityState:
    candidate_id: str | None = None
    candidate_name: str | None = None
    candidate_score: float = 0.0
    consecutive_hits: int = 0
    identity_id: str | None = None
    identity_name: str | None = None
    identity_score: float = 0.0


class IdentityManager:
    """Associates face matches with ByteTrack IDs and confirms identity by consensus."""

    def __init__(self) -> None:
        self._states: dict[int, TrackIdentityState] = {}
        self._frame_index = 0

    def reset(self) -> None:
        self._states.clear()
        self._frame_index = 0

    def update(
        self,
        image: np.ndarray,
        detections: list[dict],
        track_states: list[dict],
    ) -> list[dict]:
        self._frame_index += 1
        current_track_ids = {int(item["tracker_id"]) for item in track_states}
        self._prune(current_track_ids)

        should_scan = (
            face_engine.ready
            and not face_registry.empty
            and self._frame_index % settings.face_scan_interval_frames == 0
        )

        if should_scan:
            observations = face_engine.detect(image)
            for observation in observations:
                tracker_id = self._find_tracker_for_face(observation["box"], detections)
                if tracker_id is None:
                    continue

                match = face_registry.match(observation["embedding"])
                self._record_match(tracker_id, match)

        return [self._decorate(item) for item in track_states]

    def _find_tracker_for_face(
        self,
        face_box: tuple[float, float, float, float],
        detections: list[dict],
    ) -> int | None:
        fx1, fy1, fx2, fy2 = face_box
        center_x = (fx1 + fx2) / 2
        center_y = (fy1 + fy2) / 2

        candidates: list[tuple[float, int]] = []
        for detection in detections:
            tracker_id = detection.get("tracker_id")
            if tracker_id is None:
                continue

            x1, y1, x2, y2 = detection["box"]
            if x1 <= center_x <= x2 and y1 <= center_y <= y2:
                area = max(1.0, (x2 - x1) * (y2 - y1))
                candidates.append((area, int(tracker_id)))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _record_match(self, tracker_id: int, match: dict | None) -> None:
        state = self._states.setdefault(tracker_id, TrackIdentityState())

        if match is None:
            if state.identity_id is None:
                state.consecutive_hits = max(0, state.consecutive_hits - 1)
            return

        identity_id = match["identity_id"]
        name = match["name"]
        score = float(match["score"])

        if state.identity_id == identity_id:
            state.identity_score = max(state.identity_score, score)
            return

        if state.identity_id is not None:
            # Once an identity is confirmed for a stable track, do not switch it
            # because of a single contradictory face observation.
            return

        if state.candidate_id == identity_id:
            state.consecutive_hits += 1
            state.candidate_score = max(state.candidate_score, score)
        else:
            state.candidate_id = identity_id
            state.candidate_name = name
            state.candidate_score = score
            state.consecutive_hits = 1

        if state.consecutive_hits >= settings.face_confirm_hits:
            state.identity_id = state.candidate_id
            state.identity_name = state.candidate_name
            state.identity_score = state.candidate_score

    def _decorate(self, track: dict) -> dict:
        tracker_id = int(track["tracker_id"])
        state = self._states.get(tracker_id)

        enriched = dict(track)
        if state is None:
            enriched.update(
                {
                    "identity_status": "unknown",
                    "identity_id": None,
                    "identity_name": None,
                    "identity_score": None,
                }
            )
            return enriched

        if state.identity_id is not None:
            enriched.update(
                {
                    "identity_status": "confirmed",
                    "identity_id": state.identity_id,
                    "identity_name": state.identity_name,
                    "identity_score": round(state.identity_score, 4),
                }
            )
        elif state.candidate_id is not None:
            enriched.update(
                {
                    "identity_status": "candidate",
                    "identity_id": None,
                    "identity_name": None,
                    "identity_score": round(state.candidate_score, 4),
                }
            )
        else:
            enriched.update(
                {
                    "identity_status": "unknown",
                    "identity_id": None,
                    "identity_name": None,
                    "identity_score": None,
                }
            )

        return enriched

    def _prune(self, current_track_ids: set[int]) -> None:
        stale_ids = [tracker_id for tracker_id in self._states if tracker_id not in current_track_ids]
        for tracker_id in stale_ids:
            del self._states[tracker_id]


identity_manager = IdentityManager()
