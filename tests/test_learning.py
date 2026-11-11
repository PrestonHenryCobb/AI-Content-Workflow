from datetime import UTC, datetime, timedelta

import numpy as np

from pipeline import analytics, offline, strategy
from pipeline.budget import Governor
from pipeline.schemas import CaseMix
from pipeline.stages import publish
from pipeline.youtube import Credentials, HttpResponse, YouTube

NOW = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)


def seed_stats(state, rows):
    strategy.init(state)
    publish.init(state)
    for i, (hook, pct) in enumerate(rows):
        job = f"j{i}"
        strategy.record_arm(state, job, "hook_style", hook)
        state.conn.execute(
            "INSERT INTO video_stats (video_id, job_id, fetched_at, views, avg_view_pct, "
            "avg_view_s, likes, comments, subs) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"v{i}", job, NOW.isoformat(), 100, pct, 30, 1, 0, 0))
    state.conn.commit()
    analytics.label(state)


def test_labels_against_median(state):
    seed_stats(state, [("a", 90), ("a", 80), ("b", 20), ("b", 30)])
    assert strategy.arm_stats(state, "hook_style") == {"a": (2, 0), "b": (0, 2)}


def test_thompson_prefers_winner(state):
    seed_stats(state, [("a", 90)] * 10 + [("b", 10)] * 10)
    rng = np.random.default_rng(0)
    picks = [strategy.choose(state, "hook_style", ["a", "b"], rng) for _ in range(200)]
    assert picks.count("a") > 180


def test_unknown_arm_still_explored(state):
    seed_stats(state, [("a", 50)] * 4)
    rng = np.random.default_rng(1)
    picks = {strategy.choose(state, "hook_style", ["a", "new"], rng) for _ in range(100)}
    assert "new" in picks


def test_clamp_mix_moves_gradually():
    old = {"unsolved": 0.6, "solved_with_twist": 0.25, "strange_but_true": 0.15}
    new = analytics.clamp_mix(old, CaseMix(unsolved=0.1, solved_with_twist=0.75,
                                           strange_but_true=0.15))
    assert abs(sum(new.values()) - 1) < 0.01
    assert new["unsolved"] >= 0.40           # moved at most ~0.15 (+ renormalization)


def test_plan_week_needs_data_then_stores(state, settings):
    llm = offline.OfflineLLM(Governor(state, settings))
    assert analytics.plan_week(llm, state, settings) is None
    seed_stats(state, [("a", 50 + i) for i in range(8)])
    plan = analytics.plan_week(llm, state, settings)
    assert plan is not None
    assert strategy.get(state, "writer_notes") == ["Keep the second line under ten words."]
    mix = strategy.get(state, "case_mix")
    assert abs(sum(mix.values()) - 1) < 0.01


def test_fetch_reads_rows_and_skips_too_new(state, settings):
    publish.init(state)
    old = (NOW - timedelta(days=3)).isoformat()
    new = (NOW - timedelta(hours=5)).isoformat()
    state.conn.executemany(
        "INSERT INTO publications VALUES (?,?,?,?,?,?,?,?)",
        [("j1", "youtube", old, "scheduled", "vidA", "t", None, old),
         ("j2", "youtube", new, "scheduled", "vidB", "t", None, new)])
    state.conn.commit()
    seen = []

    def transport(method, url, headers, body):
        if "oauth2" in url:
            return HttpResponse(200, {}, b'{"access_token": "t"}')
        seen.append(url)
        return HttpResponse(200, {}, b'{"rows": [["vidA", 500, 71.5, 40, 9, 2, 3]]}')

    yt = YouTube(Credentials("i", "s", "r"), Governor(state, settings, now=NOW), transport)
    assert analytics.fetch(yt, state, NOW) == 1
    assert "vidB" not in seen[0] and "vidA" in seen[0]
    row = state.conn.execute("SELECT views, avg_view_pct, job_id FROM video_stats").fetchone()
    assert tuple(row) == (500, 71.5, "j1")


def test_script_prompt_gets_hook_and_notes(state, settings):
    import copy

    from pipeline.schemas import FactPack
    from pipeline.stages import script

    captured = {}

    class Spy(offline.OfflineLLM):
        def complete(self, stage_name, prompt, **kw):
            captured["prompt"] = prompt
            return super().complete(stage_name, prompt, **kw)

    pack = FactPack.model_validate(copy.deepcopy(offline.FACT_PACK))
    script.write_script(Spy(Governor(state, settings)), pack, hook_style="countdown",
                        cta="See you Sunday.", style_notes=["Shorter second line."])
    p = captured["prompt"]
    assert strategy.HOOK_STYLES["countdown"] in p
    assert "Shorter second line." in p and "never override the hard rules" in p


def test_prune_deletes_old_api_data_but_keeps_learning(state):
    from datetime import timedelta

    seed_stats(state, [("a", 90), ("a", 80), ("b", 20), ("b", 30)])
    before = strategy.arm_stats(state, "hook_style")
    later = NOW + timedelta(days=31)
    assert analytics.prune(state, later) == 4
    assert state.conn.execute("SELECT COUNT(*) FROM video_stats").fetchone()[0] == 0
    assert strategy.arm_stats(state, "hook_style") == before
