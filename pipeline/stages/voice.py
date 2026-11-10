"""Stage 4: narration. Kokoro TTS (local, free) per line, eerie post-FX, word timings.

Providers:
- kokoro: real voice (CI). Word timings from faster-whisper; proportional fallback.
- silent: offline/test mode. Silence with realistic durations and proportional timings.
"""

from __future__ import annotations

import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from pipeline.media import duration, ffmpeg
from pipeline.schemas import Script

SR = 24_000
GAP_S = 0.35
WORDS_PER_S = 2.6


@dataclass
class Word:
    w: str
    start: float
    end: float


@dataclass
class LineTiming:
    index: int
    text: str
    start: float
    end: float
    words: list[Word]


def proportional_words(text: str, start: float, end: float) -> list[Word]:
    words = text.split()
    weights = np.array([len(w) + 2 for w in words], dtype=float)
    edges = start + np.concatenate([[0], np.cumsum(weights)]) / weights.sum() * (end - start)
    return [Word(w, float(edges[i]), float(edges[i + 1])) for i, w in enumerate(words)]


def _write_wav(path: Path, audio: np.ndarray[Any, Any]) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(pcm.tobytes())


class SilentTTS:
    def synth(self, text: str, out: Path) -> None:
        secs = max(1.0, len(text.split()) / WORDS_PER_S)
        _write_wav(out, np.zeros(int(secs * SR), dtype=np.float32))

    def align(self, wav: Path, text: str) -> list[Word]:
        return proportional_words(text, 0.0, duration(wav))


class KokoroTTS:  # pragma: no cover - needs model weights, exercised in CI slice
    def __init__(self, voice: str, speed: float) -> None:
        from kokoro import KPipeline  # type: ignore[import-not-found]

        self.pipe = KPipeline(lang_code="a")
        self.voice, self.speed = voice, speed
        self._whisper: Any = None

    def synth(self, text: str, out: Path) -> None:
        chunks = [np.asarray(audio, dtype=np.float32)
                  for _, _, audio in self.pipe(text, voice=self.voice, speed=self.speed)]
        _write_wav(out, np.concatenate(chunks))

    def align(self, wav: Path, text: str) -> list[Word]:
        try:
            if self._whisper is None:
                from faster_whisper import WhisperModel  # type: ignore[import-not-found]

                self._whisper = WhisperModel("small", device="cpu", compute_type="int8")
            segs, _ = self._whisper.transcribe(str(wav), word_timestamps=True, language="en")
            words = [Word(w.word.strip(), float(w.start), float(w.end))
                     for s in segs for w in (s.words or [])]
            if len(words) >= max(1, len(text.split()) // 2):
                return words
        except Exception:  # noqa: BLE001 - alignment is best-effort; fall back below
            pass
        return proportional_words(text, 0.0, duration(wav))


def make_tts(voice_cfg: dict[str, Any], offline: bool) -> SilentTTS | KokoroTTS:
    if offline or voice_cfg.get("provider") != "kokoro":
        return SilentTTS()
    k = voice_cfg.get("kokoro", {})
    return KokoroTTS(str(k.get("voice", "am_onyx")), float(k.get("speed", 0.92)))


def _semitone_chain(semitones: float) -> str:
    ratio = 2 ** (semitones / 12)
    return f"asetrate={SR}*{ratio:.5f},aresample={SR},atempo={1 / ratio:.5f}"


def narrate(script: Script, out_dir: Path, voice_cfg: dict[str, Any],
            offline: bool = False) -> tuple[Path, list[LineTiming]]:
    """Synthesize each line, apply post-FX, concatenate. Returns (wav, timings)."""
    tts = make_tts(voice_cfg, offline)
    fx = voice_cfg.get("post_fx", {})
    parts = out_dir / "voice_parts"
    parts.mkdir(parents=True, exist_ok=True)
    pitch = _semitone_chain(float(fx.get("pitch_semitones", -1.5)))
    reverb = f"aecho=0.8:0.6:45|80:{float(fx.get('reverb_room', 0.25)):.2f}|0.12"
    timings: list[LineTiming] = []
    files: list[Path] = []
    t = 0.0
    for i, line in enumerate(script.lines):
        raw, done = parts / f"l{i:02d}_raw.wav", parts / f"l{i:02d}.wav"
        tts.synth(line.text, raw)
        chain = [pitch, reverb]
        if i == 0:  # radio EQ on the hook
            chain.insert(0, f"highpass=f=300,lowpass=f={int(fx.get('lowpass_hz_hook', 3400))}")
        ffmpeg("-i", str(raw), "-af", ",".join(chain), "-ar", str(SR), "-ac", "1", str(done))
        d = duration(done)
        words = [Word(w.w, w.start + t, w.end + t) for w in tts.align(done, line.text)]
        timings.append(LineTiming(i, line.text, t, t + d, words))
        files.append(done)
        t += d + GAP_S
    gap = parts / "gap.wav"
    _write_wav(gap, np.zeros(int(GAP_S * SR), dtype=np.float32))
    concat = parts / "concat.txt"
    concat.write_text("".join(f"file '{f.resolve()}'\nfile '{gap.resolve()}'\n" for f in files))
    out = out_dir / "narration.wav"
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(concat), "-ar", str(SR), "-ac", "1", str(out))
    return out, timings


def timings_to_json(timings: list[LineTiming]) -> list[dict[str, Any]]:
    return [asdict(t) for t in timings]


def timings_from_json(data: list[dict[str, Any]]) -> list[LineTiming]:
    return [LineTiming(d["index"], d["text"], d["start"], d["end"],
                       [Word(**w) for w in d["words"]]) for d in data]
