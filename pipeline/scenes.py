"""Procedural low-poly 3D scene templates, animated (DECISIONS D17).

Flat-shaded polygons projected through a pinhole camera with distance fog, rendered at
the PS2 internal resolution. Fast enough to render every frame on a CI CPU, so "scene3d"
hero shots get real camera motion at $0. Templates: hallway, night_road, room.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from pipeline.brand_art import BONE, FOG, RGB, SICKLY, SODIUM, Cam, _fog, _mix, _vignette, hallway

SceneFn = Callable[[int, int, float, float, int, float], Image.Image]


def _add_glow(img: Image.Image, glow: Image.Image, radius: int) -> Image.Image:
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(1, radius)))
    out = np.clip(np.asarray(img, dtype=np.int16) + np.asarray(glow, dtype=np.int16), 0, 255)
    return Image.fromarray(out.astype(np.uint8))


def night_road(w: int, h: int, cam_z: float, cam_x: float, seed: int,
               flicker: float) -> Image.Image:
    """Two-lane rural road at night: sodium streetlights, treeline, fog, dashed line."""
    rng = np.random.default_rng(seed)
    cam = Cam(w, h, f=w * 0.95, cam_y=1.3, horizon=0.46, cam_x=cam_x)
    sky_top, sky_bot = (8, 12, 14), FOG
    img = Image.new("RGB", (w, h), FOG)
    d = ImageDraw.Draw(img)
    hz = int(h * cam.horizon)
    for y in range(hz):
        d.line([(0, y), (w, y)], fill=_mix(sky_top, sky_bot, y / max(1, hz)))
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    far, step = 40.0, 2.0
    # treeline silhouettes
    for side in (-1, 1):
        for k in range(26):
            z = 3 + k * 1.5 - (cam_z % 1.5)
            x = side * (5.5 + rng.uniform(0, 3))
            ht = rng.uniform(3.5, 7)
            col = _mix((10, 16, 12), FOG, _fog(z, 1, 28))
            base_l, base_r = cam.p(x - 1.2, 0, z), cam.p(x + 1.2, 0, z)
            top = cam.p(x, ht, z)
            d.polygon([base_l, base_r, top], fill=col)
    # ground + road strips, back to front
    z = far
    i = 0
    while z > 0.6:
        z0, z1 = max(0.6, z - step), z
        fz = _fog((z0 + z1) / 2, 1, 30)
        d.polygon([cam.p(-30, 0, z0), cam.p(30, 0, z0), cam.p(30, 0, z1), cam.p(-30, 0, z1)],
                  fill=_mix((26, 30, 22), FOG, fz))
        d.polygon([cam.p(-3, 0, z0), cam.p(3, 0, z0), cam.p(3, 0, z1), cam.p(-3, 0, z1)],
                  fill=_mix((44, 44, 46), FOG, fz))
        z -= step
        i += 1
    off = cam_z % 3.0
    for k in range(14):
        z0 = 1.0 + k * 3.0 - off
        if z0 < 0.6:
            continue
        fz = _fog(z0, 1, 30)
        d.polygon([cam.p(-0.06, 0.001, z0), cam.p(0.06, 0.001, z0), cam.p(0.06, 0.001, z0 + 1.2),
                   cam.p(-0.06, 0.001, z0 + 1.2)], fill=_mix((200, 170, 90), FOG, fz))
    # streetlights (one flickering)
    loff = cam_z % 9.0
    for k in range(5):
        z = 4 + k * 9.0 - loff
        if z < 0.8:
            continue
        fz = _fog(z, 1, 30)
        x = 3.6
        pw = max(1, int(cam.f * 0.12 / z))
        d.line([cam.p(x, 0, z), cam.p(x, 5, z)], fill=_mix((74, 70, 62), FOG, fz), width=pw)
        d.line([cam.p(x, 5, z), cam.p(x - 1.2, 5, z)], fill=_mix((74, 70, 62), FOG, fz),
               width=pw)
        on = flicker if k == 1 else 1.0
        lx, ly = cam.p(x - 1.2, 4.9, z)
        r = max(1.0, cam.f * 0.18 / z)
        g.ellipse([lx - r, ly - r, lx + r, ly + r], fill=_mix((0, 0, 0), SODIUM, on * (1 - fz)))
        pool = [cam.p(x - 2.4, 0.002, z - 1.0), cam.p(x - 0.2, 0.002, z - 1.0),
                cam.p(x - 0.2, 0.002, z + 1.0), cam.p(x - 2.4, 0.002, z + 1.0)]
        g.polygon(pool, fill=_mix((0, 0, 0), (70, 50, 26), on * (1 - fz) ** 2))
    return _vignette(_add_glow(img, glow, h // 50), 0.5)


def room(w: int, h: int, cam_z: float, cam_x: float, seed: int, flicker: float) -> Image.Image:
    """Wood-panel living room at night: window, CRT glow, half-open door."""
    rng = np.random.default_rng(seed)
    cam = Cam(w, h, f=w * 0.85, cam_y=1.4, horizon=0.5, cam_x=cam_x)
    img = Image.new("RGB", (w, h), FOG)
    d = ImageDraw.Draw(img)
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    back = 6.0 - cam_z
    hw, ceil = 2.6, 2.5
    wood, wood_d = (96, 68, 44), (70, 50, 34)

    def quad(pts: list[tuple[float, float, float]], col: RGB, fz: float) -> None:
        d.polygon([cam.p(*p) for p in pts], fill=_mix(col, FOG, fz))

    fzb = _fog(back, 1, 12)
    quad([(-hw, 0, back), (hw, 0, back), (hw, ceil, back), (-hw, ceil, back)], wood, fzb)
    for k in range(-5, 6):  # panel grooves
        x = k * 0.48
        d.line([cam.p(x, 0, back), cam.p(x, ceil, back)], fill=_mix(wood_d, FOG, fzb))
    quad([(-hw, 0, 0.5), (-hw, 0, back), (-hw, ceil, back), (-hw, ceil, 0.5)], wood_d, 0.15)
    quad([(hw, 0, 0.5), (hw, 0, back), (hw, ceil, back), (hw, ceil, 0.5)], wood_d, 0.25)
    quad([(-hw, 0, 0.5), (hw, 0, 0.5), (hw, 0, back), (-hw, 0, back)], (58, 50, 44), 0.1)
    quad([(-hw, ceil, 0.5), (hw, ceil, 0.5), (hw, ceil, back), (-hw, ceil, back)],
         (46, 46, 42), 0.2)
    # window with night outside and a sliver of moon
    quad([(-1.6, 1.0, back - 0.01), (-0.4, 1.0, back - 0.01), (-0.4, 2.0, back - 0.01),
          (-1.6, 2.0, back - 0.01)], (14, 20, 30), 0)
    mx, my = cam.p(-0.75, 1.75, back - 0.02)
    mr = cam.f * 0.07 / back
    d.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=(150, 160, 150))
    d.line([cam.p(-1.0, 1.0, back - 0.02), cam.p(-1.0, 2.0, back - 0.02)], fill=wood_d, width=2)
    # half-open door on right wall: dark gap
    quad([(hw - 0.01, 0, back - 1.6), (hw - 0.01, 0, back - 0.7), (hw - 0.01, 2.05, back - 0.7),
          (hw - 0.01, 2.05, back - 1.6)], (6, 6, 6), 0.1)
    # CRT TV on a stand, glowing
    tz = back - 1.0
    quad([(0.6, 0, tz), (1.6, 0, tz), (1.6, 0.55, tz), (0.6, 0.55, tz)], (40, 32, 26), 0.1)
    quad([(0.7, 0.55, tz), (1.5, 0.55, tz), (1.5, 1.2, tz), (0.7, 1.2, tz)], (52, 50, 44), 0.1)
    scr = [cam.p(0.78, 0.63, tz - 0.01), cam.p(1.32, 0.63, tz - 0.01),
           cam.p(1.32, 1.1, tz - 0.01), cam.p(0.78, 1.1, tz - 0.01)]
    level = 0.75 + 0.25 * flicker * rng.uniform(0.8, 1.0)
    d.polygon(scr, fill=_mix((20, 30, 24), (190, 220, 200), level))
    g.polygon(scr, fill=_mix((0, 0, 0), SICKLY, level * 0.8))
    floor_pool = [cam.p(0.0, 0.001, tz - 1.6), cam.p(2.2, 0.001, tz - 1.6),
                  cam.p(2.2, 0.001, tz), cam.p(0.0, 0.001, tz)]
    g.polygon(floor_pool, fill=_mix((0, 0, 0), (40, 56, 44), level))
    return _vignette(_add_glow(img, glow, h // 30), 0.55)


def _hallway(w: int, h: int, cam_z: float, cam_x: float, seed: int,
             flicker: float) -> Image.Image:
    return hallway(w, h, seed=seed, figure=True, cam_z=cam_z, cam_x=cam_x, flicker=flicker)


TEMPLATES: dict[str, SceneFn] = {"hallway": _hallway, "night_road": night_road, "room": room}


def camera(move: str, t: float) -> tuple[float, float]:
    """(cam_z, cam_x) for normalized time t in [0, 1]."""
    if move in ("push_in", "creep_forward"):
        return 1.1 * t, 0.0
    if move == "pull_out":
        return 1.1 * (1 - t), 0.0
    if move == "dolly_left":
        return 0.2 * t, -0.35 * t
    if move == "dolly_right":
        return 0.2 * t, 0.35 * t
    return 0.15 * t, 0.06 * math.sin(t * 2 * math.pi * 1.3)   # handheld_sway


def flicker_value(frame: int, seed: int) -> float:
    rng = np.random.default_rng(seed * 100_003 + frame // 2)
    return 0.15 if rng.random() < 0.08 else 1.0


def render_frame(template: str, move: str, t: float, frame: int, w: int, h: int,
                 seed: int) -> Image.Image:
    cz, cx = camera(move, t)
    return TEMPLATES[template](w, h, cz, cx, seed, flicker_value(frame, seed))


def template_for_prompt(prompt: str) -> str:
    p = prompt.lower()
    if any(k in p for k in ("road", "highway", "street", "car", "forest", "woods", "field",
                            "bridge", "trail", "parking")):
        return "night_road"
    if any(k in p for k in ("room", "house", "home", "kitchen", "bedroom", "apartment",
                            "living", "cabin", "office", "tv", "television")):
        return "room"
    return "hallway"


__all__ = ["BONE", "TEMPLATES", "camera", "render_frame", "template_for_prompt"]
