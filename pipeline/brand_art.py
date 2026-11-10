"""Procedural channel art in the Lost PS2 Disc style. $0: no image API needed.

Scenes are drawn as flat-shaded low-poly geometry with distance fog at a low internal
resolution, then sent through the PS2 post-process pass. Everything is original:
no game assets, no real people. Human figures are faceless silhouettes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from pipeline.fx.pixeltext import draw_text, text_size
from pipeline.fx.ps2 import PS2Params, apply_ps2

RGB = tuple[int, int, int]
FOG: RGB = (38, 48, 42)            # murky green-black
SODIUM: RGB = (255, 178, 92)
SICKLY: RGB = (196, 230, 150)
BONE: RGB = (236, 230, 214)
WARN: RGB = (216, 255, 60)


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    t = min(1.0, max(0.0, t))
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t),
            round(a[2] + (b[2] - a[2]) * t))


@dataclass
class Cam:
    w: int
    h: int
    f: float
    cam_y: float = 1.45
    horizon: float = 0.5

    def p(self, x: float, y: float, z: float) -> tuple[float, float]:
        return (self.w / 2 + self.f * x / z,
                self.h * self.horizon - self.f * (y - self.cam_y) / z)


def _fog(z: float, near: float = 1.0, far: float = 16.0) -> float:
    return float(min(1.0, max(0.0, (z - near) / (far - near))) ** 0.8)


def hallway(w: int, h: int, seed: int = 7, figure: bool = True) -> Image.Image:
    """One-point-perspective motel/school corridor: doors, buzzing lights, one dead."""
    rng = np.random.default_rng(seed)
    cam = Cam(w, h, f=h * 0.9)
    img = Image.new("RGB", (w, h), FOG)
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    d, g = ImageDraw.Draw(img), ImageDraw.Draw(glow)
    hw, ceil, seg = 1.15, 2.6, 1.2
    wall, floor_a, floor_b, ceil_c = (128, 140, 112), (104, 92, 74), (72, 66, 58), (88, 90, 80)
    door_c, frame_c = (58, 40, 30), (120, 116, 96)
    zs = [1.0 + i * seg for i in range(14)]
    dead_light = int(rng.integers(2, 6))

    for i in reversed(range(len(zs) - 1)):
        z0, z1 = zs[i], zs[i + 1]
        fz = _fog((z0 + z1) / 2)
        lit = 0.25 if i % 3 == dead_light % 3 and i // 3 == 1 else 1.0

        def shade(c: RGB, k: float = 1.0, lit: float = lit, fz: float = fz) -> RGB:
            return _mix(_mix((0, 0, 0), c, lit * k), FOG, fz)
        # floor tiles (2 across, checker)
        for t in range(2):
            x0, x1 = -hw + t * hw, -hw + (t + 1) * hw
            col = floor_a if (i + t) % 2 == 0 else floor_b
            d.polygon([cam.p(x0, 0, z0), cam.p(x1, 0, z0), cam.p(x1, 0, z1), cam.p(x0, 0, z1)],
                      fill=shade(col))
        d.polygon([cam.p(-hw, ceil, z0), cam.p(hw, ceil, z0), cam.p(hw, ceil, z1),
                   cam.p(-hw, ceil, z1)], fill=shade(ceil_c, 0.8))
        for sx, k in ((-hw, 0.85), (hw, 0.7)):
            d.polygon([cam.p(sx, 0, z0), cam.p(sx, ceil, z0), cam.p(sx, ceil, z1),
                       cam.p(sx, 0, z1)], fill=shade(wall, k))
            d.line([cam.p(sx, 0.9, z0), cam.p(sx, 0.9, z1)], fill=shade((60, 70, 56)), width=1)
            if i % 2 == 1:      # door with frame
                a, b = z0 + 0.25, z1 - 0.25
                d.polygon([cam.p(sx, 0, a), cam.p(sx, 2.1, a), cam.p(sx, 2.1, b),
                           cam.p(sx, 0, b)], fill=shade(frame_c, k))
                a2, b2 = a + 0.07, b - 0.07
                d.polygon([cam.p(sx, 0, a2), cam.p(sx, 2.0, a2), cam.p(sx, 2.0, b2),
                           cam.p(sx, 0, b2)], fill=shade(door_c, k))
        if i % 3 == 0:          # ceiling light
            on = i // 3 != 1
            a, b = z0 + 0.3, z0 + 0.9
            quad = [cam.p(-0.35, ceil - 0.01, a), cam.p(0.35, ceil - 0.01, a),
                    cam.p(0.35, ceil - 0.01, b), cam.p(-0.35, ceil - 0.01, b)]
            col = _mix(SICKLY if on else (40, 44, 40), FOG, fz * 0.7)
            d.polygon(quad, fill=col)
            if on:
                g.polygon(quad, fill=_mix(SICKLY, (0, 0, 0), fz * 0.6))
                pool = [cam.p(-1.1, 0.001, a - 0.4), cam.p(1.1, 0.001, a - 0.4),
                        cam.p(1.1, 0.001, b + 0.6), cam.p(-1.1, 0.001, b + 0.6)]
                g.polygon(pool, fill=_mix((110, 120, 84), (0, 0, 0), fz * 0.6))

    if figure:  # faceless silhouette standing far down the hall
        z, col = 9.6, _mix((6, 6, 6), FOG, _fog(9.6) * 0.25)
        body = [cam.p(-0.22, 0, z), cam.p(0.22, 0, z), cam.p(0.26, 1.35, z), cam.p(0.18, 1.5, z),
                cam.p(-0.18, 1.5, z), cam.p(-0.26, 1.35, z)]
        d.polygon(body, fill=col)
        hx, hy = cam.p(0, 1.68, z)
        r = cam.f * 0.13 / z
        d.regular_polygon((hx, hy, r), n_sides=6, fill=col)

    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(2, h // 40)))
    out = np.clip(np.asarray(img, dtype=np.int16) + np.asarray(glow, dtype=np.int16), 0, 255)
    return _vignette(Image.fromarray(out.astype(np.uint8)), 0.45)


def _vignette(img: Image.Image, strength: float) -> Image.Image:
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    mask = 1 - strength * np.clip(r - 0.35, 0, 1) ** 1.5
    a = np.asarray(img, dtype=np.float32) * mask[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def crt_tv(size: int, seed: int = 3, background: bool = True) -> Image.Image:
    """Low-poly CRT TV glowing in a dark, foggy room. Reads at 48 px."""
    rng = np.random.default_rng(seed)
    s = size
    img = Image.new("RGBA", (s, s), (*FOG, 255) if background else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if background:
        d.polygon([(0, s * 0.72), (s, s * 0.72), (s, s), (0, s)], fill=(30, 34, 30, 255))
    # body: front, top, side (flat shaded)
    fx0, fy0, fx1, fy1 = s * 0.20, s * 0.32, s * 0.72, s * 0.78
    dx, dy = s * 0.10, s * 0.07
    d.polygon([(fx0, fy0), (fx0 + dx, fy0 - dy), (fx1 + dx, fy0 - dy), (fx1, fy0)],
              fill=(84, 82, 70, 255))
    d.polygon([(fx1, fy0), (fx1 + dx, fy0 - dy), (fx1 + dx, fy1 - dy), (fx1, fy1)],
              fill=(44, 44, 38, 255))
    d.rectangle([fx0, fy0, fx1, fy1], fill=(64, 62, 54, 255))
    # antenna
    ax, ay = (fx0 + fx1) / 2 + dx / 2, fy0 - dy
    d.line([(ax, ay), (ax - s * 0.11, s * 0.13)], fill=(110, 108, 96, 255), width=max(1, s // 90))
    d.line([(ax, ay), (ax + s * 0.10, s * 0.14)], fill=(110, 108, 96, 255), width=max(1, s // 90))
    # screen with static
    sx0, sy0, sx1, sy1 = fx0 + s * 0.05, fy0 + s * 0.05, fx1 - s * 0.12, fy1 - s * 0.06
    sw, sh = int(sx1 - sx0), int(sy1 - sy0)
    noise = rng.integers(120, 255, (max(1, sh // 6), max(1, sw // 6)), dtype=np.uint8)
    static = Image.fromarray(noise, "L").resize((sw, sh), Image.Resampling.NEAREST)
    tint = Image.merge("RGB", (static.point(lambda v: int(v * 0.80)), static,
                               static.point(lambda v: int(v * 0.72))))
    img.paste(tint, (int(sx0), int(sy0)))
    d.rectangle([sx0, sy0 + sh * 0.45, sx1, sy0 + sh * 0.55], fill=(*BONE, 255))
    # knobs
    for k in range(2):
        cx, cy = fx1 - s * 0.06, fy0 + s * (0.14 + k * 0.12)
        d.regular_polygon((cx, cy, s * 0.025), n_sides=6, fill=(30, 30, 26, 255))
    # glow
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rectangle([sx0 - s * 0.06, sy0 - s * 0.06, sx1 + s * 0.06,
                                    sy1 + s * 0.06], fill=(*SICKLY, 120))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=s // 12))
    return Image.alpha_composite(glow, img) if not background else Image.alpha_composite(
        img, glow)


def profile_picture(size: int = 800, seed: int = 3) -> Image.Image:
    base = crt_tv(size, seed).convert("RGB")
    return apply_ps2(base, (size, size), PS2Params(internal_height=160, vhs_noise=0.06), seed)


def watermark(size: int = 150, seed: int = 3) -> Image.Image:
    """Transparent TV icon for YouTube's branding watermark slot."""
    small = crt_tv(64, seed, background=False)
    return small.resize((size, size), Image.Resampling.NEAREST)


