"""Ink and ground helpers shared by recipes that place a mark on a canvas."""

from __future__ import annotations

from typing import Optional

from PIL import Image


def _srgb_to_linear(channel: float) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def parse_hex(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def ink_color(img: Image.Image) -> Optional[tuple[int, int, int]]:
    """The artwork's average colour where it is actually opaque.

    Alpha-weighted, so a mark with a soft edge is judged by its body rather
    than by the transparency around it. None when nothing is opaque enough to
    judge.
    """
    small = img.convert("RGBA")
    small.thumbnail((64, 64), Image.LANCZOS)
    total = 0.0
    acc = [0.0, 0.0, 0.0]
    for r, g, b, a in small.getdata():
        if a < 24:
            continue
        weight = a / 255.0
        total += weight
        acc[0] += r * weight
        acc[1] += g * weight
        acc[2] += b * weight
    if total < 1.0:
        return None
    return tuple(int(round(c / total)) for c in acc)  # type: ignore[return-value]


# The two neutrals a mark gets grounded on when nobody asked for a colour.
# A dark mark needs a light backdrop and a light mark needs a dark one, and
# getting it wrong shows an empty rectangle.
NEUTRAL_LIGHT = "#FFFFFF"
NEUTRAL_DARK = "#141414"
# A mark brighter than this reads as light ink and wants a dark ground.
LIGHT_INK_LUMINANCE = 0.42


def neutral_ground(ink: Optional[tuple[int, int, int]]) -> str:
    """The neutral canvas a mark belongs on, from the mark itself."""
    if ink is None:
        return NEUTRAL_LIGHT
    return NEUTRAL_DARK if relative_luminance(ink) > LIGHT_INK_LUMINANCE else NEUTRAL_LIGHT


# Below this the mark stops separating from its own canvas.
MIN_ICON_CONTRAST = 1.55
