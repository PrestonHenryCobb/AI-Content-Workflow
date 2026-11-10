"""SQLite state: jobs, spend ledger, API quota, published cases, buffer."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pipeline.config import REPO_ROOT

DEFAULT_DB = REPO_ROOT / "data" / "state.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,          -- e.g. 2026-11-11/slot1
    kind        TEXT NOT NULL,             -- short | compilation | trailer
    case_id     TEXT,
    stage       TEXT NOT NULL,
    status      TEXT NOT NULL,             -- pending | running | done | failed | discarded
    attempts    INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    meta        TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spend (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    provider    TEXT NOT NULL,
    stage       TEXT NOT NULL,
    usd         REAL NOT NULL,
    job_id      TEXT,
    meta        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS spend_ts ON spend(ts);
CREATE TABLE IF NOT EXISTS quota (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    api         TEXT NOT NULL,             -- youtube
    quota_day   TEXT NOT NULL,             -- YYYY-MM-DD in the API's reset timezone
    op          TEXT NOT NULL,
    units       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS quota_day_idx ON quota(api, quota_day);
CREATE TABLE IF NOT EXISTS cases (
    case_id     TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL,             -- candidate | verified | published | blocked
    score       REAL,
    meta        TEXT NOT NULL DEFAULT '{}',
    published_at TEXT
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    backend     TEXT NOT NULL,             -- claude_code | api
    model       TEXT NOT NULL,
    stage       TEXT NOT NULL,
    job_id      TEXT,
    ok          INTEGER NOT NULL,
    limit_hit   INTEGER NOT NULL DEFAULT 0,
    duration_s  REAL,
    input_tokens  INTEGER,
    output_tokens INTEGER
);
CREATE INDEX IF NOT EXISTS llm_calls_ts ON llm_calls(ts);
CREATE TABLE IF NOT EXISTS buffer (
    job_id      TEXT PRIMARY KEY REFERENCES jobs(job_id),
    added_at    TEXT NOT NULL,
    used_at     TEXT,
    used_for_slot TEXT
);
"""


class Stage(StrEnum):
    DISCOVER = "discover"
    VERIFY = "verify"
    SCRIPT = "script"
    VOICE = "voice"
    ART = "art"
    RENDER = "render"
    QA = "qa"
    PUBLISH = "publish"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    DISCARDED = "discarded"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class State:
    def __init__(self, path: Path | str = DEFAULT_DB) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.conn:
            yield self.conn

    # ----- jobs -----
    def upsert_job(
        self,
        job_id: str,
        kind: str,
        stage: Stage,
        status: JobStatus,
        case_id: str | None = None,
        error: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        ts = now_iso()
        with self.tx() as c:
            c.execute(
                """
                INSERT INTO jobs (job_id, kind, case_id, stage, status, attempts, error, meta,
                                  created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    stage = excluded.stage,
                    status = excluded.status,
                    case_id = COALESCE(excluded.case_id, jobs.case_id),
                    error = excluded.error,
                    meta = excluded.meta,
                    attempts = jobs.attempts
                        + (CASE WHEN excluded.status = 'running' THEN 1 ELSE 0 END),
                    updated_at = excluded.updated_at
                """,
                (job_id, kind, case_id, stage.value, status.value,
                 1 if status is JobStatus.RUNNING else 0, error,
                 json.dumps(meta or {}, sort_keys=True), ts, ts),
            )

    def get_job(self, job_id: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return row

    # ----- spend -----
    def record_spend(
        self, provider: str, stage: str, usd: float,
        job_id: str | None = None, meta: dict[str, Any] | None = None, ts: str | None = None,
    ) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO spend (ts, provider, stage, usd, job_id, meta) VALUES (?,?,?,?,?,?)",
                (ts or now_iso(), provider, stage, usd, job_id,
                 json.dumps(meta or {}, sort_keys=True)),
            )

    def spend_since(self, since_iso: str, provider: str | None = None) -> float:
        q = "SELECT COALESCE(SUM(usd), 0) FROM spend WHERE ts >= ?"
        args: list[Any] = [since_iso]
        if provider:
            q += " AND provider = ?"
            args.append(provider)
        return float(self.conn.execute(q, args).fetchone()[0])

    def spend_by_provider_since(self, since_iso: str) -> dict[str, float]:
        rows = self.conn.execute(
            "SELECT provider, SUM(usd) FROM spend WHERE ts >= ? GROUP BY provider", (since_iso,)
        ).fetchall()
        return {r[0]: float(r[1]) for r in rows}

    # ----- quota -----
    def record_quota(self, api: str, quota_day: str, op: str, units: int) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO quota (ts, api, quota_day, op, units) VALUES (?,?,?,?,?)",
                (now_iso(), api, quota_day, op, units),
            )

    def quota_used(self, api: str, quota_day: str) -> int:
        return int(self.conn.execute(
            "SELECT COALESCE(SUM(units), 0) FROM quota WHERE api = ? AND quota_day = ?",
            (api, quota_day),
        ).fetchone()[0])

    # ----- llm calls (subscription usage) -----
    def record_llm_call(
        self, backend: str, model: str, stage: str, ok: bool, limit_hit: bool = False,
        job_id: str | None = None, duration_s: float | None = None,
        input_tokens: int | None = None, output_tokens: int | None = None,
        ts: str | None = None,
    ) -> None:
        with self.tx() as c:
            c.execute(
                """INSERT INTO llm_calls (ts, backend, model, stage, job_id, ok, limit_hit,
                                          duration_s, input_tokens, output_tokens)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (ts or now_iso(), backend, model, stage, job_id, int(ok), int(limit_hit),
                 duration_s, input_tokens, output_tokens),
            )

    def llm_calls_since(self, since_iso: str, backend: str = "claude_code") -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM llm_calls WHERE ts >= ? AND backend = ?",
            (since_iso, backend),
        ).fetchone()[0])

    def limit_hits_since(self, since_iso: str, backend: str = "claude_code") -> list[str]:
        rows = self.conn.execute(
            "SELECT ts FROM llm_calls WHERE ts >= ? AND backend = ? AND limit_hit = 1 "
            "ORDER BY ts", (since_iso, backend),
        ).fetchall()
        return [r[0] for r in rows]

    # ----- buffer -----
    def add_to_buffer(self, job_id: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT OR IGNORE INTO buffer (job_id, added_at) VALUES (?, ?)",
                (job_id, now_iso()),
            )

    def buffer_available(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT job_id FROM buffer WHERE used_at IS NULL ORDER BY added_at"
        ).fetchall()
        return [r[0] for r in rows]

    def take_from_buffer(self, slot: str) -> str | None:
        """Atomically claim the oldest unused buffered video for a slot."""
        with self.tx() as c:
            row = c.execute(
                "SELECT job_id FROM buffer WHERE used_at IS NULL ORDER BY added_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            c.execute(
                "UPDATE buffer SET used_at = ?, used_for_slot = ? WHERE job_id = ?",
                (now_iso(), slot, row[0]),
            )
            return str(row[0])
