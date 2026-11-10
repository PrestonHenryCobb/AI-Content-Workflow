from __future__ import annotations

import pytest

from pipeline.config import load_settings
from pipeline.state import State


@pytest.fixture
def state() -> State:
    s = State(":memory:")
    yield s
    s.close()


@pytest.fixture
def settings():
    return load_settings()
