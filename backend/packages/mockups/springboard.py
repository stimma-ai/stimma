"""An iPhone with the icon on its home screen, rendered.

Geometry is in points on a 393 x 852 screen (the current 6.1" class), drawn at
``scale`` pixels per point. Everything is original: the frame, the wallpaper,
the neighbouring apps and their glyphs, the OS chrome.
"""

from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from packages.mockups import draw as D
from packages.mockups.fonts import font

SCREEN_W, SCREEN_H = 393, 852
BEZEL = 5          # frame thickness in points
FRAME_R = 55       # outer corner radius
SCREEN_R = 50
ICON = 60          # home screen icon size in points
COLS = 4
ROWS = 6
LEFT = 27          # first column x
TOP = 82           # first row y (below the status bar)
COL_STEP = (SCREEN_W - 2 * LEFT - ICON) / (COLS - 1)
ROW_STEP = 94
LABEL_SIZE = 11
DOCK_H = 96
DOCK_MARGIN = 8


def _wallpaper(mode: str, w: int, h: int) -> Image.Image:
    """A soft gradient with a few large blurred forms — the shape of most stock wallpapers."""
    if mode == "dark":
        base = D.vertical_gradient(w, h, D.rgb("#1A1F3A"), D.rgb("#07080F"))
        blobs = [((0.78, 0.06), 0.62, "#5B4B9E", 170), ((0.12, 0.34), 0.55, "#1E4C8A", 150),
                 ((0.55, 0.92), 0.7, "#28124A", 120)]
    else:
        base = D.vertical_gradient(w, h, D.rgb("#F5EFE6"), D.rgb("#D9DFEC"))
        blobs = [((0.82, 0.04), 0.66, "#FFC98A", 175), ((0.08, 0.3), 0.6, "#A9CBF0", 165),
                 ((0.62, 0.9), 0.75, "#F2B8C8", 120)]
    small_w, small_h = max(1, w // 6), max(1, h // 6)
    layer = Image.new("RGBA", (small_w, small_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for (cx, cy), rad, color, alpha in blobs:
        r = rad * small_w
        x, y = cx * small_w, cy * small_h
        d.ellipse((x - r, y - r * 0.8, x + r, y + r * 0.8), fill=D.rgb(color) + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(small_w / 5)).resize((w, h), Image.BICUBIC)
    base.alpha_composite(layer)
    return base


def _status_bar(img: Image.Image, mode: str, s: float) -> None:
    d = ImageDraw.Draw(img)
    ink = (255, 255, 255, 255) if mode == "dark" else (17, 17, 20, 255)
    d.text((int(44 * s), int(17 * s)), "9:41", font=font("bold", int(15 * s)), fill=ink)
    x0, y0 = int(SCREEN_W * s - 78 * s), int(24 * s)
    for i, hgt in enumerate((4, 6, 8, 10)):
        bx = x0 + int(i * 5 * s)
        d.rounded_rectangle((bx, y0 + int((10 - hgt) * s), bx + int(3 * s), y0 + int(10 * s)),
                            radius=int(1 * s), fill=ink)
    wx, wy = int(SCREEN_W * s - 53 * s), int(30 * s)
    for r in (int(9 * s), int(5.5 * s)):
        d.arc((wx - r, wy - r, wx + r, wy + r), 225, 315, fill=ink, width=max(1, int(2.2 * s)))
    d.ellipse((wx - int(1.7 * s), wy - int(1.7 * s), wx + int(1.7 * s), wy + int(1.7 * s)), fill=ink)
    bx, by = int(SCREEN_W * s - 40 * s), int(22 * s)
    d.rounded_rectangle((bx, by, bx + int(25 * s), by + int(12 * s)), radius=int(3.5 * s), outline=ink, width=max(1, int(1.2 * s)))
    d.rounded_rectangle((bx + int(2 * s), by + int(2 * s), bx + int(20 * s), by + int(10 * s)), radius=int(2 * s), fill=ink)
    d.rounded_rectangle((bx + int(26 * s), by + int(4 * s), bx + int(27.5 * s), by + int(8 * s)), radius=int(1 * s), fill=ink)


def _label(d: ImageDraw.ImageDraw, text: str, cx: float, y: float, mode: str, s: float) -> None:
    f = font("regular", int(LABEL_SIZE * s))
    text = D.ellipsize(d, text, f, int((COL_STEP - 6) * s))
    w = D.text_width(d, text, f)
    if mode == "dark":
        d.text((cx - w / 2 + 1, y + 1), text, font=f, fill=(0, 0, 0, 120))
        d.text((cx - w / 2, y), text, font=f, fill=(255, 255, 255, 255))
    else:
        d.text((cx - w / 2, y), text, font=f, fill=(17, 17, 20, 255))


def _place(screen: Image.Image, tile: Image.Image, x: int, y: int, s: float, strong: bool) -> None:
    sh_layer, pad = D.shadow(D.icon_mask(tile.width), blur=3 * s, alpha=70 if strong else 40, offset=(0, int(2 * s)))
    screen.alpha_composite(sh_layer, (x - pad, y - pad))
    screen.alpha_composite(tile, (x, y))


def render_iphone(icon: Image.Image, label: str, *, mode: str = "dark", scale: float = 3.0) -> Image.Image:
    """The phone, on a transparent canvas with its shadow, at ``scale`` px per point.

    ``icon`` is the finished device icon (opaque, full bleed); it is masked here.
    """
    s = scale
    sw, sh = int(SCREEN_W * s), int(SCREEN_H * s)
    screen = _wallpaper(mode, sw, sh)
    icon_px = int(ICON * s)
    ours = icon.convert("RGBA").resize((icon_px, icon_px), Image.LANCZOS)
    ours.putalpha(D.icon_mask(icon_px))

    d = ImageDraw.Draw(screen)
    for idx in range(COLS * ROWS):
        col, row = idx % COLS, idx // COLS
        x = int((LEFT + col * COL_STEP) * s)
        y = int((TOP + row * ROW_STEP) * s)
        if idx == 0:
            tile, name, strong = ours, label, True
        else:
            entry = D.NEIGHBOURS[(idx - 1) % len(D.NEIGHBOURS)]
            tile, name, strong = D.neighbour_icon(entry, icon_px), entry[0], False
        _place(screen, tile, x, y, s, strong)
        d = ImageDraw.Draw(screen)
        _label(d, name, x + icon_px / 2, y + icon_px + int(5 * s), mode, s)

    # dock: frosted glass over the wallpaper
    dock_box = (int(DOCK_MARGIN * s), sh - int((DOCK_H + 26) * s), sw - int(DOCK_MARGIN * s), sh - int(26 * s))
    screen = D.blur_region(screen, dock_box, 14 * s)
    tint = (255, 255, 255, 46) if mode == "dark" else (255, 255, 255, 120)
    dock_layer = Image.new("RGBA", screen.size, (0, 0, 0, 0))
    ImageDraw.Draw(dock_layer).rounded_rectangle(dock_box, radius=int(30 * s), fill=tint)
    screen.alpha_composite(dock_layer)
    dock_y = dock_box[1] + int((DOCK_H - ICON) / 2 * s)
    for i, entry in enumerate(D.NEIGHBOURS[:4]):
        _place(screen, D.neighbour_icon(entry, icon_px), int((LEFT + i * COL_STEP) * s), dock_y, s, False)

    d = ImageDraw.Draw(screen)
    bar_ink = (255, 255, 255, 200) if mode == "dark" else (17, 17, 20, 190)
    bw = int(134 * s)
    d.rounded_rectangle(((sw - bw) // 2, sh - int(13 * s), (sw + bw) // 2, sh - int(8 * s)), radius=int(3 * s), fill=bar_ink)
    _status_bar(screen, mode, s)
    d = ImageDraw.Draw(screen)
    d.rounded_rectangle(((sw - int(126 * s)) // 2, int(11 * s), (sw + int(126 * s)) // 2, int(48 * s)),
                        radius=int(19 * s), fill=(5, 5, 6, 255))

    sheen = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).polygon([(0, 0), (int(sw * 0.62), 0), (0, int(sh * 0.46))], fill=(255, 255, 255, 18))
    screen.alpha_composite(sheen.filter(ImageFilter.GaussianBlur(40 * s)))
    screen.putalpha(D.rounded_mask(sw, sh, SCREEN_R * s))

    # frame with a lighter edge ring
    fw, fh = sw + int(2 * BEZEL * s), sh + int(2 * BEZEL * s)
    if mode == "dark":
        frame = D.vertical_gradient(fw, fh, D.rgb("#5A5A61"), D.rgb("#26262A"))
        edge = D.vertical_gradient(fw, fh, D.rgb("#9C9CA3"), D.rgb("#3B3B41"))
    else:
        frame = D.vertical_gradient(fw, fh, D.rgb("#F4F3F0"), D.rgb("#C4C3C0"))
        edge = D.vertical_gradient(fw, fh, D.rgb("#FFFFFF"), D.rgb("#DEDDD9"))
    outer = D.rounded_mask(fw, fh, FRAME_R * s)
    e = int(1.2 * s)
    inner_full = Image.new("L", (fw, fh), 0)
    inner_full.paste(D.rounded_mask(fw - 2 * e, fh - 2 * e, (FRAME_R - 1.2) * s), (e, e))
    ring = ImageChops.subtract(outer, inner_full)
    body = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    body.paste(frame, (0, 0), outer)
    body.paste(edge, (0, 0), ring)
    body.alpha_composite(screen, (int(BEZEL * s), int(BEZEL * s)))
    bd = ImageDraw.Draw(body)
    btn = D.rgb("#3A3A40") if mode == "dark" else D.rgb("#B8B7B3")
    for y0, h0 in ((150, 34), (205, 62), (280, 62)):
        bd.rounded_rectangle((0, int(y0 * s), int(1.5 * s), int((y0 + h0) * s)), fill=btn)
    bd.rounded_rectangle((fw - int(1.5 * s), int(230 * s), fw, int(330 * s)), fill=btn)

    sh_layer, pad = D.shadow(outer, blur=26 * s, alpha=150, offset=(0, int(22 * s)))
    canvas = Image.new("RGBA", sh_layer.size, (0, 0, 0, 0))
    canvas.alpha_composite(sh_layer)
    canvas.alpha_composite(body, (pad, pad))
    return canvas
