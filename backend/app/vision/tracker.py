from __future__ import annotations

import numpy as np
import supervision as sv

from app.core.config import settings


class PersonTracker:
    """Stateful ByteTrack wrapper for a single active camera stream."""

    def __init__(self) -> None:
        self._tracker = self._build_tracker()

    def _build_tracker(self) -> sv.ByteTrack:
        return sv.ByteTrack(
            track_activation_threshold=settings.tracker_activation_threshold,
            lost_track_buffer=settings.tracker_lost_buffer,
            minimum_matching_threshold=settings.tracker_matching_threshold,
            frame_rate=settings.tracker_frame_rate,
            minimum_consecutive_frames=settings.tracker_min_consecutive_frames,
        )

    def reset(self) -> None:
        self._tracker = self._build_tracker()

    def update(self, detections: list[dict]) -> list[dict]:
        if detections:
            supervision_detections = sv.Detections(
                xyxy=np.asarray([item["box"] for item in detections], dtype=np.float32),
                confidence=np.asarray(
                    [item["confidence"] for item in detections], dtype=np.float32
                ),
                class_id=np.asarray(
                    [item["class_id"] for item in detections], dtype=int
                ),
            )
        else:
            supervision_detections = sv.Detections.empty()

        tracked = self._tracker.update_with_detections(supervision_detections)

        result: list[dict] = []
        for index in range(len(tracked)):
            tracker_id = None
            if tracked.tracker_id is not None:
                tracker_id = int(tracked.tracker_id[index])

            confidence = 0.0
            if tracked.confidence is not None:
                confidence = float(tracked.confidence[index])

            class_id = 0
            if tracked.class_id is not None:
                class_id = int(tracked.class_id[index])

            result.append(
                {
                    "class_name": "person",
                    "class_id": class_id,
                    "confidence": confidence,
                    "box": tuple(float(value) for value in tracked.xyxy[index]),
                    "tracker_id": tracker_id,
                }
            )

        return result


tracker = PersonTracker()
