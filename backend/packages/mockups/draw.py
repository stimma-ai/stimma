"""Small drawing helpers shared by the mockups. All supersampled, all deterministic."""

from __future__ import annotations


from PIL import Image, ImageChops, ImageDraw, ImageFilter

IOS_RADIUS = 0.2237  # the rounded-rect approximation of Apple's icon superellipse
SS = 3  # supersample factor for masks and glyphs


def rgb(hexstr: str) -> tuple[int, int, int]:
    h = hexstr.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rounded_mask(w: int, h: int, radius: float) -> Image.Image:
    m = Image.new("L", (w * SS, h * SS), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=int(radius * SS), fill=255)
    return m.resize((w, h), Image.LANCZOS)


def icon_mask(size: int) -> Image.Image:
    return rounded_mask(size, size, size * IOS_RADIUS)


def vertical_gradient(w: int, h: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    strip = Image.new("RGB", (1, h))
    px = strip.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(int(round(top[i] + (bottom[i] - top[i]) * t)) for i in range(3))
    return strip.resize((w, h), Image.NEAREST).convert("RGBA")


def fit(art: Image.Image, size: int) -> Image.Image:
    """The artwork inside a size x size canvas, aspect kept, centred."""
    art = art.convert("RGBA")
    scaled = art.copy()
    scaled.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2), scaled)
    return canvas


def device_icon(art: Image.Image, size: int, background: str) -> Image.Image:
    """The icon exactly as iOS draws it: full bleed on its canvas, corners masked."""
    flat = Image.new("RGBA", (size, size), rgb(background) + (255,))
    flat.alpha_composite(fit(art, size))
    flat.putalpha(icon_mask(size))
    return flat


def shadow(mask: Image.Image, blur: float, alpha: int, offset: tuple[int, int] = (0, 0)) -> Image.Image:
    """A soft shadow the shape of ``mask``, on a transparent canvas of the same size."""
    pad = int(blur * 3) + max(abs(offset[0]), abs(offset[1])) + 2
    canvas = Image.new("RGBA", (mask.width + pad * 2, mask.height + pad * 2), (0, 0, 0, 0))
    layer = Image.new("RGBA", mask.size, (0, 0, 0, alpha))
    layer.putalpha(ImageChops.multiply(mask, Image.new("L", mask.size, alpha)))
    canvas.paste(layer, (pad + offset[0], pad + offset[1]), layer)
    return canvas.filter(ImageFilter.GaussianBlur(blur)), pad  # type: ignore[return-value]


def text_width(draw: ImageDraw.ImageDraw, text: str, fnt) -> int:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=fnt)
    return right - left


