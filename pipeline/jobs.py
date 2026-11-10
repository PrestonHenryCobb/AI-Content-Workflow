"""Job folders: data/jobs/<job_id>/ holds every artifact a stage produces.

A stage whose artifact already exists is skipped, so re-running a job resumes it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from pipeline.config import REPO_ROOT

JOBS_DIR = REPO_ROOT / "data" / "jobs"
M = TypeVar("M", bound=BaseModel)


class Job:
    def __init__(self, job_id: str, root: Path = JOBS_DIR) -> None:
        self.id = job_id
        self.dir = root / job_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self.dir / name

    def has(self, name: str) -> bool:
        return self.path(name).exists()

    def save(self, name: str, model: BaseModel) -> Path:
        p = self.path(name)
        p.write_text(model.model_dump_json(indent=2))
        return p

    def load(self, name: str, cls: type[M]) -> M:
        return cls.model_validate_json(self.path(name).read_text())

    def save_json(self, name: str, data: object) -> Path:
        p = self.path(name)
        p.write_text(json.dumps(data, indent=2, sort_keys=True))
        return p

    def load_json(self, name: str) -> object:
        return json.loads(self.path(name).read_text())
