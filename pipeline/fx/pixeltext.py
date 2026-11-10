"""Chunky bitmap text: Pillow's built-in bitmap font scaled with nearest-neighbour.

No external font files, so no licensing to track. Used for captions, case cards,
banner titles and thumbnails.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

_FONT = ImageFont.load_default_imagefont()


def text_size(text: str, scale: int) -> tuple[int, int]:
    x0, y0, x1, y1 = _FONT.getbbox(text)
    return (x1 - x0) * scale, (y1 - y0 + 2) * scale


def render_text(text: str, scale: int, color: tuple[int, int, int],
                shadow: tuple[int, int, int] | None = (0, 0, 0)) -> Image.Image:
    """RGBA image of `text` in pixel font at integer `scale`, with a 1px drop shadow."""
    x0, y0, x1, y1 = _FONT.getbbox(text)
    w, h = x1 - x0 + 2, y1 - y0 + 4
    small = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(small)
    if shadow is not None:
        d.text((1 - x0, 2 - y0), text, font=_FONT, fill=(*shadow, 255))
    d.text((-x0, 1 - y0), text, font=_FONT, fill=(*color, 255))
    return small.resize((w * scale, h * scale), Image.Resampling.NEAREST)


def draw_text(img: Image.Image, xy: tuple[int, int], text: str, scale: int,
              color: tuple[int, int, int], anchor: str = "lt",
              shadow: tuple[int, int, int] | None = (0, 0, 0)) -> None:
    """Paste pixel text onto `img`. anchor: 'lt' top-left, 'mm' centre, 'rb' bottom-right."""
    t = render_text(text, scale, color, shadow)
    x, y = xy
    if anchor == "mm":
        x, y = x - t.width // 2, y - t.height // 2
    elif anchor == "rb":
        x, y = x - t.width, y - t.height
    img.paste(t, (x, y), t)
