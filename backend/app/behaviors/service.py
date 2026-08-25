from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

from app.behaviors.store import BehaviorStore
from app.core.config import settings


@dataclass
class PhoneSignal:
    identity_id: str
    identity_name: str
    tracker_id: int
    started_at: datetime
    last_seen_at: datetime
    confidence: float
    incident_id: int | None = None
    last_persisted_monotonic: float = 0.0


class BehaviorManager:
    """Tracks sustained visual behavior signals for recognized employees."""

    phone_behavior_type = "PHONE_USE_LONG"

    def __init__(self) -> None:
        self.store = BehaviorStore(settings.resolved_presence_db_path)
        self._phone_signals: dict[str, PhoneSignal] = {}
        self._lock = Lock()

    def reset(self, reason: str = "camera_reset") -> None:
        with self._lock:
            for signal in list(self._phone_signals.values()):
                if signal.incident_id is not None:
                    self._close_phone_incident(signal, signal.last_seen_at, reason)
            self._phone_signals.clear()

    def update(
        self,
        objects: list[dict],
        person_detections: list[dict],
        tracks: list[dict],
    ) -> list[dict]:
        with self._lock:
            now = datetime.now(timezone.utc)
            now_monotonic = monotonic()
            track_map = {
                int(track["tracker_id"]): track
                for track in tracks
                if track.get("tracker_id") is not None
            }

            phone_by_tracker = _associate_phones_to_people(
                objects,
                person_detections,
                track_map,
            )

            observed_identity_ids: set[str] = set()
            for tracker_id, phone in phone_by_tracker.items():
                track = track_map.get(tracker_id)
                if track is None:
                    continue
                if track.get("identity_status") != "confirmed" or not track.get("identity_id"):
                    continue
                if not track.get("detected_now") or track.get("status") != "visible":
                    continue
                # Behavior supervision is intentionally limited to the configured
                # operational module to avoid mall/background detections.
                if not track.get("in_operational_module"):
                    continue

                identity_id = str(track["identity_id"])
                observed_identity_ids.add(identity_id)
                confidence = float(phone.get("confidence") or 0.0)
                signal = self._phone_signals.get(identity_id)

                if signal is None or (
                    now - signal.last_seen_at
                ).total_seconds() > settings.phone_use_gap_grace_seconds:
                    if signal is not None and signal.incident_id is not None:
                        self._close_phone_incident(
                            signal,
                            signal.last_seen_at,
                            "phone_signal_gap",
                        )
                    signal = PhoneSignal(
                        identity_id=identity_id,
                        identity_name=str(track.get("identity_name") or identity_id),
                        tracker_id=tracker_id,
                        started_at=now,
                        last_seen_at=now,
                        confidence=confidence,
                    )
                    self._phone_signals[identity_id] = signal
                else:
                    signal.tracker_id = tracker_id
                    signal.identity_name = str(track.get("identity_name") or identity_id)
                    signal.last_seen_at = now
                    signal.confidence = confidence

                visible_seconds = max(0.0, (now - signal.started_at).total_seconds())
                if (
                    signal.incident_id is None
                    and visible_seconds >= settings.phone_use_confirm_seconds
                ):
                    signal.incident_id = self.store.create_incident(
                        behavior_type=self.phone_behavior_type,
                        identity_id=signal.identity_id,
                        tracker_id=signal.tracker_id,
                        started_at=signal.started_at,
                        confirmed_at=now,
                        last_seen_at=now,
                        details={
                            "signal": "cell_phone_visible_near_employee",
                            "threshold_seconds": settings.phone_use_confirm_seconds,
                            "confidence": round(signal.confidence, 4),
                        },
                    )
                    signal.last_persisted_monotonic = now_monotonic
                elif (
                    signal.incident_id is not None
                    and now_monotonic - signal.last_persisted_monotonic >= 1.0
                ):
                    self.store.touch_incident(
                        incident_id=signal.incident_id,
                        tracker_id=signal.tracker_id,
                        last_seen_at=now,
                        details={
                            "signal": "cell_phone_visible_near_employee",
                            "confidence": round(signal.confidence, 4),
                        },
                    )
                    signal.last_persisted_monotonic = now_monotonic

            for identity_id, signal in list(self._phone_signals.items()):
                if identity_id in observed_identity_ids:
                    continue
                if (
                    now - signal.last_seen_at
                ).total_seconds() <= settings.phone_use_gap_grace_seconds:
                    continue
                if signal.incident_id is not None:
                    self._close_phone_incident(
                        signal,
                        signal.last_seen_at,
                        "phone_signal_ended",
                    )
                self._phone_signals.pop(identity_id, None)

            return [self._decorate(track, phone_by_tracker, now) for track in tracks]

    def status(self) -> list[dict]:
        with self._lock:
            now = datetime.now(timezone.utc)
            return [self._signal_to_dict(signal, now) for signal in self._phone_signals.values()]

    def history(self, incident_limit: int | None = None, event_limit: int | None = None) -> dict:
        return {
            "incidents": self.store.list_incidents(
                incident_limit or settings.behavior_history_limit
            ),
            "events": self.store.list_events(
                event_limit or settings.behavior_event_limit
            ),
        }

    def _close_phone_incident(
        self,
        signal: PhoneSignal,
        ended_at: datetime,
        reason: str,
    ) -> None:
        if signal.incident_id is None:
            return
        self.store.close_incident(
            incident_id=signal.incident_id,
            behavior_type=self.phone_behavior_type,
            identity_id=signal.identity_id,
            tracker_id=signal.tracker_id,
            ended_at=ended_at,
            close_reason=reason,
            details={"last_confidence": round(signal.confidence, 4)},
        )
        signal.incident_id = None

    def _decorate(
        self,
        track: dict,
        phone_by_tracker: dict[int, dict],
        now: datetime,
    ) -> dict:
        enriched = dict(track)
        tracker_id = enriched.get("tracker_id")
        identity_id = enriched.get("identity_id")
        enriched["phone_visible_now"] = bool(
            tracker_id is not None and int(tracker_id) in phone_by_tracker
        )
        enriched["phone_visible_seconds"] = 0.0
        enriched["phone_use_long"] = False
        enriched["phone_incident_id"] = None

        if not identity_id:
            return enriched

        signal = self._phone_signals.get(str(identity_id))
        if signal is None:
            return enriched

        enriched["phone_visible_seconds"] = round(
            max(0.0, (now - signal.started_at).total_seconds()),
            2,
        )
        enriched["phone_use_long"] = signal.incident_id is not None
        enriched["phone_incident_id"] = signal.incident_id
        return enriched

    @staticmethod
    def _signal_to_dict(signal: PhoneSignal, now: datetime) -> dict:
        return {
            "behavior_type": "PHONE_USE_LONG",
            "identity_id": signal.identity_id,
            "identity_name": signal.identity_name,
            "tracker_id": signal.tracker_id,
            "phone_visible_seconds": round(
                max(0.0, (now - signal.started_at).total_seconds()),
                2,
            ),
            "phone_visible_now": (
                now - signal.last_seen_at
            ).total_seconds() <= settings.phone_use_gap_grace_seconds,
            "incident_id": signal.incident_id,
            "confirmed": signal.incident_id is not None,
            "confidence": round(signal.confidence, 4),
        }


