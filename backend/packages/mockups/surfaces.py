"""The other places an icon has to survive, drawn to the OS's proportions.

Each returns an RGBA image at ``scale`` px per point, 390 points wide.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from packages.mockups import draw as D
from packages.mockups.fonts import font

W = 390


def _palette(mode: str) -> dict:
    if mode == "dark":
        return {"bg": (0, 0, 0, 255), "group": (28, 28, 30, 255), "fg": (255, 255, 255, 255),
                "muted": (152, 152, 157, 255), "line": (56, 56, 58, 255), "pill": (54, 54, 58, 255),
                "pill_fg": (255, 255, 255, 255), "chev": (99, 99, 102, 255), "banner": (44, 44, 46, 236)}
    return {"bg": (242, 242, 247, 255), "group": (255, 255, 255, 255), "fg": (0, 0, 0, 255),
            "muted": (110, 110, 115, 255), "line": (216, 216, 220, 255), "pill": (232, 232, 237, 255),
            "pill_fg": (0, 122, 255, 255), "chev": (195, 195, 199, 255), "banner": (248, 248, 250, 238)}


def _canvas(h: int, s: float, mode: str, fill=None):
    img = Image.new("RGBA", (int(W * s), int(h * s)), fill or _palette(mode)["bg"])
    return img, ImageDraw.Draw(img)


def _masked(icon: Image.Image, size: int, radius: float | None = None, *, mode: str = "light") -> Image.Image:
    """The icon masked, with the hairline iOS draws inside list icons.

    That edge is what keeps a white icon from vanishing into a white row; it
    is faint enough to be invisible on any icon that already has contrast.
    """
    ic = icon.convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = D.icon_mask(size) if radius is None else D.rounded_mask(size, size, radius)
    ic.putalpha(mask)
    inset = max(1, int(round(size * 0.02)))
    inner = D.icon_mask(size - 2 * inset) if radius is None else D.rounded_mask(size - 2 * inset, size - 2 * inset, radius - inset)
    ring_mask = Image.new("L", (size, size), 0)
    ring_mask.paste(inner, (inset, inset))
    from PIL import ImageChops
    ring_mask = ImageChops.subtract(mask, ring_mask)
    edge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    edge.putalpha(ImageChops.multiply(ring_mask, Image.new("L", (size, size), 34 if mode == "light" else 46)))
    ic.alpha_composite(edge if mode == "light" else Image.merge("RGBA", [Image.new("L", (size, size), 255)] * 3 + [edge.getchannel("A")]))
    return ic


def render_app_store_row(icon: Image.Image, name: str, subtitle: str, *, mode: str = "light", scale: float = 3.0) -> Image.Image:
    """A store search result: 64pt icon, name, category, the GET pill."""
    s, p = scale, _palette(mode)
    img, d = _canvas(92, s, mode)
    img.alpha_composite(_masked(icon, int(64 * s), mode=mode), (int(20 * s), int(14 * s)))
    d.text((int(96 * s), int(22 * s)), name, font=font("medium", int(17 * s)), fill=p["fg"])
    d.text((int(96 * s), int(46 * s)), subtitle, font=font("regular", int(14 * s)), fill=p["muted"])
    pw, ph = int(72 * s), int(30 * s)
    px, py = int(W * s - 20 * s) - pw, int(31 * s)
    d.rounded_rectangle((px, py, px + pw, py + ph), radius=ph // 2, fill=p["pill"])
    f = font("bold", int(15 * s))
    d.text((px + (pw - D.text_width(d, "GET", f)) / 2, py + int(4.5 * s)), "GET", font=f, fill=p["pill_fg"])
    return img


def render_settings_row(icon: Image.Image, name: str, *, mode: str = "light", scale: float = 3.0) -> Image.Image:
    """An inset grouped list: our app between two ordinary settings."""
    s, p = scale, _palette(mode)
    img, d = _canvas(150, s, mode)
    gx0, gx1 = int(16 * s), int((W - 16) * s)
    group = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(group).rounded_rectangle((gx0, int(6 * s), gx1, int(144 * s)), radius=int(10 * s), fill=p["group"])
    img.alpha_composite(group)
    d = ImageDraw.Draw(img)
    rows = [("Notifications", "#FF3B30", "dot"), (name, None, None), ("Privacy & Security", "#007AFF", "dot")]
    size = int(29 * s)
    for i, (label, color, kind) in enumerate(rows):
        y = int((6 + i * 46) * s)
        if i > 0:
            d.line((int(60 * s), y, gx1, y), fill=p["line"], width=max(1, int(0.7 * s)))
        if color is None:
            ic = _masked(icon, size, 7 * s, mode=mode)
        else:
            ic = D.vertical_gradient(size, size, D.rgb(color), D.rgb(color))
            g = D.glyph(kind, int(size * 0.7))
            ic.alpha_composite(g, ((size - g.width) // 2, (size - g.height) // 2))
            ic.putalpha(D.rounded_mask(size, size, 7 * s))
        img.alpha_composite(ic, (int(31 * s), y + int(8.5 * s)))
        d = ImageDraw.Draw(img)
        d.text((int(72 * s), y + int(13 * s)), label, font=font("regular", int(17 * s)), fill=p["fg"])
        cx, cy = int((W - 30) * s), y + int(23 * s)
        d.line((cx - int(4 * s), cy - int(6 * s), cx, cy, cx - int(4 * s), cy + int(6 * s)), fill=p["chev"], width=max(1, int(1.8 * s)))
    return img


def render_notification(icon: Image.Image, name: str, message: str, *, mode: str = "light", scale: float = 3.0) -> Image.Image:
    """A banner as it lands on the lock screen or over another app."""
    s, p = scale, _palette(mode)
    img = Image.new("RGBA", (int(W * s), int(96 * s)), (0, 0, 0, 0))
    box = (int(10 * s), int(8 * s), int((W - 10) * s), int(88 * s))
    sh, pad = D.shadow(D.rounded_mask(box[2] - box[0], box[3] - box[1], 22 * s), blur=10 * s, alpha=60, offset=(0, int(4 * s)))
    img.alpha_composite(sh, (box[0] - pad, box[1] - pad))
    banner = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(banner).rounded_rectangle(box, radius=int(22 * s), fill=p["banner"])
    img.alpha_composite(banner)
    img.alpha_composite(_masked(icon, int(38 * s), mode=mode), (int(24 * s), int(29 * s)))
    d = ImageDraw.Draw(img)
    d.text((int(74 * s), int(27 * s)), name, font=font("medium", int(15 * s)), fill=p["fg"])
    body = font("regular", int(15 * s))
    d.text((int(74 * s), int(47 * s)), D.ellipsize(d, message, body, int(260 * s)), font=body, fill=p["fg"])
    f = font("regular", int(13 * s))
    d.text((int((W - 24) * s) - D.text_width(d, "now", f), int(28 * s)), "now", font=f, fill=p["muted"])
    return img


def render_spotlight_row(icon: Image.Image, name: str, *, mode: str = "light", scale: float = 3.0) -> Image.Image:
    """Search: the field with the query typed, and the app as the top hit."""
    s, p = scale, _palette(mode)
    img, d = _canvas(132, s, mode)
    # the field
    fx0, fy0, fx1, fy1 = int(16 * s), int(12 * s), int((W - 16) * s), int(48 * s)
    field = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(field).rounded_rectangle((fx0, fy0, fx1, fy1), radius=int(11 * s), fill=p["group"] if mode == "light" else (44, 44, 46, 255))
    img.alpha_composite(field)
    d = ImageDraw.Draw(img)
    cx, cy, r = int(34 * s), int(30 * s), int(6 * s)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=p["muted"], width=max(1, int(1.8 * s)))
    d.line((cx + int(4.5 * s), cy + int(4.5 * s), cx + int(9 * s), cy + int(9 * s)), fill=p["muted"], width=max(1, int(1.8 * s)))
    d.text((int(50 * s), int(21 * s)), name, font=font("regular", int(17 * s)), fill=p["fg"])
    # caret after the query
    tw = D.text_width(d, name, font("regular", int(17 * s)))
    d.rectangle((int(52 * s) + tw, int(21 * s), int(53.5 * s) + tw, int(41 * s)), fill=(0, 122, 255, 255))
    # the top hit
    card = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle((fx0, int(58 * s), fx1, int(122 * s)), radius=int(11 * s), fill=p["group"])
    img.alpha_composite(card)
    img.alpha_composite(_masked(icon, int(44 * s), mode=mode), (int(28 * s), int(68 * s)))
    d = ImageDraw.Draw(img)
    d.text((int(84 * s), int(72 * s)), name, font=font("medium", int(16 * s)), fill=p["fg"])
    d.text((int(84 * s), int(94 * s)), "App", font=font("regular", int(13 * s)), fill=p["muted"])
    return img
