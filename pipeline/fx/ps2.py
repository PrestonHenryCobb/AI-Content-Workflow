"""The "Lost PS2 Disc" post-process pass (GOD_PROMPT §1.3, config/style.yaml).

This pass is what guarantees the channel look whatever produced the source image
(Flux still, Blender render, parallax frame): low internal resolution, limited
palette with ordered dithering, slight geometry wobble, nearest-neighbour upscale,
scanlines, chromatic aberration and VHS noise. Deterministic for a given seed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

BAYER4 = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
                   dtype=np.float32) + 0.5) / 16.0 - 0.5

F32 = NDArray[np.float32]


@dataclass(frozen=True)
class PS2Params:
    internal_height: int = 360
    levels_per_channel: int = 6          # 6^3 = 216 max colours before grading
    vertex_wobble_px: float = 1.5
    scanlines: float = 0.25
    chromatic_aberration_px: int = 1
    vhs_noise: float = 0.15
    grade: bool = True                   # sodium-orange highlights, green-teal shadows
    crush_blacks: float = 0.06

    @classmethod
    def from_style(cls, style: dict[str, Any]) -> PS2Params:
        pp = style.get("post_process", {})
        colors = int(pp.get("palette_colors", 216))
        return cls(
            internal_height=int(pp.get("internal_height", 360)),
            levels_per_channel=max(2, round(colors ** (1 / 3)) + 2),
            vertex_wobble_px=float(pp.get("vertex_wobble_px", 1.5)),
            scanlines=float(pp.get("scanlines", 0.25)),
            chromatic_aberration_px=int(pp.get("chromatic_aberration_px", 1)),
            vhs_noise=float(pp.get("vhs_noise", 0.15)),
        )


def _to_f32(img: Image.Image) -> F32:
    return np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0


def _to_img(a: F32) -> Image.Image:
    return Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def _wobble(a: F32, px: float, rng: np.random.Generator) -> F32:
    """Affine-warp feel: rows and columns drift by a slow sine, like jittery vertices."""
    if px <= 0:
        return a
    h, w, _ = a.shape
    ph = rng.uniform(0, 2 * np.pi, 2)
    dx = np.round(px * np.sin(np.arange(h) / 23.0 + ph[0])).astype(int)
    dy = np.round(px * np.sin(np.arange(w) / 31.0 + ph[1])).astype(int)
    rows = np.clip(np.arange(h)[:, None] + dy[None, :], 0, h - 1)
    cols = np.clip(np.arange(w)[None, :] + dx[:, None], 0, w - 1)
    out: F32 = a[rows, cols]
    return out


def _grade(a: F32, crush: float) -> F32:
    lum = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    lum = lum[..., None]
    desat = a * 0.55 + lum * 0.45
    shadows = np.array([0.55, 0.85, 0.75], dtype=np.float32)    # sickly green-teal
    highlights = np.array([1.10, 0.85, 0.55], dtype=np.float32)  # sodium orange
    tint = shadows + (highlights - shadows) * np.clip(lum * 1.4, 0, 1)
    out = desat * tint
    graded: F32 = np.clip((out - crush) / (1 - crush), 0, 1).astype(np.float32)
    return graded


def _dither_quantize(a: F32, levels: int) -> F32:
    h, w, _ = a.shape
    thresh = np.tile(BAYER4, (h // 4 + 1, w // 4 + 1))[:h, :w, None]
    q = np.floor(a * (levels - 1) + 0.5 + thresh)
    out: F32 = (np.clip(q, 0, levels - 1) / (levels - 1)).astype(np.float32)
    return out


def apply_ps2(img: Image.Image, out_size: tuple[int, int] | None = None,
              params: PS2Params | None = None, seed: int = 0) -> Image.Image:
    p = params or PS2Params()
    rng = np.random.default_rng(seed)
    out_w, out_h = out_size or img.size
    ih = min(p.internal_height, out_h)
    iw = max(1, round(out_w * ih / out_h))

    small = _to_f32(img.resize((iw, ih), Image.Resampling.BOX))
    small = _wobble(small, p.vertex_wobble_px, rng)
    if p.grade:
        small = _grade(small, p.crush_blacks)
    small = _dither_quantize(small, p.levels_per_channel)

    big = _to_f32(_to_img(small).resize((out_w, out_h), Image.Resampling.NEAREST))

    if p.chromatic_aberration_px > 0:
        s = p.chromatic_aberration_px * max(1, out_h // ih)
        big[..., 0] = np.roll(big[..., 0], -s, axis=1)
        big[..., 2] = np.roll(big[..., 2], s, axis=1)

    if p.scanlines > 0:
        period = max(2, out_h // ih)
        mask = np.ones(out_h, dtype=np.float32)
        mask[np.arange(out_h) % period >= period // 2] = 1 - p.scanlines
        big *= mask[:, None, None]

    if p.vhs_noise > 0:
        big += rng.normal(0, p.vhs_noise * 0.12, (out_h, out_w, 1)).astype(np.float32)
        for _ in range(rng.integers(1, 4)):          # tracking lines
            y = int(rng.integers(0, out_h))
            hgt = int(rng.integers(1, max(2, out_h // 120)))
            big[y:y + hgt] = big[y:y + hgt] * 0.6 + 0.25

    return _to_img(big)


def ps2_internal(frame: NDArray[np.uint8], p: PS2Params, rng: np.random.Generator,
                 wobble_phase: float = 0.0) -> NDArray[np.uint8]:
    """Per-frame PS2 pass at internal resolution (video path): wobble, grade, dither."""
    a = frame.astype(np.float32) / 255.0
    if p.vertex_wobble_px > 0:
        h, w, _ = a.shape
        dx = np.round(p.vertex_wobble_px * np.sin(np.arange(h) / 23.0 + wobble_phase)).astype(int)
        cols = np.clip(np.arange(w)[None, :] + dx[:, None], 0, w - 1)
        a = a[np.arange(h)[:, None], cols]
    if p.grade:
        a = _grade(a, p.crush_blacks)
    a = _dither_quantize(a, p.levels_per_channel)
    out: NDArray[np.uint8] = (a * 255 + 0.5).astype(np.uint8)
    return out


def upscale_scanlines(frame: NDArray[np.uint8], factor: int,
                      strength: float) -> NDArray[np.uint8]:
    """Nearest-neighbour integer upscale with darkened bottom row of every source pixel."""
    big = np.repeat(np.repeat(frame, factor, axis=0), factor, axis=1)
    if strength > 0 and factor > 1:
        big = big.copy()
        big[factor - 1::factor] = (big[factor - 1::factor] * (1 - strength)).astype(np.uint8)
    out: NDArray[np.uint8] = big
    return out
