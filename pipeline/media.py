"""Thin FFmpeg/ffprobe helpers."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


class MediaError(RuntimeError):
    pass


def ffmpeg(*args: str, quiet: bool = True) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner"] + (["-loglevel", "error"] if quiet else []) + list(args)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"ffmpeg failed: {' '.join(cmd)}\n{proc.stderr[-2000:]}")


def probe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
         str(path)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"ffprobe failed on {path}: {proc.stderr}")
    data: dict[str, Any] = json.loads(proc.stdout)
    return data


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def loudness(path: Path) -> tuple[float, float]:
    """Integrated LUFS and true peak (dBTP) via the ebur128 filter."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-filter_complex",
         "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    tail = proc.stderr[proc.stderr.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", tail)
    p = re.search(r"Peak:\s+(-?[\d.]+) dBFS", tail)
    if not i or not p:
        raise MediaError(f"could not measure loudness of {path}")
    return float(i.group(1)), float(p.group(1))


def silences(path: Path, min_s: float = 1.5, noise_db: float = -45) -> list[tuple[float, float]]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
         f"silencedetect=noise={noise_db}dB:d={min_s}", "-f", "null", "-"],
        capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", proc.stderr)]
    return list(zip(starts, ends, strict=False))
