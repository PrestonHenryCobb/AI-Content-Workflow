"""Clip library: rendered shot clips saved for reuse (DECISIONS D11)."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.config import REPO_ROOT
from pipeline.state import State, now_iso

LIB_DIR = REPO_ROOT / "library" / "clips"

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    clip_id   TEXT PRIMARY KEY,
    path      TEXT NOT NULL,
    template  TEXT NOT NULL,
    move      TEXT NOT NULL,
    mood      TEXT NOT NULL,      -- JSON list
    duration  REAL NOT NULL,
    uses      INTEGER NOT NULL DEFAULT 0,
    added_at  TEXT NOT NULL
);
"""


class Library:
    def __init__(self, state: State, root: Path = LIB_DIR) -> None:
        self.state, self.root = state, root
        self.root.mkdir(parents=True, exist_ok=True)
        state.conn.executescript(SCHEMA)

    def add(self, clip_id: str, path: Path, template: str, move: str, mood: list[str],
            duration: float) -> None:
        with self.state.tx() as c:
            c.execute("INSERT OR REPLACE INTO clips (clip_id, path, template, move, mood, "
                      "duration, added_at) VALUES (?,?,?,?,?,?,?)",
                      (clip_id, str(path), template, move, json.dumps(sorted(mood)), duration,
                       now_iso()))

    def find(self, template: str, mood: list[str], min_duration: float,
             min_score: float = 0.75) -> Path | None:
        """Best unused-ish clip of the same template with enough mood overlap."""
        rows = self.state.conn.execute(
            "SELECT clip_id, path, mood, uses FROM clips WHERE template = ? AND duration >= ?",
            (template, min_duration)).fetchall()
        best: tuple[float, str, str] | None = None
        want = set(mood)
        for clip_id, path, mood_json, uses in rows:
            have = set(json.loads(mood_json))
            overlap = len(want & have) / max(1, len(want | have)) if want else 1.0
            score = overlap - 0.05 * uses
            if overlap >= min_score and Path(path).exists() and (best is None or score > best[0]):
                best = (score, clip_id, path)
        if best is None:
            return None
        with self.state.tx() as c:
            c.execute("UPDATE clips SET uses = uses + 1 WHERE clip_id = ?", (best[1],))
        return Path(best[2])
