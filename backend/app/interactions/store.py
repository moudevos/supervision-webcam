from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class InteractionStore:
    """SQLite persistence for confirmed person-to-person interactions."""

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
                CREATE TABLE IF NOT EXISTS interaction_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    presence_session_id INTEGER NOT NULL,
                    identity_id TEXT NOT NULL,
                    employee_tracker_id INTEGER,
                    other_tracker_id INTEGER NOT NULL,
                    other_identity_id TEXT,
                    zone_id TEXT,
                    started_at TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL CHECK(status IN ('active', 'closed')),
                    min_distance_ratio REAL NOT NULL,
                    avg_distance_ratio REAL NOT NULL,
                    sample_count INTEGER NOT NULL DEFAULT 1,
                    close_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(presence_session_id) REFERENCES presence_sessions(id),
                    FOREIGN KEY(identity_id) REFERENCES identities(id),
                    FOREIGN KEY(other_identity_id) REFERENCES identities(id),
                    FOREIGN KEY(zone_id) REFERENCES zones(id)
                );

                CREATE INDEX IF NOT EXISTS idx_interaction_sessions_identity_started
                    ON interaction_sessions(identity_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_interaction_sessions_status
                    ON interaction_sessions(status);
                CREATE INDEX IF NOT EXISTS idx_interaction_sessions_other_tracker
                    ON interaction_sessions(other_tracker_id, started_at DESC);

                CREATE TABLE IF NOT EXISTS interaction_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    interaction_session_id INTEGER NOT NULL,
                    presence_session_id INTEGER NOT NULL,
                    identity_id TEXT NOT NULL,
                    employee_tracker_id INTEGER,
                    other_tracker_id INTEGER NOT NULL,
                    other_identity_id TEXT,
                    zone_id TEXT,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    details_json TEXT,
                    FOREIGN KEY(interaction_session_id) REFERENCES interaction_sessions(id),
                    FOREIGN KEY(presence_session_id) REFERENCES presence_sessions(id),
                    FOREIGN KEY(identity_id) REFERENCES identities(id),
                    FOREIGN KEY(other_identity_id) REFERENCES identities(id),
                    FOREIGN KEY(zone_id) REFERENCES zones(id)
                );

                CREATE INDEX IF NOT EXISTS idx_interaction_events_occurred
                    ON interaction_events(occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_interaction_events_session
                    ON interaction_events(interaction_session_id, occurred_at);
                """
            )

    def create_session(
        self,
        *,
        presence_session_id: int,
        identity_id: str,
        employee_tracker_id: int,
        other_tracker_id: int,
        other_identity_id: str | None,
        zone_id: str | None,
        started_at: datetime,
        confirmed_at: datetime,
        distance_ratio: float,
    ) -> int:
        now_iso = _iso(confirmed_at)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO interaction_sessions(
                    presence_session_id, identity_id, employee_tracker_id,
                    other_tracker_id, other_identity_id, zone_id,
                    started_at, confirmed_at, last_seen_at, duration_seconds,
                    status, min_distance_ratio, avg_distance_ratio, sample_count,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, 1, ?, ?)
                """,
                (
                    presence_session_id,
                    identity_id,
                    employee_tracker_id,
                    other_tracker_id,
                    other_identity_id,
                    zone_id,
                    _iso(started_at),
                    now_iso,
                    now_iso,
                    _duration(started_at, confirmed_at),
                    distance_ratio,
                    distance_ratio,
                    now_iso,
                    now_iso,
                ),
            )
            session_id = int(cursor.lastrowid)
            self._insert_event(
                connection,
                interaction_session_id=session_id,
                presence_session_id=presence_session_id,
                identity_id=identity_id,
                employee_tracker_id=employee_tracker_id,
                other_tracker_id=other_tracker_id,
                other_identity_id=other_identity_id,
                zone_id=zone_id,
                event_type="INTERACTION_START",
                occurred_at=confirmed_at,
                details={
                    "proximity_started_at": _iso(started_at),
                    "distance_ratio": round(distance_ratio, 6),
                },
            )
        return session_id

    def touch_session(
        self,
        *,
        session_id: int,
        employee_tracker_id: int,
        other_tracker_id: int,
        other_identity_id: str | None,
        zone_id: str | None,
        last_seen_at: datetime,
        distance_ratio: float,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT started_at, min_distance_ratio, avg_distance_ratio, sample_count
                FROM interaction_sessions
                WHERE id = ? AND status = 'active'
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                return

            started_at = _parse(row["started_at"])
            sample_count = int(row["sample_count"])
            previous_avg = float(row["avg_distance_ratio"])
            next_count = sample_count + 1
            next_avg = ((previous_avg * sample_count) + distance_ratio) / next_count
            next_min = min(float(row["min_distance_ratio"]), distance_ratio)

            connection.execute(
                """
                UPDATE interaction_sessions
                SET employee_tracker_id = ?, other_tracker_id = ?,
                    other_identity_id = ?, zone_id = ?, last_seen_at = ?,
                    duration_seconds = ?, min_distance_ratio = ?,
                    avg_distance_ratio = ?, sample_count = ?, updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (
                    employee_tracker_id,
                    other_tracker_id,
                    other_identity_id,
                    zone_id,
                    _iso(last_seen_at),
                    _duration(started_at, last_seen_at),
                    next_min,
                    next_avg,
                    next_count,
                    _iso(last_seen_at),
                    session_id,
                ),
            )

    def close_session(
        self,
        *,
        session_id: int,
        presence_session_id: int,
        identity_id: str,
        employee_tracker_id: int | None,
        other_tracker_id: int,
        other_identity_id: str | None,
        zone_id: str | None,
        ended_at: datetime,
        close_reason: str,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT started_at, status FROM interaction_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row is None or row["status"] != "active":
                return

            started_at = _parse(row["started_at"])
            now = datetime.now(timezone.utc)
            connection.execute(
                """
                UPDATE interaction_sessions
                SET employee_tracker_id = ?, other_tracker_id = ?,
                    other_identity_id = ?, zone_id = ?, ended_at = ?,
                    last_seen_at = ?, duration_seconds = ?, status = 'closed',
                    close_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    employee_tracker_id,
                    other_tracker_id,
                    other_identity_id,
                    zone_id,
                    _iso(ended_at),
                    _iso(ended_at),
                    _duration(started_at, ended_at),
                    close_reason,
                    _iso(now),
                    session_id,
                ),
            )
            self._insert_event(
                connection,
                interaction_session_id=session_id,
                presence_session_id=presence_session_id,
                identity_id=identity_id,
                employee_tracker_id=employee_tracker_id,
                other_tracker_id=other_tracker_id,
                other_identity_id=other_identity_id,
                zone_id=zone_id,
                event_type="INTERACTION_END",
                occurred_at=ended_at,
                details={"reason": close_reason},
            )

    def recover_open_sessions(self) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, presence_session_id, identity_id, employee_tracker_id,
                       other_tracker_id, other_identity_id, zone_id,
                       started_at, last_seen_at
                FROM interaction_sessions
                WHERE status = 'active'
                """
            ).fetchall()
            now = datetime.now(timezone.utc)
            for row in rows:
                started_at = _parse(row["started_at"])
                last_seen_at = _parse(row["last_seen_at"])
                connection.execute(
                    """
                    UPDATE interaction_sessions
                    SET ended_at = ?, duration_seconds = ?, status = 'closed',
                        close_reason = 'backend_restart', updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        _iso(last_seen_at),
                        _duration(started_at, last_seen_at),
                        _iso(now),
                        row["id"],
                    ),
                )
                self._insert_event(
                    connection,
                    interaction_session_id=int(row["id"]),
                    presence_session_id=int(row["presence_session_id"]),
                    identity_id=str(row["identity_id"]),
                    employee_tracker_id=(
                        int(row["employee_tracker_id"])
                        if row["employee_tracker_id"] is not None
                        else None
                    ),
                    other_tracker_id=int(row["other_tracker_id"]),
                    other_identity_id=(
                        str(row["other_identity_id"])
                        if row["other_identity_id"] is not None
                        else None
                    ),
                    zone_id=str(row["zone_id"]) if row["zone_id"] is not None else None,
                    event_type="INTERACTION_END",
                    occurred_at=last_seen_at,
                    details={"reason": "backend_restart"},
                )

    def list_sessions(self, limit: int = 80) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    s.id, s.presence_session_id, s.identity_id,
                    i.name AS identity_name, s.employee_tracker_id,
                    s.other_tracker_id, s.other_identity_id,
                    oi.name AS other_identity_name,
                    s.zone_id, z.name AS zone_name,
                    s.started_at, s.confirmed_at, s.last_seen_at, s.ended_at,
                    s.duration_seconds, s.status, s.min_distance_ratio,
                    s.avg_distance_ratio, s.sample_count, s.close_reason
                FROM interaction_sessions s
                JOIN identities i ON i.id = s.identity_id
                LEFT JOIN identities oi ON oi.id = s.other_identity_id
                LEFT JOIN zones z ON z.id = s.zone_id
                ORDER BY s.started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, limit: int = 160) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    e.id, e.interaction_session_id, e.presence_session_id,
                    e.identity_id, i.name AS identity_name,
                    e.employee_tracker_id, e.other_tracker_id,
                    e.other_identity_id, oi.name AS other_identity_name,
                    e.zone_id, z.name AS zone_name, e.event_type,
                    e.occurred_at, e.details_json
                FROM interaction_events e
                JOIN identities i ON i.id = e.identity_id
                LEFT JOIN identities oi ON oi.id = e.other_identity_id
                LEFT JOIN zones z ON z.id = e.zone_id
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
        interaction_session_id: int,
        presence_session_id: int,
        identity_id: str,
        employee_tracker_id: int | None,
        other_tracker_id: int,
        other_identity_id: str | None,
        zone_id: str | None,
        event_type: str,
        occurred_at: datetime,
        details: dict | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO interaction_events(
                interaction_session_id, presence_session_id, identity_id,
                employee_tracker_id, other_tracker_id, other_identity_id,
                zone_id, event_type, occurred_at, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                interaction_session_id,
                presence_session_id,
                identity_id,
                employee_tracker_id,
                other_tracker_id,
                other_identity_id,
                zone_id,
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
