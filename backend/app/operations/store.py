from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class OperationalStore:
    """SQLite persistence for operational supervision incidents."""

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
                CREATE TABLE IF NOT EXISTS operational_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_type TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL CHECK(status IN ('active', 'closed')),
                    close_reason TEXT,
                    details_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_operational_incidents_type_started
                    ON operational_incidents(incident_type, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_operational_incidents_status
                    ON operational_incidents(status);

                CREATE TABLE IF NOT EXISTS operational_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    details_json TEXT,
                    FOREIGN KEY(incident_id) REFERENCES operational_incidents(id)
                );

                CREATE INDEX IF NOT EXISTS idx_operational_events_occurred
                    ON operational_events(occurred_at DESC);
                """
            )

    def create_incident(
        self,
        *,
        incident_type: str,
        started_at: datetime,
        confirmed_at: datetime,
        details: dict | None,
    ) -> int:
        timestamp = _iso(confirmed_at)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO operational_incidents(
                    incident_type, started_at, confirmed_at, duration_seconds,
                    status, details_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    incident_type,
                    _iso(started_at),
                    timestamp,
                    _duration(started_at, confirmed_at),
                    json.dumps(details, ensure_ascii=False) if details else None,
                    timestamp,
                    timestamp,
                ),
            )
            incident_id = int(cursor.lastrowid)
            self._insert_event(
                connection,
                incident_id=incident_id,
                event_type=f"{incident_type}_START",
                occurred_at=confirmed_at,
                details={
                    "condition_started_at": _iso(started_at),
                    **(details or {}),
                },
            )
        return incident_id

    def touch_incident(self, incident_id: int, now: datetime) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT started_at
                FROM operational_incidents
                WHERE id = ? AND status = 'active'
                """,
                (incident_id,),
            ).fetchone()
            if row is None:
                return
            started_at = _parse(row["started_at"])
            connection.execute(
                """
                UPDATE operational_incidents
                SET duration_seconds = ?, updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (_duration(started_at, now), _iso(now), incident_id),
            )

    def close_incident(
        self,
        *,
        incident_id: int,
        incident_type: str,
        ended_at: datetime,
        close_reason: str,
        details: dict | None = None,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT started_at, status
                FROM operational_incidents
                WHERE id = ?
                """,
                (incident_id,),
            ).fetchone()
            if row is None or row["status"] != "active":
                return

            started_at = _parse(row["started_at"])
            connection.execute(
                """
                UPDATE operational_incidents
                SET ended_at = ?, duration_seconds = ?, status = 'closed',
                    close_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (
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
                event_type=f"{incident_type}_END",
                occurred_at=ended_at,
                details={"reason": close_reason, **(details or {})},
            )

    def recover_open_incidents(self) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, incident_type, started_at, confirmed_at
                FROM operational_incidents
                WHERE status = 'active'
                """
            ).fetchall()
            now = datetime.now(timezone.utc)
            for row in rows:
                confirmed_at = _parse(row["confirmed_at"])
                connection.execute(
                    """
                    UPDATE operational_incidents
                    SET ended_at = ?, duration_seconds = ?, status = 'closed',
                        close_reason = 'backend_restart', updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        _iso(confirmed_at),
                        _duration(_parse(row["started_at"]), confirmed_at),
                        _iso(now),
                        row["id"],
                    ),
                )
                self._insert_event(
                    connection,
                    incident_id=int(row["id"]),
                    event_type=f"{row['incident_type']}_END",
                    occurred_at=confirmed_at,
                    details={"reason": "backend_restart"},
                )

    def list_incidents(self, limit: int = 100) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, incident_type, started_at, confirmed_at, ended_at,
                       duration_seconds, status, close_reason, details_json
                FROM operational_incidents
                ORDER BY started_at DESC, id DESC
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
                SELECT e.id, e.incident_id, e.event_type, e.occurred_at,
                       e.details_json, i.incident_type
                FROM operational_events e
                JOIN operational_incidents i ON i.id = e.incident_id
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
        event_type: str,
        occurred_at: datetime,
        details: dict | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO operational_events(
                incident_id, event_type, occurred_at, details_json
            ) VALUES (?, ?, ?, ?)
            """,
            (
                incident_id,
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
