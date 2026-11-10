import numpy as np
from PIL import Image

from pipeline import brand_art
from pipeline.fx.pixeltext import render_text, text_size
from pipeline.fx.ps2 import PS2Params, apply_ps2


def _gradient(w=320, h=180):
    a = np.zeros((h, w, 3), dtype=np.uint8)
    a[..., 0] = np.linspace(0, 255, w)[None, :]
    a[..., 1] = np.linspace(0, 255, h)[:, None]
    return Image.fromarray(a)


def test_ps2_output_size_and_determinism():
    src = _gradient()
    a = apply_ps2(src, (640, 360), seed=1)
    b = apply_ps2(src, (640, 360), seed=1)
    assert a.size == (640, 360)
    assert np.array_equal(np.asarray(a), np.asarray(b))


def test_ps2_reduces_palette_before_noise():
    p = PS2Params(internal_height=90, vhs_noise=0, scanlines=0, chromatic_aberration_px=0)
    out = np.asarray(apply_ps2(_gradient(), (320, 180), p))
    assert len(np.unique(out.reshape(-1, 3), axis=0)) <= p.levels_per_channel ** 3


def test_params_from_style(settings):
    p = PS2Params.from_style(settings.style)
    assert p.internal_height == settings.style["post_process"]["internal_height"]


def test_pixel_text_scales():
    w, h = text_size("CASE", 4)
    img = render_text("CASE", 4, (255, 255, 255))
    assert img.mode == "RGBA" and img.width >= w


def test_brand_art_sizes():
    assert brand_art.banner("Test Name", "TAGLINE").size == (2560, 1440)
    assert brand_art.profile_picture(200).size == (200, 200)
    wm = brand_art.watermark(150)
    assert wm.size == (150, 150) and wm.mode == "RGBA"
    assert wm.getpixel((0, 0))[3] == 0          # transparent corner
    assert brand_art.end_screen("X").size == (1920, 1080)
    assert brand_art.thumbnail_template("Vanished From Room", "CASE #1").size == (1280, 720)
