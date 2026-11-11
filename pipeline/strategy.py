"""Learned strategy (Stage 10): Thompson-sampling bandits + weekly planner overrides.

Everything learned lives in the state DB (persisted on the `state` branch), never in the
code branch, so the pipeline can adapt without committing to its own repo. Safety rules
are fixed text in the prompts; learned notes are appended as *style* notes and can't
override them.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from pipeline.state import State, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS arms (
    job_id  TEXT NOT NULL,
    name    TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (job_id, name)
);
CREATE TABLE IF NOT EXISTS video_stats (
    video_id   TEXT PRIMARY KEY,
    job_id     TEXT,
    fetched_at TEXT NOT NULL,
    views      INTEGER,
    avg_view_pct REAL,
    avg_view_s REAL,
    likes      INTEGER,
    comments   INTEGER,
    subs       INTEGER,
    success    INTEGER          -- 1 if avg_view_pct >= rolling median at labeling time
);
CREATE TABLE IF NOT EXISTS arm_archive (   -- outcome counts folded in from pruned stats
    name    TEXT NOT NULL,                    -- (no YouTube API data is kept here)
    value   TEXT NOT NULL,
    wins    INTEGER NOT NULL DEFAULT 0,
    losses  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (name, value)
);
CREATE TABLE IF NOT EXISTS strategy_kv (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

HOOK_STYLES: dict[str, str] = {
    "impossible_fact": "Open with the single most impossible-sounding verified fact.",
    "last_known": "Open with the last verified moment the person was seen or heard.",
    "wrong_detail": "Open with the one verified detail that doesn't fit the official story.",
    "countdown": "Open with a precise verified time or date that starts a countdown.",
}


def init(state: State) -> None:
    state.conn.executescript(SCHEMA)


def record_arm(state: State, job_id: str, name: str, value: str) -> None:
    init(state)
    with state.tx() as c:
        c.execute("INSERT OR REPLACE INTO arms (job_id, name, value) VALUES (?,?,?)",
                  (job_id, name, value))


def arm_stats(state: State, name: str) -> dict[str, tuple[int, int]]:
    """{value: (wins, losses)} over labeled videos."""
    init(state)
    rows = state.conn.execute(
        "SELECT a.value, SUM(v.success), SUM(1 - v.success) FROM arms a "
        "JOIN video_stats v ON v.job_id = a.job_id WHERE a.name = ? AND v.success IS NOT NULL "
        "GROUP BY a.value", (name,)).fetchall()
    out = {r[0]: (int(r[1] or 0), int(r[2] or 0)) for r in rows}
    for value, w, lo in state.conn.execute(
            "SELECT value, wins, losses FROM arm_archive WHERE name = ?", (name,)):
        a, b = out.get(value, (0, 0))
        out[value] = (a + int(w), b + int(lo))
    return out


def choose(state: State, name: str, options: list[str],
           rng: np.random.Generator | None = None) -> str:
    """Thompson sampling with a Beta(1,1) prior per option."""
    rng = rng or np.random.default_rng()
    stats = arm_stats(state, name)
    draws = {o: rng.beta(1 + stats.get(o, (0, 0))[0], 1 + stats.get(o, (0, 0))[1])
             for o in options}
    return max(draws, key=lambda o: draws[o])


def put(state: State, key: str, value: Any) -> None:
    init(state)
    with state.tx() as c:
        c.execute("INSERT OR REPLACE INTO strategy_kv (key, value, updated_at) VALUES (?,?,?)",
                  (key, json.dumps(value), now_iso()))


def get(state: State, key: str, default: Any = None) -> Any:
    init(state)
    row = state.conn.execute("SELECT value FROM strategy_kv WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default
