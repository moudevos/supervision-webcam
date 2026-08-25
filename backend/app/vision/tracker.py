from __future__ import annotations

import numpy as np
import supervision as sv


class PersonTracker:
    """Stateful ByteTrack wrapper for a single active camera stream."""

    def __init__(self, frame_rate: int = 4) -> None:
        self.frame_rate = frame_rate
        self._tracker = self._build_tracker()

    def _build_tracker(self) -> sv.ByteTrack:
        return sv.ByteTrack(frame_rate=self.frame_rate)

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
