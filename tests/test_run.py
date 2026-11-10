import copy

from pipeline import offline
from pipeline.budget import Governor
from pipeline.run import script_with_gates
from pipeline.schemas import FactPack

FAIL_FACT = {"sentences": [{"sentence": "x", "supported": False, "claim_ids": [],
                            "problem": "needs attribution"}],
             "hook_strength": 8, "pacing": 8, "clarity": 8, "fix_instructions": "attribute it"}


class Scripted(offline.OfflineLLM):
    """Offline LLM whose qa_fact answers follow a queue; records prompts."""

    def __init__(self, gov, fact_answers):
        super().__init__(gov)
        self.fact_answers = list(fact_answers)
        self.prompts = []

    def complete(self, stage_name, prompt, **kw):
        self.prompts.append((stage_name, prompt))
        if stage_name == "qa_fact" and self.fact_answers:
            res = super().complete(stage_name, prompt, **kw)
            return res.__class__(**{**res.__dict__, "data": self.fact_answers.pop(0)})
        return super().complete(stage_name, prompt, **kw)


def _run(state, settings, answers, max_rewrites=3):
    llm = Scripted(Governor(state, settings), answers)
    pack = FactPack.model_validate(copy.deepcopy(offline.FACT_PACK))
    out = script_with_gates(llm, pack, job_id="j", urgent=True, hook_style="countdown",
                            cta="", notes=[], max_rewrites=max_rewrites)
    return llm, out


def test_policy_skipped_until_facts_pass_and_previous_draft_sent(state, settings):
    llm, out = _run(state, settings, [FAIL_FACT, offline.RESPONSES["qa_fact"]])
    assert not isinstance(out, str)
    stages = [s for s, _ in llm.prompts]
    assert stages == ["script", "qa_fact", "script", "qa_fact", "qa_policy"]
    second_script = [p for s, p in llm.prompts if s == "script"][1]
    assert "attribute it" in second_script and "Revise this previous draft" in second_script


def test_gives_up_with_feedback(state, settings):
    llm, out = _run(state, settings, [FAIL_FACT] * 2, max_rewrites=1)
    assert isinstance(out, str) and "attribute it" in out
    assert "qa_policy" not in [s for s, _ in llm.prompts]
