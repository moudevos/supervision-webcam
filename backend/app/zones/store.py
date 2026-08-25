from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class ZoneStore:
    """SQLite persistence for zone definitions, zone sessions and zone events."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self.recover_open_sessions()

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
                CREATE TABLE IF NOT EXISTS zones (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    polygon_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_zones_enabled
                    ON zones(enabled, name);

                CREATE TABLE IF NOT EXISTS zone_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    presence_session_id INTEGER NOT NULL,
                    identity_id TEXT NOT NULL,
                    tracker_id INTEGER,
                    zone_id TEXT NOT NULL,
                    entered_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    exited_at TEXT,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL CHECK(status IN ('active', 'closed')),
                    close_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(presence_session_id) REFERENCES presence_sessions(id),
                    FOREIGN KEY(identity_id) REFERENCES identities(id),
                    FOREIGN KEY(zone_id) REFERENCES zones(id)
                );

                CREATE INDEX IF NOT EXISTS idx_zone_sessions_presence
                    ON zone_sessions(presence_session_id, entered_at DESC);
                CREATE INDEX IF NOT EXISTS idx_zone_sessions_identity
                    ON zone_sessions(identity_id, entered_at DESC);
                CREATE INDEX IF NOT EXISTS idx_zone_sessions_status
                    ON zone_sessions(status);

                CREATE TABLE IF NOT EXISTS zone_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zone_session_id INTEGER NOT NULL,
                    presence_session_id INTEGER NOT NULL,
                    identity_id TEXT NOT NULL,
                    tracker_id INTEGER,
                    zone_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    details_json TEXT,
                    FOREIGN KEY(zone_session_id) REFERENCES zone_sessions(id),
                    FOREIGN KEY(presence_session_id) REFERENCES presence_sessions(id),
                    FOREIGN KEY(identity_id) REFERENCES identities(id),
                    FOREIGN KEY(zone_id) REFERENCES zones(id)
                );

                CREATE INDEX IF NOT EXISTS idx_zone_events_occurred
                    ON zone_events(occurred_at DESC);
                """
            )

    def create_zone(self, name: str, polygon: list[list[float]], at: datetime) -> dict:
        zone_id = str(uuid4())
        timestamp = _iso(at)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO zones(id, name, polygon_json, enabled, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (zone_id, name, json.dumps(polygon), timestamp, timestamp),
            )
        return self.get_zone(zone_id)

    def get_zone(self, zone_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, name, polygon_json, enabled, created_at, updated_at FROM zones WHERE id = ?",
                (zone_id,),
            ).fetchone()
        if row is None:
            raise KeyError(zone_id)
        return _zone_row(row)

    def list_zones(self, enabled_only: bool = True) -> list[dict]:
        sql = "SELECT id, name, polygon_json, enabled, created_at, updated_at FROM zones"
        params: tuple[object, ...] = ()
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name COLLATE NOCASE, created_at"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_zone_row(row) for row in rows]

    def disable_zone(self, zone_id: str, at: datetime) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE zones SET enabled = 0, updated_at = ? WHERE id = ? AND enabled = 1",
                (_iso(at), zone_id),
            )
        return cursor.rowcount > 0

    def create_zone_session(
        self,
        *,
        presence_session_id: int,
        identity_id: str,
        tracker_id: int,
        zone_id: str,
        entered_at: datetime,
    ) -> int:
        timestamp = _iso(entered_at)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO zone_sessions(
                    presence_session_id, identity_id, tracker_id, zone_id,
                    entered_at, last_seen_at, duration_seconds, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 'active', ?, ?)
                """,
                (
                    presence_session_id,
                    identity_id,
                    tracker_id,
                    zone_id,
                    timestamp,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            zone_session_id = int(cursor.lastrowid)
            self._insert_event(
                connection,
                zone_session_id=zone_session_id,
                presence_session_id=presence_session_id,
                identity_id=identity_id,
                tracker_id=tracker_id,
                zone_id=zone_id,
                event_type="ENTER_ZONE",
                occurred_at=entered_at,
                details=None,
            )
        return zone_session_id

    def touch_zone_session(
        self,
        *,
        zone_session_id: int,
        tracker_id: int,
        last_seen_at: datetime,
        updated_at: datetime,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT entered_at FROM zone_sessions WHERE id = ? AND status = 'active'",
                (zone_session_id,),
            ).fetchone()
            if row is None:
                return
            entered_at = _parse(row["entered_at"])
            connection.execute(
                """
                UPDATE zone_sessions
                SET tracker_id = ?, last_seen_at = ?, duration_seconds = ?, updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (
                    tracker_id,
                    _iso(last_seen_at),
                    _duration(entered_at, last_seen_at),
                    _iso(updated_at),
                    zone_session_id,
                ),
            )

    def close_zone_session(
        self,
        *,
        zone_session_id: int,
        presence_session_id: int,
        identity_id: str,
        tracker_id: int | None,
        zone_id: str,
        exited_at: datetime,
        close_reason: str,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT entered_at, status FROM zone_sessions WHERE id = ?",
                (zone_session_id,),
            ).fetchone()
            if row is None or row["status"] != "active":
                return
            entered_at = _parse(row["entered_at"])
            now = datetime.now(timezone.utc)
            connection.execute(
                """
                UPDATE zone_sessions
                SET exited_at = ?, last_seen_at = ?, duration_seconds = ?,
                    status = 'closed', close_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    _iso(exited_at),
                    _iso(exited_at),
                    _duration(entered_at, exited_at),
                    close_reason,
                    _iso(now),
                    zone_session_id,
                ),
            )
            self._insert_event(
                connection,
                zone_session_id=zone_session_id,
                presence_session_id=presence_session_id,
                identity_id=identity_id,
                tracker_id=tracker_id,
                zone_id=zone_id,
                event_type="EXIT_ZONE",
                occurred_at=exited_at,
                details={"reason": close_reason},
            )

    def recover_open_sessions(self) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, presence_session_id, identity_id, tracker_id, zone_id,
                       entered_at, last_seen_at
                FROM zone_sessions
                WHERE status = 'active'
                """
            ).fetchall()
            now = datetime.now(timezone.utc)
            for row in rows:
                entered_at = _parse(row["entered_at"])
                last_seen_at = _parse(row["last_seen_at"])
                connection.execute(
                    """
                    UPDATE zone_sessions
                    SET exited_at = ?, duration_seconds = ?, status = 'closed',
                        close_reason = 'backend_restart', updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        _iso(last_seen_at),
                        _duration(entered_at, last_seen_at),
                        _iso(now),
                        row["id"],
                    ),
                )
                self._insert_event(
                    connection,
                    zone_session_id=int(row["id"]),
                    presence_session_id=int(row["presence_session_id"]),
                    identity_id=str(row["identity_id"]),
                    tracker_id=int(row["tracker_id"]) if row["tracker_id"] is not None else None,
                    zone_id=str(row["zone_id"]),
                    event_type="EXIT_ZONE",
                    occurred_at=last_seen_at,
                    details={"reason": "backend_restart"},
                )

    def list_zone_sessions(self, limit: int = 50) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    zs.id, zs.presence_session_id, zs.identity_id,
                    i.name AS identity_name, zs.tracker_id,
                    zs.zone_id, z.name AS zone_name,
                    zs.entered_at, zs.last_seen_at, zs.exited_at,
                    zs.duration_seconds, zs.status, zs.close_reason
                FROM zone_sessions zs
                JOIN identities i ON i.id = zs.identity_id
                JOIN zones z ON z.id = zs.zone_id
                ORDER BY zs.entered_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_zone_events(self, limit: int = 120) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    ze.id, ze.zone_session_id, ze.presence_session_id,
                    ze.identity_id, i.name AS identity_name, ze.tracker_id,
                    ze.zone_id, z.name AS zone_name, ze.event_type,
                    ze.occurred_at, ze.details_json
                FROM zone_events ze
                JOIN identities i ON i.id = ze.identity_id
                JOIN zones z ON z.id = ze.zone_id
                ORDER BY ze.occurred_at DESC, ze.id DESC
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
        zone_session_id: int,
        presence_session_id: int,
        identity_id: str,
        tracker_id: int | None,
        zone_id: str,
        event_type: str,
        occurred_at: datetime,
        details: dict | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO zone_events(
                zone_session_id, presence_session_id, identity_id, tracker_id,
                zone_id, event_type, occurred_at, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                zone_session_id,
                presence_session_id,
                identity_id,
                tracker_id,
                zone_id,
                event_type,
                _iso(occurred_at),
                json.dumps(details, ensure_ascii=False) if details else None,
            ),
        )


def _zone_row(row: sqlite3.Row) -> dict:
    return {
        "id": str(row["id"]),
        "name": str(row["name"]),
        "polygon": json.loads(row["polygon_json"]),
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


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
