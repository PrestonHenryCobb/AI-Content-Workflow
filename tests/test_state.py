from pipeline.state import JobStatus, Stage


def test_job_upsert_counts_attempts(state):
    state.upsert_job("2026-11-11/slot1", "short", Stage.SCRIPT, JobStatus.RUNNING)
    state.upsert_job("2026-11-11/slot1", "short", Stage.SCRIPT, JobStatus.FAILED, error="x")
    state.upsert_job("2026-11-11/slot1", "short", Stage.SCRIPT, JobStatus.RUNNING)
    row = state.get_job("2026-11-11/slot1")
    assert row["attempts"] == 2
    assert row["status"] == "running"


def test_buffer_fifo(state):
    for i in range(3):
        state.upsert_job(f"b{i}", "short", Stage.QA, JobStatus.DONE)
        state.add_to_buffer(f"b{i}")
    assert state.take_from_buffer("slotA") == "b0"
    assert state.buffer_available() == ["b1", "b2"]


def test_empty_buffer_returns_none(state):
    assert state.take_from_buffer("slotA") is None
