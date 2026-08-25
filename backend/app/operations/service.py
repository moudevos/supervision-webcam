from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from time import monotonic

from app.core.config import settings
from app.operations.store import OperationalStore


class OperationalManager:
    """Evaluates module occupancy only from recognized employees in valid zones."""

    incident_type = "MODULE_ABANDONED"

    def __init__(self) -> None:
        self.store = OperationalStore(settings.resolved_presence_db_path)
        self._empty_started_at: datetime | None = None
        self._active_incident_id: int | None = None
        self._last_persisted_monotonic = 0.0
        self._last_status: dict = self._empty_status()
        self._lock = Lock()

    def reset(self, reason: str = "camera_reset") -> None:
        with self._lock:
            now = datetime.now(timezone.utc)
            if self._active_incident_id is not None:
                self.store.close_incident(
                    incident_id=self._active_incident_id,
                    incident_type=self.incident_type,
                    ended_at=now,
                    close_reason=reason,
                )
            self._empty_started_at = None
            self._active_incident_id = None
            self._last_persisted_monotonic = 0.0
            self._last_status = self._empty_status()

    def update(self, tracks: list[dict], zones: list[dict]) -> list[dict]:
        with self._lock:
            now = datetime.now(timezone.utc)
            now_monotonic = monotonic()

            configured_module_names = settings.module_zone_names
            module_names = configured_module_names or [str(zone["name"]) for zone in zones]
            module_keys = {name.casefold() for name in module_names}
            counter_names = settings.counter_zone_names
            counter_keys = {name.casefold() for name in counter_names}
            monitored = bool(module_keys)

            employees = [
                track
                for track in tracks
                if track.get("identity_status") == "confirmed"
                and track.get("identity_id")
                and track.get("status") == "visible"
                and track.get("detected_now")
                and track.get("zone_position_eligible") is not False
            ]

            employees_in_module = [
                track
                for track in employees
                if _zone_key(track.get("current_zone_name")) in module_keys
            ] if monitored else []

            employees_at_counter = [
                track
                for track in employees
                if _zone_key(track.get("current_zone_name")) in counter_keys
            ] if counter_keys else []

            if monitored and not employees_in_module:
                if self._empty_started_at is None:
                    self._empty_started_at = now

                empty_seconds = max(0.0, (now - self._empty_started_at).total_seconds())
                if (
                    self._active_incident_id is None
                    and empty_seconds >= settings.module_empty_confirm_seconds
                ):
                    self._active_incident_id = self.store.create_incident(
                        incident_type=self.incident_type,
                        started_at=self._empty_started_at,
                        confirmed_at=now,
                        details={
                            "module_zones": module_names,
                            "confirm_seconds": settings.module_empty_confirm_seconds,
                        },
                    )
                    self._last_persisted_monotonic = now_monotonic
                elif (
                    self._active_incident_id is not None
                    and now_monotonic - self._last_persisted_monotonic >= 1.0
                ):
                    self.store.touch_incident(self._active_incident_id, now)
                    self._last_persisted_monotonic = now_monotonic
            else:
                empty_seconds = 0.0
                self._empty_started_at = None
                if self._active_incident_id is not None:
                    self.store.close_incident(
                        incident_id=self._active_incident_id,
                        incident_type=self.incident_type,
                        ended_at=now,
                        close_reason="employee_returned",
                        details={
                            "employees_in_module": [
                                str(track.get("identity_name") or track.get("identity_id"))
                                for track in employees_in_module
                            ]
                        },
                    )
                    self._active_incident_id = None
                    self._last_persisted_monotonic = 0.0

            if not monitored:
                empty_seconds = 0.0

            self._last_status = {
                "monitored": monitored,
                "module_zone_names": module_names,
                "counter_zone_names": counter_names,
                "module_empty": monitored and not employees_in_module,
                "module_empty_seconds": round(empty_seconds, 2),
                "module_abandoned": self._active_incident_id is not None,
                "active_incident_id": self._active_incident_id,
                "employees_in_module": [_employee_snapshot(track) for track in employees_in_module],
                "counter_occupied": bool(employees_at_counter),
                "employees_at_counter": [_employee_snapshot(track) for track in employees_at_counter],
                "updated_at": now,
            }

            return [
                self._decorate(track, module_keys, counter_keys)
                for track in tracks
            ]

    def status(self) -> dict:
        with self._lock:
            return dict(self._last_status)

    def history(self, limit: int | None = None, event_limit: int = 200) -> dict:
        return {
            "incidents": self.store.list_incidents(limit or settings.operational_history_limit),
            "events": self.store.list_events(event_limit),
        }

    @staticmethod
    def _decorate(track: dict, module_keys: set[str], counter_keys: set[str]) -> dict:
        enriched = dict(track)
        zone_key = _zone_key(enriched.get("current_zone_name"))
        eligible = enriched.get("zone_position_eligible") is not False
        enriched["in_operational_module"] = bool(
            eligible and zone_key and zone_key in module_keys
        )
        enriched["at_counter"] = bool(
            eligible and zone_key and zone_key in counter_keys
        )
        return enriched

    @staticmethod
    def _empty_status() -> dict:
        return {
            "monitored": False,
            "module_zone_names": [],
            "counter_zone_names": settings.counter_zone_names,
            "module_empty": False,
            "module_empty_seconds": 0.0,
            "module_abandoned": False,
            "active_incident_id": None,
            "employees_in_module": [],
            "counter_occupied": False,
            "employees_at_counter": [],
            "updated_at": None,
        }


def _zone_key(value: object) -> str:
    return str(value).strip().casefold() if value else ""


def _employee_snapshot(track: dict) -> dict:
    return {
        "identity_id": str(track.get("identity_id")),
        "identity_name": str(track.get("identity_name") or track.get("identity_id")),
        "tracker_id": int(track["tracker_id"]) if track.get("tracker_id") is not None else None,
        "zone_id": track.get("current_zone_id"),
        "zone_name": track.get("current_zone_name"),
    }


operational_manager = OperationalManager()
