"""Stage 6: compose the short.

Everything visual happens at the PS2 internal resolution (360x640): shot frames
(procedural 3D scenes or parallax stills), ambient FX, the PS2 grade/dither pass, and
pixel-font captions. Frames are then upscaled 3x with scanlines and piped to FFmpeg, which
adds chromatic aberration and grain and muxes the loudness-normalized audio mix.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

from pipeline.fx.ambient import Ambient, stamp
from pipeline.fx.pixeltext import render_text, text_size
from pipeline.fx.ps2 import PS2Params, ps2_internal, upscale_scanlines
from pipeline.media import MediaError, duration, ffmpeg
from pipeline.parallax import Parallax
from pipeline.scenes import render_frame, template_for_prompt
from pipeline.schemas import Script, Shot
from pipeline.stages.voice import LineTiming, Word

IW, IH, FACTOR, FPS = 360, 640, 3, 30
TAIL_S = 0.8
BONE, WARN, SODIUM, SICKLY = (236, 230, 214), (216, 255, 60), (255, 178, 92), (196, 230, 150)


@dataclass
class Span:
    shot: Shot
    start: float
    end: float


@dataclass
class Chunk:
    words: list[str]
    start: float
    end: float


def spans_for(script: Script, timings: list[LineTiming], total: float) -> list[Span]:
    shots = {s.id: s for s in script.shots}
    spans: list[Span] = []
    for i, t in enumerate(timings):
        start = 0.0 if i == 0 else t.start
        end = timings[i + 1].start if i + 1 < len(timings) else total
        shot = shots[script.lines[i].shot_id]
        if spans and spans[-1].shot.id == shot.id:
            spans[-1].end = end
        else:
            spans.append(Span(shot, start, end))
    return spans


def caption_chunks(timings: list[LineTiming], max_words: int = 3) -> list[Chunk]:
    words: list[Word] = [w for t in timings for w in t.words]
    chunks: list[Chunk] = []
    cur: list[Word] = []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or re.search(r"[.,;:?!]$", w.w):
            chunks.append(Chunk([x.w for x in cur], cur[0].start, cur[-1].end))
            cur = []
    if cur:
        chunks.append(Chunk([x.w for x in cur], cur[0].start, cur[-1].end))
    for a, b in zip(chunks, chunks[1:], strict=False):   # hold until the next chunk
        a.end = min(b.start, a.end + 0.6)
    return chunks


def _clean(word: str) -> str:
    word = re.sub(r"[^A-Za-z0-9#:'\-.]", "", word).rstrip(".:").upper()
    return word


def draw_caption(img: Image.Image, chunk: Chunk, scale: int = 2, y_frac: float = 0.64) -> None:
    words = [_clean(w) for w in chunk.words if _clean(w)]
    if not words:
        return
    hi = max(range(len(words)), key=lambda i: len(words[i])) if max(map(len, words)) > 4 else -1
    space = text_size(" ", scale)[0] or 6 * scale
    widths = [text_size(w, scale)[0] for w in words]
    total = sum(widths) + space * (len(words) - 1)
    if total > img.width - 24:                       # wrap to two lines
        scale = 1 if total > (img.width - 24) * 2 else scale
    x = (img.width - total) // 2
    y = int(img.height * y_frac)
    for i, w in enumerate(words):
        t = render_text(w, scale, WARN if i == hi else BONE)
        img.paste(t, (max(4, x), y), t)
        x += widths[i] + space


def hook_card(img: Image.Image, case_no: str, location: str, year: int | str) -> None:
    lines = [(case_no, 2, WARN), (location.upper()[:28], 1, BONE), (str(year), 2, SODIUM)]
    bw = max(text_size(t, s)[0] for t, s, _ in lines) + 28
    bh = sum(text_size(t, s)[1] for t, s, _ in lines) + 30
    x0, y0 = (img.width - bw) // 2, int(img.height * 0.22)
    panel = Image.new("RGBA", (bw, bh), (8, 12, 10, 200))
    img.paste(panel, (x0, y0), panel)
    d = ImageDraw.Draw(img)
    d.rectangle([x0, y0, x0 + bw - 1, y0 + bh - 1], outline=(150, 146, 120), width=2)
    y = y0 + 10
    for text, s, col in lines:
        t = render_text(text, s, col)
        img.paste(t, ((img.width - t.width) // 2, y), t)
        y += text_size(text, s)[1] + 4


class ShotSource:
    def __init__(self, shot: Shot, stills_dir: Path, seed: int, depth_model: str,
                 size: tuple[int, int] = (IW, IH)) -> None:
        self.shot, self.seed, self.size = shot, seed, size
        self.parallax: Parallax | None = None
        self.template = shot.template if shot.template != "none" else template_for_prompt(
            shot.prompt)
        still = stills_dir / f"{shot.id}.png"
        if shot.kind == "still" and still.exists():
            with Image.open(still) as im:
                self.parallax = Parallax(im.convert("RGB"), size, depth_model)

    def frame(self, t: float, i: int) -> NDArray[np.uint8]:
        if self.parallax is not None:
            return self.parallax.frame(self.shot.move, t)
        w, h = self.size
        return np.asarray(render_frame(self.template, self.shot.move, t, i, w, h, self.seed))


def build_audio(narration: Path, total: float, out: Path) -> Path:
    """Narration + generated dark-ambient bed (no licensed music needed), -14 LUFS.

    True-peak target is -2 dBTP so AAC encoding overshoot still lands under -1.
    """
    mix = out.with_name("mix_raw.wav")
    ffmpeg(
        "-i", str(narration),
        "-f", "lavfi", "-t", f"{total:.3f}", "-i", "anoisesrc=color=brown:amplitude=0.6:seed=7",
        "-f", "lavfi", "-t", f"{total:.3f}", "-i", "sine=frequency=49:sample_rate=48000",
        "-f", "lavfi", "-t", "0.35", "-i", "anoisesrc=color=white:amplitude=0.25:seed=3",
        "-filter_complex",
        "[1]lowpass=f=260,volume=0.10[bed];[2]volume=0.05[hum];[3]highpass=f=1500[st];"
        "[0]aresample=48000,apad[v];"
        "[v][bed][hum][st]amix=inputs=4:duration=first:normalize=0,"
        f"atrim=0:{total:.3f}[m]",
        "-map", "[m]", "-ar", "48000", "-ac", "2", str(mix))
    # two-pass loudness normalization to -14 LUFS / -1.5 dBTP
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(mix), "-af",
         "loudnorm=I=-14:TP=-2.0:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if not m:
        raise MediaError("loudnorm measurement failed")
    j = json.loads(m.group(0))
    ffmpeg("-i", str(mix), "-af",
           f"loudnorm=I=-14:TP=-2.0:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}"
           f":measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}"
           f":offset={j['target_offset']}:linear=true,"
           "aresample=192000,alimiter=limit=0.79:level=false,aresample=48000",
           "-ar", "48000", str(out))
    return out


def enforce_true_peak(video: Path, ceiling: float = -1.2, max_passes: int = 4) -> float:
    """Measure the encoded file; if AAC overshoot pushed true peak above `ceiling`, re-encode
    only the audio (always from the original) with less gain until it fits.
    Returns the total gain applied (dB)."""
    from pipeline.media import loudness

    _, peak = loudness(video)
    if peak <= ceiling:
        return 0.0
    src = video.with_name(video.stem + "_src" + video.suffix)
    video.replace(src)
    gain = 0.0
    try:
        for _ in range(max_passes):
            gain += ceiling - peak - 0.3
            ffmpeg("-i", str(src), "-c:v", "copy", "-af", f"volume={gain:.2f}dB",
                   "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(video))
            _, peak = loudness(video)
            if peak <= ceiling:
                break
    finally:
        src.unlink(missing_ok=True)
    return gain


def render_short(script: Script, timings: list[LineTiming], narration: Path, stills_dir: Path,
                 out: Path, *, case_no: str, location: str, year: int,
                 style: dict[str, object], depth_model: str = "heuristic",
                 seed: int = 1) -> Path:
    """9:16 short: 360x640 internal -> 1080x1920, captions, case card on the hook."""
    return render_video(script, timings, narration, stills_dir, out, case_no=case_no,
                        location=location, year=year, style=style, depth_model=depth_model,
                        seed=seed)


def render_video(script: Script, timings: list[LineTiming], narration: Path, stills_dir: Path,
                 out: Path, *, case_no: str, location: str, year: int | str,
                 style: dict[str, object], depth_model: str = "heuristic", seed: int = 1,
                 size: tuple[int, int] = (IW, IH), fps: int = FPS, caption_y: float = 0.64,
                 card_s: float = 2.4, stamp_on: bool = True) -> Path:
    iw, ih = size
    total = duration(narration) + TAIL_S
    audio = build_audio(narration, total, out.with_name("mix.wav"))
    spans = spans_for(script, timings, total)
    chunks = caption_chunks(timings)
    params = PS2Params.from_style(style)
    pp = style.get("post_process", {})
    scan = float(pp.get("scanlines", 0.25)) if isinstance(pp, dict) else 0.25
    rng = np.random.default_rng(seed)
    amb = Ambient(iw, ih, seed)
    hook_end = min(card_s, timings[0].end) if card_s > 0 else 0.0
    n_frames = int(total * fps)
    sources = {s.shot.id: ShotSource(s.shot, stills_dir, seed + k, depth_model, size)
               for k, s in enumerate(spans)}

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{iw * FACTOR}x{ih * FACTOR}",
           "-r", str(fps), "-i", "-", "-i", str(audio),
           "-vf", "rgbashift=rh=-3:bh=3,noise=alls=6:allf=t",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    si, ci = 0, 0
    try:
        for i in range(n_frames):
            t = i / fps
            while si + 1 < len(spans) and t >= spans[si].end:
                si += 1
            span = spans[si]
            local = (t - span.start) / max(1e-3, span.end - span.start)
            since_cut = t - span.start
            if si > 0 and since_cut < 2 / fps:
                frame = amb.static()
            else:
                frame = sources[span.shot.id].frame(min(1.0, local), i)
                frame = amb.apply(frame, i, fps, glitch=since_cut < 4 / fps and si > 0)
            frame = ps2_internal(frame, params, rng, wobble_phase=i * 0.15)
            img = Image.fromarray(frame)
            if t < hook_end:
                hook_card(img, case_no, location, year)
            while ci + 1 < len(chunks) and t >= chunks[ci].end:
                ci += 1
            if chunks and chunks[ci].start <= t < chunks[ci].end:
                draw_caption(img, chunks[ci], y_frac=caption_y)
            if stamp_on:
                stamp(img, case_no, i, fps)
            big = upscale_scanlines(np.asarray(img), FACTOR, scan)
            proc.stdin.write(big.tobytes())
        proc.stdin.close()
        err = proc.stderr.read().decode() if proc.stderr else ""
        if proc.wait() != 0:
            raise MediaError(f"encode failed: {err[-2000:]}")
    finally:
        if proc.poll() is None:
            proc.kill()
    enforce_true_peak(out)
    return out
