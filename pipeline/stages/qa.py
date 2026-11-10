"""Stage 7: the QA gate that replaces human review (GOD_PROMPT §2 Stage 7).

Text gates (fact + policy) run *before* voice/art/render so a bad script never costs
render time. Technical + visual gates run on the finished file.
"""

from __future__ import annotations

from pathlib import Path

from pipeline import prompts
from pipeline.llm import Completer
from pipeline.media import duration, ffmpeg, loudness, probe, silences
from pipeline.schemas import Check, FactPack, FactVerdict, PolicyVerdict, Script, VisualVerdict

MIN_QUALITY = 7.0


def script_text(script: Script) -> str:
    lines = "\n".join(f"{i + 1}. {ln.text}  [claims: {', '.join(ln.claim_ids) or '-'}]"
                      for i, ln in enumerate(script.lines))
    return f"{lines}\n\nTitles:\n" + "\n".join(f"- {t}" for t in script.titles)


def fact_gate(llm: Completer, pack: FactPack, script: Script, *, job_id: str | None = None,
              urgent: bool = False) -> tuple[Check, float, str]:
    res = llm.complete("qa_fact", prompts.load(
        "qa_fact", fact_pack=pack.model_dump_json(indent=1), script=script_text(script)),
        json_schema=FactVerdict.json_schema(), job_id=job_id, urgent=urgent)
    v = FactVerdict.model_validate(res.data)
    bad = [s for s in v.sentences if not s.supported]
    quality = (v.hook_strength + v.pacing + v.clarity) / 3
    detail = "; ".join(f"{s.sentence[:60]}… → {s.problem}" for s in bad) or "all supported"
    ok = not bad and quality >= MIN_QUALITY
    fix = v.fix_instructions or detail
    if quality < MIN_QUALITY:
        fix += f"\nQuality {quality:.1f}/10 is below {MIN_QUALITY}: strengthen the hook and pacing."
    return Check(name="fact", passed=ok, detail=f"{detail} (quality {quality:.1f})"), quality, fix


def policy_gate(llm: Completer, pack: FactPack, script: Script, *, job_id: str | None = None,
                urgent: bool = False) -> tuple[Check, str]:
    allowed = ", ".join(p.name for p in pack.people if p.name_allowed) or "none"
    blocked = ", ".join(p.name for p in pack.people if not p.name_allowed) or "none"
    res = llm.complete("qa_policy", prompts.load(
        "qa_policy", allowed_names=allowed, blocked_names=blocked, script=script_text(script)),
        json_schema=PolicyVerdict.json_schema(), job_id=job_id, urgent=urgent)
    v = PolicyVerdict.model_validate(res.data)
    return (Check(name="policy", passed=v.passed, detail="; ".join(v.violations) or "ok"),
            v.fix_instructions or "; ".join(v.violations))


def technical_checks(video: Path, narration: Path | None, *, size: tuple[int, int] = (1080, 1920),
                     fps: str = "30/1", min_s: float = 40, max_s: float = 80) -> list[Check]:
    info = probe(video)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    dur = duration(video)
    checks = [
        Check(name="duration", passed=min_s <= dur <= max_s,
              detail=f"{dur:.1f}s ({min_s:.0f}–{max_s:.0f})"),
        Check(name="resolution", passed=bool(v and (v["width"], v["height"]) == size),
              detail=f"{v and v['width']}x{v and v['height']}"),
        Check(name="fps", passed=bool(v and v.get("r_frame_rate") == fps),
              detail=str(v and v.get("r_frame_rate"))),
        Check(name="audio_stream", passed=a is not None, detail=str(a and a["codec_name"])),
    ]
    lufs, peak = loudness(video)
    checks.append(Check(name="loudness", passed=-16.5 <= lufs <= -12.5 and peak <= -1.0,
                        detail=f"{lufs:.1f} LUFS, peak {peak:.1f} dBFS"))
    if narration is not None:
        gaps = [g for g in silences(narration, 1.5) if g[0] > 0.1]   # ignore leading silence
        checks.append(Check(name="silent_gaps", passed=not gaps,
                            detail=f"{len(gaps)} gaps > 1.5s"))
    return checks


def sample_frames(video: Path, out_dir: Path, n: int = 6) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    dur = duration(video)
    paths = []
    for k in range(n):
        t = dur * (k + 0.5) / n
        p = out_dir / f"frame_{k}.png"
        ffmpeg("-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=540:960",
               str(p))
        paths.append(p)
    return paths


def visual_gate(llm: Completer, frames: list[Path], *, job_id: str | None = None,
                urgent: bool = False) -> Check:
    listing = "\n".join(str(p.resolve()) for p in frames)
    res = llm.complete("qa_visual", prompts.load("qa_visual", frames=listing),
                       json_schema=VisualVerdict.json_schema(), job_id=job_id, urgent=urgent,
                       add_dirs=[str(frames[0].parent.resolve())], extra_tools=["Read"])
    v = VisualVerdict.model_validate(res.data)
    return Check(name="visual", passed=v.passed, detail="; ".join(v.problems) or "ok")
