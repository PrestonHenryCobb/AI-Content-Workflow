import copy

import numpy as np
import pytest
from PIL import Image

from pipeline import offline, prompts
from pipeline.budget import Governor
from pipeline.library import Library
from pipeline.parallax import Parallax, heuristic_depth
from pipeline.scenes import TEMPLATES, render_frame, template_for_prompt
from pipeline.schemas import CaseCandidate, FactPack, Script
from pipeline.stages import discover, script, verify
from pipeline.stages.render import _clean, caption_chunks, spans_for
from pipeline.stages.voice import LineTiming, Word, proportional_words


@pytest.fixture
def pack():
    return FactPack.model_validate(copy.deepcopy(offline.FACT_PACK))


@pytest.fixture
def sc():
    return Script.model_validate(copy.deepcopy(offline.SCRIPT))


# ----- prompts -----
def test_every_prompt_fills(settings):
    assert "Cold Save" in prompts.load("script", voice_guide="v", cta="c", feedback="",
                                       fact_pack="{}")
    with pytest.raises(KeyError):
        prompts.load("script", voice_guide="v")
    assert prompts.version("script") >= 1


# ----- discover -----
def test_dedupe_and_scoring():
    c = CaseCandidate.model_validate(offline.CASE)
    assert discover.is_duplicate(c, ["TEST CASE (fictional): The Room 12 signal"])
    assert not discover.is_duplicate(c, ["The Somerton Man"])
    risky = c.model_copy(update={"scores": c.scores.model_copy(update={"risk": 9})})
    assert discover.score(risky) < discover.score(c)


def test_discover_stores_backlog(state, settings):
    llm = offline.OfflineLLM(Governor(state, settings))
    found = discover.discover(llm, state)
    assert found and discover.next_case(state).case_id == found[0].case_id


# ----- verify gates -----
def test_active_trial_blocked(pack):
    with pytest.raises(verify.CaseBlocked, match="trial"):
        verify.sanitize(pack.model_copy(update={"active_trial": True}))


def test_too_recent_blocked(pack):
    with pytest.raises(verify.CaseBlocked, match="newer"):
        verify.sanitize(pack.model_copy(update={"year": 2024}))


def test_banned_sources_stripped(pack):
    claims = [c.model_copy(update={"citations": [
        c.citations[0].model_copy(update={"url": "https://www.reddit.com/r/x"})]})
        for c in pack.claims]
    with pytest.raises(verify.CaseBlocked, match="usable claims"):
        verify.sanitize(pack.model_copy(update={"claims": claims}))


def test_minor_and_uncharged_names_forced_off(pack):
    people = [p.model_copy(update={"role": "uncharged_person_of_interest", "name_allowed": True})
              for p in pack.people]
    out = verify.sanitize(pack.model_copy(update={"people": people}))
    assert not any(p.name_allowed for p in out.people)


# ----- script lint -----
def test_fixture_script_lints_clean(sc, pack):
    assert script.lint(sc, pack) == []


def test_lint_catches_unknown_claim_and_blocked_name(sc, pack):
    lines = list(sc.lines)
    lines[2] = lines[2].model_copy(update={"claim_ids": ["c99"],
                                           "text": "Test Clerk saw it all."})
    people = [p.model_copy(update={"name_allowed": False}) for p in pack.people]
    problems = script.lint(sc.model_copy(update={"lines": lines}),
                           pack.model_copy(update={"people": people}))
    assert any("unknown claims" in p for p in problems)
    assert any("not allowed" in p for p in problems)


def test_lint_word_count(sc, pack):
    short = sc.model_copy(update={"lines": sc.lines[:5]})
    assert any("words" in p for p in script.lint(short, pack))


# ----- voice timing -----
def test_proportional_words_cover_span():
    ws = proportional_words("one two three", 1.0, 4.0)
    assert ws[0].start == 1.0 and ws[-1].end == pytest.approx(4.0)


# ----- render helpers -----
def _timings(sc):
    out, t = [], 0.0
    for i, ln in enumerate(sc.lines):
        out.append(LineTiming(i, ln.text, t, t + 3, proportional_words(ln.text, t, t + 3)))
        t += 3.35
    return out


def test_spans_merge_consecutive_shots(sc):
    spans = spans_for(sc, _timings(sc), 40.0)
    ids = [s.shot.id for s in spans]
    assert all(a != b for a, b in zip(ids, ids[1:], strict=False))
    assert spans[0].start == 0 and spans[-1].end == 40.0


def test_caption_chunks_short_and_ordered(sc):
    chunks = caption_chunks(_timings(sc))
    assert all(1 <= len(c.words) <= 3 for c in chunks)
    assert all(a.end <= b.start + 1e-9 for a, b in zip(chunks, chunks[1:], strict=False))


def test_clean_keeps_times():
    assert _clean("2:14") == "2:14"
    assert _clean("empty.") == "EMPTY"


# ----- visuals -----
@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_templates_render(template):
    a = np.asarray(render_frame(template, "push_in", 0.5, 0, 90, 160, 1))
    assert a.shape == (160, 90, 3) and a.std() > 3


def test_template_routing():
    assert template_for_prompt("empty highway at night") == "night_road"
    assert template_for_prompt("a kitchen with a TV") == "room"
    assert template_for_prompt("motel corridor") == "hallway"


def test_parallax_moves_pixels():
    img = render_frame("hallway", "push_in", 0.2, 0, 180, 320, 2)
    p = Parallax(img, (90, 160))
    a, b = p.frame("push_in", 0.0), p.frame("push_in", 1.0)
    assert a.shape == (160, 90, 3) and not np.array_equal(a, b)
    d = heuristic_depth(img)
    assert d[-1].mean() > d[0].mean()          # bottom of frame is nearer


# ----- library -----
def test_library_find_by_mood(state, tmp_path):
    lib = Library(state, tmp_path)
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x")
    lib.add("a", clip, "hallway", "push_in", ["motel", "night"], 4.0)
    assert lib.find("hallway", ["motel", "night"], 3.0) == clip
    assert lib.find("hallway", ["forest"], 3.0) is None
    assert lib.find("room", ["motel", "night"], 3.0) is None


def test_procedural_still(tmp_path, sc):
    from pipeline.stages.art import procedural_still

    out = tmp_path / "s.png"
    procedural_still(sc.shots[0], 1, out)
    assert Image.open(out).size == (576, 1024)


def test_offline_stub_counts_calls(state, settings):
    llm = offline.OfflineLLM(Governor(state, settings))
    llm.complete("qa_policy", "x")
    assert llm.calls == ["qa_policy"]


def test_words_dataclass():
    assert Word("a", 0, 1).end == 1
