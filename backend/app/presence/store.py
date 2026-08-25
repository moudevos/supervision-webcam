from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class PresenceStore:
    """SQLite persistence for identities, presence sessions and relevant events."""

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
                CREATE TABLE IF NOT EXISTS identities (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS presence_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    identity_id TEXT NOT NULL,
                    tracker_id INTEGER,
                    started_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL CHECK(status IN ('active', 'closed')),
                    identity_score REAL,
                    close_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(identity_id) REFERENCES identities(id)
                );

                CREATE INDEX IF NOT EXISTS idx_presence_sessions_identity_started
                    ON presence_sessions(identity_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_presence_sessions_status
                    ON presence_sessions(status);

                CREATE TABLE IF NOT EXISTS presence_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    identity_id TEXT NOT NULL,
                    tracker_id INTEGER,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    details_json TEXT,
                    FOREIGN KEY(session_id) REFERENCES presence_sessions(id),
                    FOREIGN KEY(identity_id) REFERENCES identities(id)
                );

                CREATE INDEX IF NOT EXISTS idx_presence_events_occurred
                    ON presence_events(occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_presence_events_session
                    ON presence_events(session_id, occurred_at);
                """
            )

    def upsert_identity(self, identity_id: str, name: str, at: datetime) -> None:
        timestamp = _iso(at)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO identities(id, name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    updated_at = excluded.updated_at
                """,
                (identity_id, name, timestamp, timestamp),
            )

    def create_session(
        self,
        *,
        identity_id: str,
        identity_name: str,
        tracker_id: int,
        started_at: datetime,
        last_seen_at: datetime,
        identified_at: datetime,
        identity_score: float | None,
    ) -> int:
        self.upsert_identity(identity_id, identity_name, identified_at)
        now_iso = _iso(identified_at)

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO presence_sessions(
                    identity_id, tracker_id, started_at, last_seen_at,
                    duration_seconds, status, identity_score,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    identity_id,
                    tracker_id,
                    _iso(started_at),
                    _iso(last_seen_at),
                    _duration(started_at, last_seen_at),
                    identity_score,
                    now_iso,
                    now_iso,
                ),
            )
            session_id = int(cursor.lastrowid)
            self._insert_event(
                connection,
                session_id=session_id,
                identity_id=identity_id,
                tracker_id=tracker_id,
                event_type="ENTER",
                occurred_at=started_at,
                details={"source": "track_first_seen"},
            )
            self._insert_event(
                connection,
                session_id=session_id,
                identity_id=identity_id,
                tracker_id=tracker_id,
                event_type="IDENTIFIED",
                occurred_at=identified_at,
                details={"identity_score": identity_score},
            )

        return session_id

    def touch_session(
        self,
        *,
        session_id: int,
        tracker_id: int,
        last_seen_at: datetime,
        identity_score: float | None,
        updated_at: datetime,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT started_at FROM presence_sessions WHERE id = ? AND status = 'active'",
                (session_id,),
            ).fetchone()
            if row is None:
                return

            started_at = _parse(row["started_at"])
            connection.execute(
                """
                UPDATE presence_sessions
                SET tracker_id = ?, last_seen_at = ?, duration_seconds = ?,
                    identity_score = ?, updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (
                    tracker_id,
                    _iso(last_seen_at),
                    _duration(started_at, last_seen_at),
                    identity_score,
                    _iso(updated_at),
                    session_id,
                ),
            )

    def add_event(
        self,
        *,
        session_id: int,
        identity_id: str,
        tracker_id: int | None,
        event_type: str,
        occurred_at: datetime,
        details: dict | None = None,
    ) -> None:
        with self._connect() as connection:
            self._insert_event(
                connection,
                session_id=session_id,
                identity_id=identity_id,
                tracker_id=tracker_id,
                event_type=event_type,
                occurred_at=occurred_at,
                details=details,
            )

    def close_session(
        self,
        *,
        session_id: int,
        identity_id: str,
        tracker_id: int | None,
        ended_at: datetime,
        close_reason: str,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT started_at, status FROM presence_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row is None or row["status"] != "active":
                return

            started_at = _parse(row["started_at"])
            timestamp = _iso(datetime.now(timezone.utc))
            connection.execute(
                """
                UPDATE presence_sessions
                SET ended_at = ?, last_seen_at = ?, duration_seconds = ?,
                    status = 'closed', close_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    _iso(ended_at),
                    _iso(ended_at),
                    _duration(started_at, ended_at),
                    close_reason,
                    timestamp,
                    session_id,
                ),
            )
            self._insert_event(
                connection,
                session_id=session_id,
                identity_id=identity_id,
                tracker_id=tracker_id,
                event_type="EXIT",
                occurred_at=ended_at,
                details={"reason": close_reason},
            )

    def recover_open_sessions(self) -> None:
        """Close sessions left active by a backend/browser interruption."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, identity_id, tracker_id, started_at, last_seen_at
                FROM presence_sessions
                WHERE status = 'active'
                """
            ).fetchall()

            now_iso = _iso(datetime.now(timezone.utc))
            for row in rows:
                started_at = _parse(row["started_at"])
                last_seen_at = _parse(row["last_seen_at"])
                connection.execute(
                    """
                    UPDATE presence_sessions
                    SET ended_at = ?, duration_seconds = ?, status = 'closed',
                        close_reason = 'backend_restart', updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        _iso(last_seen_at),
                        _duration(started_at, last_seen_at),
                        now_iso,
                        row["id"],
                    ),
                )
                tracker_id = int(row["tracker_id"]) if row["tracker_id"] is not None else None
                self._insert_event(
                    connection,
                    session_id=int(row["id"]),
                    identity_id=row["identity_id"],
                    tracker_id=tracker_id,
                    event_type="EXIT",
                    occurred_at=last_seen_at,
                    details={"reason": "backend_restart"},
                )

    def list_sessions(self, limit: int = 30) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    s.id, s.identity_id, i.name AS identity_name, s.tracker_id,
                    s.started_at, s.last_seen_at, s.ended_at,
                    s.duration_seconds, s.status, s.identity_score, s.close_reason
                FROM presence_sessions s
                JOIN identities i ON i.id = s.identity_id
                ORDER BY s.started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, limit: int = 80) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    e.id, e.session_id, e.identity_id, i.name AS identity_name,
                    e.tracker_id, e.event_type, e.occurred_at, e.details_json
                FROM presence_events e
                JOIN identities i ON i.id = e.identity_id
                ORDER BY e.occurred_at DESC, e.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        result: list[dict] = []
        for row in rows:
            item = dict(row)
            raw_details = item.pop("details_json", None)
            item["details"] = json.loads(raw_details) if raw_details else None
            result.append(item)
        return result

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        *,
        session_id: int,
        identity_id: str,
        tracker_id: int | None,
        event_type: str,
        occurred_at: datetime,
        details: dict | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO presence_events(
                session_id, identity_id, tracker_id, event_type,
                occurred_at, details_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
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