def ellipsize(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> str:
    if text_width(draw, text, fnt) <= max_w:
        return text
    while text and text_width(draw, text + "…", fnt) > max_w:
        text = text[:-1]
    return text + "…"


def blur_region(img: Image.Image, box: tuple[int, int, int, int], radius: float) -> Image.Image:
    region = img.crop(box).filter(ImageFilter.GaussianBlur(radius))
    out = img.copy()
    out.paste(region, box)
    return out


def glyph(kind: str, size: int, color=(255, 255, 255, 235)) -> Image.Image:
    """Simple original glyphs for the neighbouring apps. Drawn, not borrowed."""
    S = size * SS
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    u = S / 100.0  # units in a 100-box
    w = max(2, int(7 * u))

    def L(*pts):
        d.line([(x * u, y * u) for x, y in pts], fill=color, width=w, joint="curve")

    if kind == "mail":
        d.rounded_rectangle((18 * u, 30 * u, 82 * u, 72 * u), radius=8 * u, outline=color, width=w)
        L((18, 32), (50, 55), (82, 32))
    elif kind == "calendar":
        d.rounded_rectangle((20 * u, 24 * u, 80 * u, 78 * u), radius=8 * u, outline=color, width=w)
        d.rectangle((20 * u, 24 * u, 80 * u, 40 * u), fill=color)
        for x in (34, 50, 66):
            d.ellipse((x * u - 4 * u, 55 * u - 4 * u, x * u + 4 * u, 55 * u + 4 * u), fill=color)
    elif kind == "camera":
        d.rounded_rectangle((16 * u, 32 * u, 84 * u, 74 * u), radius=10 * u, outline=color, width=w)
        d.ellipse((38 * u, 41 * u, 62 * u, 65 * u), outline=color, width=w)
        d.rectangle((36 * u, 24 * u, 56 * u, 33 * u), fill=color)
    elif kind == "clock":
        d.ellipse((18 * u, 18 * u, 82 * u, 82 * u), outline=color, width=w)
        L((50, 30), (50, 52), (66, 60))
    elif kind == "weather":
        d.ellipse((30 * u, 26 * u, 62 * u, 58 * u), fill=color)
        d.rounded_rectangle((22 * u, 52 * u, 82 * u, 74 * u), radius=11 * u, fill=color)
        d.ellipse((52 * u, 40 * u, 84 * u, 72 * u), fill=color)
    elif kind == "notes":
        d.rounded_rectangle((26 * u, 20 * u, 74 * u, 80 * u), radius=6 * u, outline=color, width=w)
        for y in (40, 52, 64):
            L((36, y), (64, y))
    elif kind == "maps":
        d.ellipse((34 * u, 18 * u, 66 * u, 50 * u), outline=color, width=w)
        d.polygon([(36 * u, 44 * u), (64 * u, 44 * u), (50 * u, 80 * u)], fill=color)
        d.ellipse((43 * u, 27 * u, 57 * u, 41 * u), fill=color)
    elif kind == "music":
        d.ellipse((26 * u, 56 * u, 46 * u, 76 * u), fill=color)
        L((45, 66), (45, 24), (74, 18), (74, 58))
        d.ellipse((56 * u, 50 * u, 76 * u, 70 * u), fill=color)
    elif kind == "photos":
        for i in range(6):
            import math
            a = math.pi * 2 * i / 6
            cx, cy = 50 + 16 * math.cos(a), 50 + 16 * math.sin(a)
            d.ellipse(((cx - 15) * u, (cy - 15) * u, (cx + 15) * u, (cy + 15) * u), fill=color[:3] + (110,))
    elif kind == "settings":
        d.ellipse((22 * u, 22 * u, 78 * u, 78 * u), outline=color, width=int(12 * u))
        import math
        for i in range(8):
            a = math.pi * 2 * i / 8
            x1, y1 = 50 + 30 * math.cos(a), 50 + 30 * math.sin(a)
            x2, y2 = 50 + 40 * math.cos(a), 50 + 40 * math.sin(a)
            d.line([(x1 * u, y1 * u), (x2 * u, y2 * u)], fill=color, width=int(11 * u))
    elif kind == "files":
        d.polygon([(24 * u, 20 * u), (58 * u, 20 * u), (76 * u, 38 * u), (76 * u, 80 * u), (24 * u, 80 * u)],
                  outline=color, width=w)
        L((58, 20), (58, 38), (76, 38))
    elif kind == "wallet":
        d.rounded_rectangle((18 * u, 30 * u, 82 * u, 74 * u), radius=8 * u, outline=color, width=w)
        d.rectangle((58 * u, 46 * u, 82 * u, 60 * u), fill=color)
    elif kind == "messages":
        d.rounded_rectangle((16 * u, 22 * u, 84 * u, 66 * u), radius=20 * u, fill=color)
        d.polygon([(30 * u, 62 * u), (30 * u, 80 * u), (46 * u, 64 * u)], fill=color)
    elif kind == "compass":
        d.ellipse((18 * u, 18 * u, 82 * u, 82 * u), outline=color, width=w)
        d.polygon([(50 * u, 26 * u), (58 * u, 50 * u), (50 * u, 74 * u), (42 * u, 50 * u)], fill=color)
    elif kind == "stocks":
        L((18, 70), (38, 48), (54, 60), (82, 30))
        L((66, 30), (82, 30), (82, 46))
    elif kind == "health":
        d.polygon([(50 * u, 78 * u), (20 * u, 48 * u), (28 * u, 28 * u), (50 * u, 36 * u),
                   (72 * u, 28 * u), (80 * u, 48 * u)], fill=color)
    elif kind == "books":
        d.rounded_rectangle((22 * u, 22 * u, 48 * u, 78 * u), radius=4 * u, outline=color, width=w)
        d.rounded_rectangle((52 * u, 22 * u, 78 * u, 78 * u), radius=4 * u, outline=color, width=w)
    elif kind == "podcasts":
        d.ellipse((38 * u, 26 * u, 62 * u, 50 * u), outline=color, width=w)
        d.ellipse((26 * u, 14 * u, 74 * u, 62 * u), outline=color[:3] + (120,), width=w)
        L((50, 50), (50, 80))
    elif kind == "translate":
        d.rounded_rectangle((16 * u, 22 * u, 58 * u, 60 * u), radius=8 * u, outline=color, width=w)
        d.rounded_rectangle((42 * u, 40 * u, 84 * u, 78 * u), radius=8 * u, fill=color)
    elif kind == "reminders":
        for y in (32, 50, 68):
            d.ellipse((22 * u, (y - 6) * u, 34 * u, (y + 6) * u), outline=color, width=w)
            L((42, y), (78, y))
    elif kind == "voice":
        d.rounded_rectangle((40 * u, 18 * u, 60 * u, 56 * u), radius=10 * u, fill=color)
        d.arc((28 * u, 34 * u, 72 * u, 72 * u), 0, 180, fill=color, width=w)
        L((50, 72), (50, 84))
    elif kind == "contacts":
        d.ellipse((36 * u, 22 * u, 64 * u, 50 * u), fill=color)
        d.pieslice((22 * u, 50 * u, 78 * u, 106 * u), 180, 360, fill=color)
    else:  # a plain dot for anything unknown
        d.ellipse((36 * u, 36 * u, 64 * u, 64 * u), fill=color)
    return im.resize((size, size), Image.LANCZOS)


# Neighbouring apps: a gradient each and a glyph. Original, generic, and
# distinct enough that a grid of them reads as somebody's phone.
NEIGHBOURS: list[tuple[str, str, str, str]] = [
    ("Mail", "mail", "#4FA3FF", "#1C68E3"),
    ("Calendar", "calendar", "#FFFFFF", "#F2F2F7"),
    ("Camera", "camera", "#8E8E93", "#3A3A3C"),
    ("Clock", "clock", "#2C2C2E", "#000000"),
    ("Weather", "weather", "#4EA8F5", "#1E63C8"),
    ("Notes", "notes", "#FFE28A", "#F5C842"),
    ("Maps", "maps", "#5CD277", "#2E9C4C"),
    ("Music", "music", "#FF6B7A", "#E8334A"),
    ("Photos", "photos", "#FFFFFF", "#EDEDF0"),
    ("Settings", "settings", "#9A9AA0", "#5B5B60"),
    ("Files", "files", "#3E8BFF", "#1F5FD3"),
    ("Wallet", "wallet", "#2C2C2E", "#0B0B0D"),
    ("Messages", "messages", "#5CE271", "#2FB74B"),
    ("Compass", "compass", "#2E2E30", "#111113"),
    ("Stocks", "stocks", "#1C1C1E", "#000000"),
    ("Health", "health", "#FFFFFF", "#F4F4F6"),
    ("Books", "books", "#FF9F43", "#E8731A"),
    ("Podcasts", "podcasts", "#C77DFF", "#8E3FE0"),
    ("Translate", "translate", "#2D5BFF", "#1439C4"),
    ("Reminders", "reminders", "#FFFFFF", "#EEEEF1"),
    ("Voice", "voice", "#1C1C1E", "#0A0A0B"),
    ("Contacts", "contacts", "#B6B6BB", "#7C7C82"),
    ("Home", "dot", "#FFB25C", "#E9852B"),
]


def neighbour_icon(entry: tuple[str, str, str, str], size: int) -> Image.Image:
    _name, kind, top, bottom = entry
    base = vertical_gradient(size, size, rgb(top), rgb(bottom))
    light = sum(rgb(top)) / 3 > 200
    g = glyph(kind, int(size * 0.72), (40, 40, 45, 230) if light else (255, 255, 255, 235))
    base.alpha_composite(g, ((size - g.width) // 2, (size - g.height) // 2))
    base.putalpha(icon_mask(size))
    return base
