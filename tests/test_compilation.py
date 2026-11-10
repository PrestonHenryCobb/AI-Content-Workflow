import copy
import json
from datetime import UTC, date, datetime

from pipeline import offline
from pipeline.jobs import Job
from pipeline.schemas import CaseCandidate, FactPack, Script
from pipeline.stages import compilation
from pipeline.state import JobStatus, Stage

NOW = datetime(2026, 11, 15, 5, 0, tzinfo=UTC)


def seed(tmp_path, state, n):
    for i in range(n):
        j = Job(f"2026-11-1{i}-01", tmp_path)
        j.save("case.json", CaseCandidate.model_validate(offline.CASE))
        j.save("fact_pack.json", FactPack.model_validate(copy.deepcopy(offline.FACT_PACK)))
        j.save("script.json", Script.model_validate(copy.deepcopy(offline.SCRIPT)))
        state.upsert_job(j.id, "short", Stage.QA, JobStatus.DONE,
                         meta={"case_no": f"CASE #{i:04d}", "quality": i})


def test_select_best_n_in_date_order(tmp_path, state):
    seed(tmp_path, state, 5)
    jobs = compilation.select_jobs(state, datetime.now(UTC), tmp_path, max_cases=3)
    assert [j.id for j in jobs] == ["2026-11-12-01", "2026-11-13-01", "2026-11-14-01"]


def test_cold_open_and_outro_are_valid_scripts():
    co = compilation.cold_open([("Hook one.", ["c1"]), ("Hook two.", ["c2"]),
                                ("Hook three.", ["c3"])], 46)
    assert len(co.lines) == 5 and "Week 46" in co.lines[0].text
    assert {ln.shot_id for ln in co.lines} <= {s.id for s in co.shots}
    out = compilation.outro()
    assert out.lines[-1].text == "Insert the next disc."


def test_reuse_mode_uses_short_script_without_llm(tmp_path, state):
    seed(tmp_path, state, 1)
    job = Job("2026-11-10-01", tmp_path)
    assert compilation.write_chapter(None, job, reuse=True).hook == offline.SCRIPT["hook"]


def test_chapter_fallback_when_expansion_fails_lint(tmp_path, state, settings):
    from pipeline.budget import Governor

    seed(tmp_path, state, 1)
    job = Job("2026-11-10-01", tmp_path)
    llm = offline.OfflineLLM(Governor(state, settings))
    # offline fixture is a 60s script: too short for a chapter -> falls back to the short
    offline.RESPONSES["compilation_script"] = offline.SCRIPT
    try:
        ch = compilation.write_chapter(llm, job, reuse=False)
    finally:
        del offline.RESPONSES["compilation_script"]
    assert ch.hook == offline.SCRIPT["hook"]
    assert llm.calls.count("compilation_script") == 2


def test_timestamp_format():
    assert compilation._fmt(0) == "00:00"
    assert compilation._fmt(75.9) == "01:15"
    assert compilation._fmt(3725) == "1:02:05"


def test_publish_slot_is_next_sunday_noon(settings):
    s = compilation.publish_slot(date(2026, 11, 12), settings)     # Thursday
    assert s.date() == date(2026, 11, 15) and s.strftime("%H:%M") == "12:00"
    assert compilation.publish_slot(date(2026, 11, 15), settings).date() == date(2026, 11, 15)


def test_description_has_chapters_sources_disclosure():
    pack = FactPack.model_validate(copy.deepcopy(offline.FACT_PACK))
    meta = {"chapters": [("00:00", "Cold open"), ("00:21", "CASE #1: A"), ("01:18", "Next")]}
    d = compilation.description(meta, [pack])
    assert d.index("00:00 Cold open") < d.index("Sources:")
    assert "example.org" in d and "AI-assisted" in d


def test_publish_dry_run_writes_plan(tmp_path, state, settings, monkeypatch):
    monkeypatch.setenv("PIPELINE_ENABLED", "false")
    seed(tmp_path, state, 3)
    wk = Job("weekly-x", tmp_path)
    meta = {"title": "T", "chapters": [("00:00", "a")],
            "jobs": ["2026-11-10-01", "2026-11-11-01", "2026-11-12-01"]}
    slot = compilation.publish_slot(date(2026, 11, 15), settings)
    plan = compilation.publish(tmp_path / "v.mp4", meta, wk, settings, slot, live=True, yt=None,
                               jobs_dir=tmp_path)
    assert plan["dry_run"] and plan["status"]["containsSyntheticMedia"] is True
    assert json.loads(wk.path("publish_plan.json").read_text())["status"]["publishAt"] == (
        "2026-11-15T17:00:00Z")