def _save_slot_box(img: Image.Image, cx: int, cy: int, name: str, tagline: str,
                   scale: int) -> None:
    """Original 'save slot' UI motif: a framed card with slot label, name and tagline."""
    nw, nh = text_size(name.upper(), scale)
    tw, th = text_size(tagline, max(2, scale // 3))
    lw, lh = text_size("SLOT 01  -  CASE ARCHIVE", max(2, scale // 3))
    bw = max(nw, tw, lw) + scale * 12
    bh = nh + th + lh + scale * 10
    x0, y0 = cx - bw // 2, cy - bh // 2
    panel = Image.new("RGBA", (bw, bh), (8, 12, 10, 190))
    img.paste(panel, (x0, y0), panel)
    d = ImageDraw.Draw(img)
    for o, col in ((0, (150, 146, 120)), (scale, (70, 74, 60))):
        d.rectangle([x0 + o, y0 + o, x0 + bw - o, y0 + bh - o], outline=col,
                    width=max(2, scale // 2))
    draw_text(img, (x0 + scale * 3, y0 + scale * 2), "SLOT 01  -  CASE ARCHIVE",
              max(2, scale // 3), SICKLY)
    draw_text(img, (cx, y0 + scale * 4 + lh + nh // 2), name.upper(), scale, BONE, anchor="mm")
    draw_text(img, (cx, y0 + bh - scale * 2 - th // 2), tagline, max(2, scale // 3), SODIUM,
              anchor="mm")


def banner(name: str, tagline: str, seed: int = 7) -> Image.Image:
    """2560x1440 YouTube banner; text kept inside the 1546x423 all-device safe area."""
    w, h = 2560, 1440
    bg = apply_ps2(hallway(640, 360, seed), (w, h),
                   PS2Params(internal_height=360, crush_blacks=0.02), seed)
    _save_slot_box(bg, w // 2, h // 2, name, tagline, scale=12)
    draw_text(bg, (w // 2 + 773 - 20, h // 2 + 211 - 10), "REC", 4, (230, 60, 50), anchor="rb")
    return bg


def end_screen(name: str, seed: int = 11) -> Image.Image:
    """1920x1080 end-screen background; leave the right half clear for YouTube elements."""
    w, h = 1920, 1080
    bg = apply_ps2(hallway(640, 360, seed, figure=True), (w, h), PS2Params(), seed)
    draw_text(bg, (120, 380), "END OF FILE", 10, BONE)
    draw_text(bg, (124, 520), "NEXT CASE LOADING...", 5, SODIUM)
    draw_text(bg, (124, 600), name.upper(), 4, SICKLY)
    return bg


def thumbnail_template(title: str, case_no: str, seed: int = 5) -> Image.Image:
    """1280x720 compilation thumbnail: one figure, 3-4 big words, high contrast."""
    w, h = 1280, 720
    bg = apply_ps2(hallway(426, 240, seed), (w, h), PS2Params(internal_height=240), seed)
    draw_text(bg, (60, 60), case_no, 5, WARN)
    words = title.upper().split()
    lines = [" ".join(words[i:i + 2]) for i in range(0, len(words), 2)][:2]
    for k, line in enumerate(lines):
        draw_text(bg, (60, 400 + k * 130), line, 11, BONE)
    return bg
