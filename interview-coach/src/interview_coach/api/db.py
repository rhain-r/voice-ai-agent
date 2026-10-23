"""SQLite persistence for sessions and reports (spec §5.8). JSON payloads live in text columns."""

import json
import secrets
import sqlite3
import string
import threading
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

ReportStatus = Literal["pending", "ready", "failed", "empty"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    setup TEXT NOT NULL,
    completion_status TEXT,
    payload TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    status TEXT NOT NULL,
    scorecard TEXT,
    error TEXT,
    updated_at REAL NOT NULL
);
"""
_ALPHABET = string.ascii_lowercase + string.digits


def _new_id() -> str:
    return "s_" + "".join(secrets.choice(_ALPHABET) for _ in range(10))


def _loads(value: str | None):
    return json.loads(value) if value else None


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(_SCHEMA)

    def create(self, setup: BaseModel) -> str:
        session_id = _new_id()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO sessions (id, created_at, setup) VALUES (?, ?, ?)",
                (session_id, time.time(), setup.model_dump_json()),
            )
        return session_id

    def complete(self, session_id: str, payload: BaseModel) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE sessions SET completion_status = ?, payload = ? WHERE id = ?",
                (getattr(payload, "status", "completed"), payload.model_dump_json(), session_id),
            )

    def set_report(
        self,
        session_id: str,
        status: ReportStatus,
        scorecard: dict | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO reports (session_id, status, scorecard, error, updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET status = excluded.status, "
                "scorecard = excluded.scorecard, error = excluded.error, updated_at = excluded.updated_at",
                (session_id, status, json.dumps(scorecard) if scorecard else None, error, time.time()),
            )

    def get(self, session_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT s.*, r.status AS report_status, r.scorecard, r.error FROM sessions s "
                "LEFT JOIN reports r ON r.session_id = s.id WHERE s.id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "setup": _loads(row["setup"]),
            "completion_status": row["completion_status"],
            "payload": _loads(row["payload"]),
            "report_status": row["report_status"],
            "scorecard": _loads(row["scorecard"]),
            "error": row["error"],
        }

    def list(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT s.id, s.created_at, s.setup, s.completion_status, r.status AS report_status, "
                "r.scorecard FROM sessions s LEFT JOIN reports r ON r.session_id = s.id "
                "ORDER BY s.rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "session_id": row["id"],
                "created_at": row["created_at"],
                "setup": _loads(row["setup"]),
                "completion_status": row["completion_status"],
                "report_status": row["report_status"],
                "overall": (_loads(row["scorecard"]) or {}).get("overall"),
            }
            for row in rows
        ]
