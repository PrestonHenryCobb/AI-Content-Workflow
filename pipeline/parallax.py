"""2.5D camera moves on still images (DECISIONS D11).

Depth: Depth Anything V2 small when `transformers` is installed and the config asks for it;
otherwise a heuristic (lower in frame = nearer, bright sky/fog = farther) that works well
for the corridor/road/room compositions this channel uses. Frames are produced by backward
warping with per-pixel displacement proportional to nearness.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageFilter

F32 = NDArray[np.float32]


def heuristic_depth(img: Image.Image) -> F32:
    """0 = far, 1 = near."""
    w, h = img.size
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None] * np.ones((1, w), dtype=np.float32)
    lum = np.asarray(img.convert("L").filter(ImageFilter.GaussianBlur(radius=max(2, w // 40))),
                     dtype=np.float32) / 255.0
    near = np.clip((y - 0.45) * 1.8, 0, 1) * 0.75 + (1 - lum) * 0.25
    out: F32 = np.clip(near, 0, 1).astype(np.float32)
    return out


def model_depth(img: Image.Image) -> F32:  # pragma: no cover - heavy optional dependency
    from transformers import pipeline  # type: ignore[import-not-found]

    pipe: Any = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf")
    d = np.asarray(pipe(img)["depth"].resize(img.size), dtype=np.float32)
    d = (d - d.min()) / max(1e-6, float(d.max() - d.min()))
    out: F32 = d.astype(np.float32)
    return out


def estimate_depth(img: Image.Image, model: str = "heuristic") -> F32:
    if model != "heuristic":
        try:
            return model_depth(img)
        except Exception:  # noqa: BLE001 - fall back to heuristic depth
            pass
    return heuristic_depth(img)


def move_params(move: str, t: float) -> tuple[float, float, float]:
    """(zoom, shift_x, shift_y) at normalized time t; shifts in fraction of width/height."""
    if move in ("push_in", "creep_forward"):
        return 1.0 + 0.10 * t, 0.0, 0.0
    if move == "pull_out":
        return 1.10 - 0.10 * t, 0.0, 0.0
    if move == "dolly_left":
        return 1.04, -0.035 * t, 0.0
    if move == "dolly_right":
        return 1.04, 0.035 * t, 0.0
    return 1.04 + 0.02 * t, 0.006 * math.sin(t * 7.0), 0.004 * math.sin(t * 5.3)


class Parallax:
    """Precompute depth once per still; render any frame of a move cheaply."""

    def __init__(self, img: Image.Image, size: tuple[int, int], depth_model: str = "heuristic"):
        w, h = size
        # cover-crop to target aspect with a margin so moves never reveal edges
        margin = 1.15
        src_ar, dst_ar = img.width / img.height, w / h
        if src_ar > dst_ar:
            nh = img.height
            nw = int(nh * dst_ar)
        else:
            nw = img.width
            nh = int(nw / dst_ar)
        left, top = (img.width - nw) // 2, (img.height - nh) // 2
        base = img.convert("RGB").crop((left, top, left + nw, top + nh))
        base = base.resize((int(w * margin), int(h * margin)), Image.Resampling.BILINEAR)
        self.src = np.asarray(base)
        self.depth = estimate_depth(base, depth_model)
        self.w, self.h, self.margin = w, h, margin
        sh, sw = self.src.shape[:2]
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        self.u = (xs - w / 2) / w          # -0.5..0.5
        self.v = (ys - h / 2) / h
        self.sw, self.sh = sw, sh

    def frame(self, move: str, t: float) -> NDArray[np.uint8]:
        zoom, sx, sy = move_params(move, t)
        # sample depth at the un-displaced location (approximation; fine for small moves)
        cx = (self.u / self.margin + 0.5) * (self.sw - 1)
        cy = (self.v / self.margin + 0.5) * (self.sh - 1)
        dep = self.depth[np.clip(cy, 0, self.sh - 1).astype(int),
                         np.clip(cx, 0, self.sw - 1).astype(int)]
        z = zoom * (1 + (zoom - 1) * 1.5 * dep)          # near pixels zoom more
        px = (self.u / z - sx * (0.4 + dep)) / self.margin
        py = (self.v / z - sy * (0.4 + dep)) / self.margin
        x = np.clip((px + 0.5) * (self.sw - 1), 0, self.sw - 1).astype(int)
        y = np.clip((py + 0.5) * (self.sh - 1), 0, self.sh - 1).astype(int)
        out: NDArray[np.uint8] = self.src[y, x]
        return out