def _associate_phones_to_people(
    objects: list[dict],
    person_detections: list[dict],
    track_map: dict[int, dict],
) -> dict[int, dict]:
    phones = [item for item in objects if item.get("class_name") == "cell_phone"]
    result: dict[int, dict] = {}

    for phone in phones:
        px1, py1, px2, py2 = [float(value) for value in phone["box"]]
        center_x = (px1 + px2) / 2.0
        center_y = (py1 + py2) / 2.0
        candidates: list[tuple[float, int]] = []

        for person in person_detections:
            tracker_id = person.get("tracker_id")
            if tracker_id is None or int(tracker_id) not in track_map:
                continue
            x1, y1, x2, y2 = [float(value) for value in person["box"]]
            width = max(1.0, x2 - x1)
            height = max(1.0, y2 - y1)
            margin_x = width * settings.phone_association_margin_ratio
            margin_y = height * settings.phone_association_margin_ratio

            if not (
                x1 - margin_x <= center_x <= x2 + margin_x
                and y1 - margin_y <= center_y <= y2 + margin_y
            ):
                continue

            person_center_x = (x1 + x2) / 2.0
            person_center_y = (y1 + y2) / 2.0
            normalized_distance = (
                ((center_x - person_center_x) / width) ** 2
                + ((center_y - person_center_y) / height) ** 2
            )
            candidates.append((normalized_distance, int(tracker_id)))

        if not candidates:
            continue

        _, tracker_id = min(candidates, key=lambda item: item[0])
        existing = result.get(tracker_id)
        if existing is None or float(phone.get("confidence") or 0.0) > float(
            existing.get("confidence") or 0.0
        ):
            result[tracker_id] = phone

    return result


behavior_manager = BehaviorManager()
