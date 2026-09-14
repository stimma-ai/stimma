"""Shipped UI fonts, so text in a mockup looks the same on every machine."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

_DIR = Path(__file__).parent / "assets" / "fonts"
_FILES = {
    "regular": "NotoSans-Regular.ttf",
    "medium": "NotoSans-Medium.ttf",
    "bold": "NotoSans-Bold.ttf",
}


@lru_cache(maxsize=64)
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_DIR / _FILES[weight]), int(size))
