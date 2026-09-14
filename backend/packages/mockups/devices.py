"""Reusable device scenes. Only the icon and its label change at recipe runtime.

Scene creation and photo upscaling happen once, outside the application. Rendering
uses bundled assets/fonts and local pixel transforms; it needs no model or server.
"""

from functools import lru_cache
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from packages.mockups.draw import icon_mask, rounded_mask
from packages.mockups.fonts import font

ASSETS = Path(__file__).parent / "assets" / "devices"


@lru_cache(maxsize=3)
def _asset(name: str) -> Image.Image:
    with Image.open(ASSETS / name) as image:
        return image.copy()


def home_screen(icon: Image.Image, label: str) -> Image.Image:
    screen = _asset("ios-home.png").copy()
    tile = icon.convert("RGB").resize((180, 180), Image.Resampling.LANCZOS)
    screen.paste(tile, (105, 270), icon_mask(180))
    # Keep adjacent labels clear, including when an app has a long Unicode name.
    draw = ImageDraw.Draw(screen)
    face = font("regular", 36)
    label = " ".join(label.split())
    while label and draw.textlength(label, font=face) > 250:
        label = label.rstrip("…")[:-1] + "…"
        if label == "…":
            break
    draw.text((195, 486), label, font=face, anchor="mm", fill="white")
    return screen


def _warp(screen: Image.Image, scene: str, size: tuple[int, int]):
    calibration = json.loads((ASSETS / f"{scene}.json").read_text())
    if list(size) != calibration["plate_size"]:
        raise ValueError("Device scene dimensions do not match its calibration")
    w, h = screen.size
    mask = Image.new("L", screen.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=160, fill=255)
    scale = 2 if size[0] >= 3000 else 3
    large = (size[0] * scale, size[1] * scale)
    # Pillow takes the inverse homography: destination pixel -> source pixel.
    # Solve it locally rather than adding an OpenCV runtime dependency.
    rows, values = [], []
    for (x, y), (u, v) in zip(
        calibration["screen_quad"], [(0, 0), (w, 0), (w, h), (0, h)]
    ):
        x, y = x * scale, y * scale
        rows.extend(
            [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        )
        values.extend([u, v])
    coefficients = np.linalg.solve(np.asarray(rows), np.asarray(values))

    def warp(image):
        return image.transform(
            large, Image.Transform.PERSPECTIVE, coefficients, Image.Resampling.BICUBIC
        ).resize(size, Image.Resampling.LANCZOS)

    return np.asarray(warp(screen)), warp(mask)


def render_lifestyle(screen: Image.Image) -> Image.Image:
    plate = _asset("cafe.jpg")
    w, h = screen.size
    yy, xx = np.mgrid[:h, :w]
    glare = (0.11 + 0.055 * (1 - xx / w) + 0.018 * np.sin(yy / h * np.pi))[..., None]
    pixels = (
        np.asarray(screen).astype(float) * (1 - glare)
        + np.array([175, 185, 195]) * glare
    )
    mapped, mask = _warp(
        Image.fromarray(pixels.astype("uint8")), "lifestyle", plate.size
    )
    return Image.composite(Image.fromarray(mapped), plate, mask)


def render_studio(screen: Image.Image, icon: Image.Image) -> Image.Image:
    plate = _asset("studio.png")
    mapped, mask = _warp(screen, "studio", plate.size)
    reflection = np.asarray(plate.convert("RGB")).astype(float)
    mapped = 255 - (255 - mapped.astype(float)) * (1 - reflection / 255)
    display = Image.fromarray(np.uint8(np.clip(mapped, 0, 255))).convert("RGBA")
    phone = Image.composite(display, plate, mask)
    image = Image.new("RGB", (1500, 1000), "#050608")
    image.paste(phone, (500, 0), phone)
    tile = icon.convert("RGB").resize((310, 310), Image.Resampling.LANCZOS)
    image.paste(tile, (100, 345), rounded_mask(310, 310, 75))
    return image


def device_previews(icon: Image.Image, label: str):
    """Yield files one at a time to bound memory during multi-run packages."""
    screen = home_screen(icon, label)
    yield "device-studio.png", render_studio(screen, icon)
    yield "device-lifestyle.png", render_lifestyle(screen)
