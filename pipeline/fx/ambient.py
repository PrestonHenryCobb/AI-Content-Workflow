"""Ambient per-frame FX layer at internal resolution (DECISIONS D11):
light flicker, drifting fog, dust, row glitches, static cuts, REC/case stamp.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from pipeline.fx.pixeltext import draw_text

U8 = NDArray[np.uint8]


class Ambient:
    def __init__(self, w: int, h: int, seed: int = 0) -> None:
        self.w, self.h = w, h
        self.rng = np.random.default_rng(seed)
        small = self.rng.random((h // 16 + 2, (w * 2) // 16 + 2)).astype(np.float32)
        fog = Image.fromarray((small * 255).astype(np.uint8), "L").resize(
            (w * 2, h), Image.Resampling.BICUBIC)
        self.fog = np.asarray(fog, dtype=np.float32) / 255.0
        self.dust = self.rng.random((60, 3)).astype(np.float32)

    def apply(self, frame: U8, i: int, fps: int, glitch: bool = False) -> U8:
        a = frame.astype(np.float32)
        # flicker: rare dips
        if self.rng.random() < 0.03:
            a *= 0.7
        # fog drift: scroll a soft noise layer left
        off = (i * 1) % self.w
        f = self.fog[:, off:off + self.w][..., None]
        a = a * (1 - 0.18 * f) + 60 * 0.18 * f
        # dust motes
        for k in range(len(self.dust)):
            x = int((self.dust[k, 0] * self.w + i * (0.3 + self.dust[k, 2])) % self.w)
            y = int((self.dust[k, 1] * self.h + i * 0.2) % self.h)
            a[y:y + 1, x:x + 1] += 50
        if glitch:
            for _ in range(int(self.rng.integers(2, 6))):
                y0 = int(self.rng.integers(0, self.h - 8))
                hh = int(self.rng.integers(2, 10))
                a[y0:y0 + hh] = np.roll(a[y0:y0 + hh], int(self.rng.integers(-20, 20)), axis=1)
        out: U8 = np.clip(a, 0, 255).astype(np.uint8)
        return out

    def static(self) -> U8:
        n = self.rng.integers(0, 255, (self.h // 2, self.w // 2), dtype=np.uint8)
        img = Image.fromarray(n, "L").resize((self.w, self.h), Image.Resampling.NEAREST)
        out: U8 = np.stack([np.asarray(img)] * 3, axis=-1)
        return out


def stamp(img: Image.Image, case_no: str, i: int, fps: int) -> None:
    """Blinking REC dot + case number (never a fake date: we don't imply real footage)."""
    if (i // (fps // 2)) % 2 == 0:
        draw_text(img, (img.width - 8, 10), "REC", 1, (230, 60, 50), anchor="rb")
    draw_text(img, (8, 6), case_no, 1, (216, 255, 60))
