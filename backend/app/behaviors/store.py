from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class BehaviorStore:
    """SQLite persistence for sustained behavior signals and their lifecycle."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self.recover_open_incidents()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS behavior_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    behavior_type TEXT NOT NULL,
                    identity_id TEXT NOT NULL,
                    tracker_id INTEGER,
                    started_at TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL CHECK(status IN ('active', 'closed')),
                    close_reason TEXT,
                    details_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(identity_id) REFERENCES identities(id)
                );

                CREATE INDEX IF NOT EXISTS idx_behavior_incidents_identity_started
                    ON behavior_incidents(identity_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_behavior_incidents_type_status
                    ON behavior_incidents(behavior_type, status);

                CREATE TABLE IF NOT EXISTS behavior_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id INTEGER NOT NULL,
                    behavior_type TEXT NOT NULL,
                    identity_id TEXT NOT NULL,
                    tracker_id INTEGER,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    details_json TEXT,
                    FOREIGN KEY(incident_id) REFERENCES behavior_incidents(id),
                    FOREIGN KEY(identity_id) REFERENCES identities(id)
                );

                CREATE INDEX IF NOT EXISTS idx_behavior_events_occurred
                    ON behavior_events(occurred_at DESC);
                """
            )

    def create_incident(
        self,
        *,
        behavior_type: str,
        identity_id: str,
        tracker_id: int | None,
        started_at: datetime,
        confirmed_at: datetime,
        last_seen_at: datetime,
        details: dict | None,
    ) -> int:
        timestamp = _iso(confirmed_at)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO behavior_incidents(
                    behavior_type, identity_id, tracker_id, started_at,
                    confirmed_at, last_seen_at, duration_seconds, status,
                    details_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    behavior_type,
                    identity_id,
                    tracker_id,
                    _iso(started_at),
                    timestamp,
                    _iso(last_seen_at),
                    _duration(started_at, last_seen_at),
                    json.dumps(details, ensure_ascii=False) if details else None,
                    timestamp,
                    timestamp,
                ),
            )
            incident_id = int(cursor.lastrowid)
            self._insert_event(
                connection,
                incident_id=incident_id,
                behavior_type=behavior_type,
                identity_id=identity_id,
                tracker_id=tracker_id,
                event_type=f"{behavior_type}_START",
                occurred_at=confirmed_at,
                details={
                    "signal_started_at": _iso(started_at),
                    **(details or {}),
                },
            )
        return incident_id

    def touch_incident(
        self,
        *,
        incident_id: int,
        tracker_id: int | None,
        last_seen_at: datetime,
        details: dict | None = None,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT started_at
                FROM behavior_incidents
                WHERE id = ? AND status = 'active'
                """,
                (incident_id,),
            ).fetchone()
            if row is None:
                return

            started_at = _parse(row["started_at"])
            connection.execute(
                """
                UPDATE behavior_incidents
                SET tracker_id = ?, last_seen_at = ?, duration_seconds = ?,
                    details_json = COALESCE(?, details_json), updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (
                    tracker_id,
                    _iso(last_seen_at),
                    _duration(started_at, last_seen_at),
                    json.dumps(details, ensure_ascii=False) if details else None,
                    _iso(last_seen_at),
                    incident_id,
                ),
            )

    def close_incident(
        self,
        *,
        incident_id: int,
        behavior_type: str,
        identity_id: str,
        tracker_id: int | None,
        ended_at: datetime,
        close_reason: str,
        details: dict | None = None,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT started_at, status
                FROM behavior_incidents
                WHERE id = ?
                """,
                (incident_id,),
            ).fetchone()
            if row is None or row["status"] != "active":
                return

            started_at = _parse(row["started_at"])
            connection.execute(
                """
                UPDATE behavior_incidents
                SET tracker_id = ?, ended_at = ?, last_seen_at = ?,
                    duration_seconds = ?, status = 'closed', close_reason = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    tracker_id,
                    _iso(ended_at),
                    _iso(ended_at),
                    _duration(started_at, ended_at),
                    close_reason,
                    _iso(ended_at),
                    incident_id,
                ),
            )
            self._insert_event(
                connection,
                incident_id=incident_id,
                behavior_type=behavior_type,
                identity_id=identity_id,
                tracker_id=tracker_id,
                event_type=f"{behavior_type}_END",
                occurred_at=ended_at,
                details={"reason": close_reason, **(details or {})},
            )

    def recover_open_incidents(self) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, behavior_type, identity_id, tracker_id,
                       started_at, last_seen_at
                FROM behavior_incidents
                WHERE status = 'active'
                """
            ).fetchall()
            now = datetime.now(timezone.utc)
            for row in rows:
                last_seen_at = _parse(row["last_seen_at"])
                connection.execute(
                    """
                    UPDATE behavior_incidents
                    SET ended_at = ?, duration_seconds = ?, status = 'closed',
                        close_reason = 'backend_restart', updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        _iso(last_seen_at),
                        _duration(_parse(row["started_at"]), last_seen_at),
                        _iso(now),
                        row["id"],
                    ),
                )
                self._insert_event(
                    connection,
                    incident_id=int(row["id"]),
                    behavior_type=str(row["behavior_type"]),
                    identity_id=str(row["identity_id"]),
                    tracker_id=int(row["tracker_id"]) if row["tracker_id"] is not None else None,
                    event_type=f"{row['behavior_type']}_END",
                    occurred_at=last_seen_at,
                    details={"reason": "backend_restart"},
                )

    def list_incidents(self, limit: int = 100) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT b.id, b.behavior_type, b.identity_id,
                       i.name AS identity_name, b.tracker_id,
                       b.started_at, b.confirmed_at, b.last_seen_at,
                       b.ended_at, b.duration_seconds, b.status,
                       b.close_reason, b.details_json
                FROM behavior_incidents b
                JOIN identities i ON i.id = b.identity_id
                ORDER BY b.started_at DESC, b.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        result: list[dict] = []
        for row in rows:
            item = dict(row)
            raw = item.pop("details_json", None)
            item["details"] = json.loads(raw) if raw else None
            result.append(item)
        return result

    def list_events(self, limit: int = 200) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.id, e.incident_id, e.behavior_type,
                       e.identity_id, i.name AS identity_name,
                       e.tracker_id, e.event_type, e.occurred_at,
                       e.details_json
                FROM behavior_events e
                JOIN identities i ON i.id = e.identity_id
                ORDER BY e.occurred_at DESC, e.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        result: list[dict] = []
        for row in rows:
            item = dict(row)
            raw = item.pop("details_json", None)
            item["details"] = json.loads(raw) if raw else None
            result.append(item)
        return result

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        *,
        incident_id: int,
        behavior_type: str,
        identity_id: str,
        tracker_id: int | None,
        event_type: str,
        occurred_at: datetime,
        details: dict | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO behavior_events(
                incident_id, behavior_type, identity_id, tracker_id,
                event_type, occurred_at, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                incident_id,
                behavior_type,
                identity_id,
                tracker_id,
                event_type,
                _iso(occurred_at),
                json.dumps(details, ensure_ascii=False) if details else None,
            ),
        )


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _duration(started_at: datetime, ended_at: datetime) -> float:
    return round(max(0.0, (ended_at - started_at).total_seconds()), 2)
