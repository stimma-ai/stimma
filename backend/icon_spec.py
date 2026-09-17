"""Platform app-icon rules, in one place.

Every producer of app icons reads this module: the SVG export in
``routes/svg_media.py`` and the ``app-icons`` recipe in
``packages/builtin/app_icons.py``. There is one table per platform and one
copy of each container writer, so the two can never disagree and a rule can
only be got wrong once.

The rules that matter, with the reasoning that is easy to lose:

- **iOS** icons are full bleed and opaque. Apple rejects an App Store icon
  that carries an alpha channel, and the system applies its own mask, so
  artwork must reach the edge and must not be pre-rounded.
- **Android adaptive icons** have two layers, each a *108dp* canvas at every
  density, with essential artwork inside the guaranteed 66dp circle. The
  launcher masks the central 72dp region and animates within the 108dp field. Shipping a layer at the legacy launcher size (48dp) is the classic
  mistake: the system scales it up, so it is soft, and art that looked fine
  lands in the ring the mask crops.
- **Legacy Android launcher icons** (pre-API-26) are standalone artwork, so
  they are full bleed over the brand background.
- **macOS** artwork sits inside a rounded-rect grid rather than filling the
  canvas: 824pt of art in a 1024pt tile in the Big Sur and later template.
  Unlike iOS, the system does not mask an ``.icns``: the tile's rounded
  corners must be baked into every size, or a full-bleed master ships as a
  hard square in the Dock.
- **Windows** ``.ico`` and web favicons are full bleed; the Apple touch icon
  is opaque because iOS Safari composites it without alpha.

Sizes are pixels. ``safe_area`` is the fraction of the canvas the artwork may
occupy, applied by centering the scaled artwork, so nothing is ever stretched.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Iterable, Optional

from PIL import Image

# iOS asset catalog: (idiom, size, scale). Pixels are size * scale.
IOS_ENTRIES: tuple[tuple[str, str, str], ...] = (
    ("iphone", "20x20", "2x"), ("iphone", "20x20", "3x"),
    ("iphone", "29x29", "2x"), ("iphone", "29x29", "3x"),
    ("iphone", "40x40", "2x"), ("iphone", "40x40", "3x"),
    ("iphone", "60x60", "2x"), ("iphone", "60x60", "3x"),
    ("ipad", "20x20", "1x"), ("ipad", "20x20", "2x"),
    ("ipad", "29x29", "1x"), ("ipad", "29x29", "2x"),
    ("ipad", "40x40", "1x"), ("ipad", "40x40", "2x"),
    ("ipad", "76x76", "2x"), ("ipad", "83.5x83.5", "2x"),
    ("ios-marketing", "1024x1024", "1x"),
)

# Android density buckets: legacy launcher icon is 48dp, adaptive layers 108dp.
ANDROID_DENSITIES: tuple[tuple[str, int], ...] = (
    ("mdpi", 1), ("hdpi", 2), ("xhdpi", 2), ("xxhdpi", 3), ("xxxhdpi", 4),
)
ANDROID_DPI_SCALE = {"mdpi": 1.0, "hdpi": 1.5, "xhdpi": 2.0, "xxhdpi": 3.0, "xxxhdpi": 4.0}
LAUNCHER_DP = 48
ADAPTIVE_DP = 108
ADAPTIVE_SAFE_DP = 66
ADAPTIVE_SAFE_AREA = ADAPTIVE_SAFE_DP / ADAPTIVE_DP
PLAY_STORE_PX = 512

# macOS: 824pt of artwork inside a 1024pt tile (Big Sur and later template).
MACOS_SAFE_AREA = 824 / 1024
MACOS_SIZES: tuple[int, ...] = (16, 32, 64, 128, 256, 512, 1024)
WINDOWS_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)
WEB_ICO_SIZES: tuple[int, ...] = (16, 32, 48)
WEB_PNG_SIZES: tuple[int, ...] = (16, 32, 192, 512)
APPLE_TOUCH_PX = 180

# Raster sizes supplied for hicolor application icons. 48px is the baseline
# recommended by the freedesktop Icon Theme specification; larger sizes cover
# high-density launchers. This is an application contribution, not a new theme.
LINUX_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256, 512)
PLATFORMS: tuple[str, ...] = ("ios", "android", "macos", "windows", "linux", "web")


def ios_px(size: str, scale: str) -> int:
    return round(float(size.split("x")[0]) * float(scale.rstrip("x")))


def android_px(density: str, dp: int) -> int:
    return round(dp * ANDROID_DPI_SCALE[density])


@dataclass(frozen=True)
class IconImage:
    """One rendered image a platform needs, and how to compose it."""

    path: str           # relative to the platform folder
    px: int             # square canvas size
    safe_area: float = 1.0
    opaque: bool = False
    role: str = "master"  # which input the artwork comes from


def ios_images() -> list[IconImage]:
    """Catalog entries, deduplicated by pixel size (Xcode shares files)."""
    out: list[IconImage] = []
    seen: set[int] = set()
    for _idiom, size, scale in IOS_ENTRIES:
        px = ios_px(size, scale)
        if px in seen:
            continue
        seen.add(px)
        # Full bleed, opaque: Apple masks the corners itself and rejects alpha.
        out.append(IconImage(f"AppIcon.appiconset/icon-{px}.png", px, 1.0, True))
    return out


def ios_filenames() -> dict[int, str]:
    return {img.px: img.path.split("/")[-1] for img in ios_images()}


def ios_contents_json(name_for: Optional[dict[int, str]] = None) -> str:
    name_for = ios_filenames() if name_for is None else name_for
    images = []
    for idiom, size, scale in IOS_ENTRIES:
        entry = {"idiom": idiom, "size": size, "scale": scale}
        filename = name_for.get(ios_px(size, scale))
        if filename:
            entry["filename"] = filename
        images.append(entry)
    return json.dumps({"images": images, "info": {"version": 1, "author": "stimma"}}, indent=2) + "\n"


def android_images(foreground_role: str = "master") -> list[IconImage]:
    out: list[IconImage] = []
    for density, _ in ANDROID_DENSITIES:
        legacy_px = android_px(density, LAUNCHER_DP)
        adaptive_px = android_px(density, ADAPTIVE_DP)
        # Legacy launchers draw this as-is, so it carries the background.
        out.append(IconImage(f"mipmap-{density}/ic_launcher.png", legacy_px, 1.0, True))
        # Adaptive foreground: 108dp canvas, artwork inside the inner 66dp.
        out.append(IconImage(
            f"mipmap-{density}/ic_launcher_foreground.png", adaptive_px,
            ADAPTIVE_SAFE_AREA, False, foreground_role,
        ))
    out.append(IconImage(f"play-store-{PLAY_STORE_PX}.png", PLAY_STORE_PX, 1.0, True))
    return out


ANDROID_ADAPTIVE_XML = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
    '    <background android:drawable="@color/ic_launcher_background"/>\n'
    '    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>\n'
    '</adaptive-icon>\n'
)


def android_background_xml(color: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        f'    <color name="ic_launcher_background">{color}</color>\n</resources>\n'
    )


def macos_images() -> list[IconImage]:
    return [IconImage(f"icon-{px}.png", px, MACOS_SAFE_AREA, False) for px in MACOS_SIZES]


def windows_images() -> list[IconImage]:
    return [IconImage(f"icon-{px}.png", px, 1.0, False) for px in WINDOWS_SIZES]


def web_images() -> list[IconImage]:
    out = [IconImage(f"icon-{px}.png", px, 1.0, False) for px in sorted({*WEB_ICO_SIZES, *WEB_PNG_SIZES})]
    # Safari composites the touch icon without alpha, so bake the background in.
    out.append(IconImage("apple-touch-icon.png", APPLE_TOUCH_PX, 1.0, True))
    return out


def images_for(platform: str, *, foreground_role: str = "master") -> list[IconImage]:
    if platform == "ios":
        return ios_images()
    if platform == "android":
        return android_images(foreground_role)
    if platform == "macos":
        return macos_images()
    if platform == "windows":
        return windows_images()
    if platform == "linux":
        return [IconImage(f"hicolor/{px}x{px}/apps/icon.png", px) for px in LINUX_SIZES]
    if platform == "web":
        return web_images()
    raise ValueError(f"unknown icon platform: {platform}")


def sizes_for(platform: str) -> list[int]:
    """Every distinct pixel size a platform needs rendered."""
    return sorted({img.px for img in images_for(platform)})


def web_manifest(app_name: str) -> str:
    return json.dumps(
        {
            "name": app_name,
            "short_name": app_name,
            "icons": [
                {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
            ],
        },
        indent=2,
    ) + "\n"


WEB_HEAD_SNIPPET = """<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="/icon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/icon-16.png">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
"""


# Composition and containers --------------------------------------------------

def _srgb_to_linear(channel: float) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def parse_hex(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


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
# Same rule the vector thumbnails use: a dark mark needs a light backdrop and a
# light mark needs a dark one, and getting it wrong shows an empty rectangle.
NEUTRAL_LIGHT = "#FFFFFF"
NEUTRAL_DARK = "#141414"
# A mark brighter than this reads as light ink and wants a dark ground.
LIGHT_INK_LUMINANCE = 0.42


def neutral_ground(ink: Optional[tuple[int, int, int]]) -> str:
    """The neutral canvas a mark belongs on, from the mark itself.

    A brand colour behind a brand mark is a decision someone has to make on
    purpose; this is what to do when they have not. Neutral is also what a
    studio ships by default, because the icon's colour is the artwork's job.
    """
    if ink is None:
        return NEUTRAL_LIGHT
    return NEUTRAL_DARK if relative_luminance(ink) > LIGHT_INK_LUMINANCE else NEUTRAL_LIGHT


# Below this the mark stops separating from its own canvas. Deliberately
# generous: this is the "you cannot see it" floor, not a design opinion.
MIN_ICON_CONTRAST = 1.55


def compose(art: Image.Image, spec: IconImage, background: str = "#FFFFFF") -> Image.Image:
    """Place ``art`` on ``spec``'s canvas, honoring its safe area and opacity.

    The artwork keeps its aspect ratio: the safe area scales it and centers it
    rather than stretching it into the box.
    """
    art = art.convert("RGBA")
    inner = max(1, int(round(spec.px * spec.safe_area)))
    scaled = art.copy()
    scaled.thumbnail((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (spec.px, spec.px), (0, 0, 0, 0))
    canvas.alpha_composite(scaled, ((spec.px - scaled.width) // 2, (spec.px - scaled.height) // 2))
    if spec.opaque:
        flat = Image.new("RGBA", (spec.px, spec.px), background)
        flat.alpha_composite(canvas)
        return flat.convert("RGB")
    return canvas


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def build_icns(images: dict[int, Image.Image]) -> bytes:
    """Write an ``.icns`` from per-size renders.

    Pillow's ICNS writer packs PNG streams in pure Python, so this works on
    every platform with no ``iconutil`` and no macOS.
    """
    usable = {px: img for px, img in images.items() if px >= 16}
    if not usable:
        raise ValueError("no images to write into an .icns")
    largest = max(usable)
    base = usable[largest].convert("RGBA")
    appended = [img.convert("RGBA") for px, img in sorted(usable.items()) if px != largest]
    buf = io.BytesIO()
    base.save(buf, "ICNS", append_images=appended)
    return buf.getvalue()


def build_ico(images: dict[int, Image.Image]) -> bytes:
    sizes = sorted(images)
    largest = images[max(sizes)].convert("RGBA")
    buf = io.BytesIO()
    largest.save(
        buf, "ICO", sizes=[(s, s) for s in sizes],
        append_images=[images[s].convert("RGBA") for s in sizes if s != max(sizes)],
    )
    return buf.getvalue()


# iOS masks its icons with a superellipse; a rounded rectangle at this radius is
# the standard approximation and is what every mockup uses.
IOS_CORNER_RADIUS = 0.2237


def rounded_mask(size: int, radius_fraction: float = IOS_CORNER_RADIUS) -> Image.Image:
    """An L-mode mask with the corner radius a device applies, supersampled."""
    from PIL import ImageDraw

    scale = 4
    mask = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size * scale - 1, size * scale - 1),
        radius=int(size * scale * radius_fraction), fill=255,
    )
    return mask.resize((size, size), Image.LANCZOS)


def macos_tile_mask(px: int) -> Image.Image:
    """An L-mode mask of the rounded 824/1024 macOS tile centered on a ``px`` canvas."""
    tile = max(1, int(round(px * MACOS_SAFE_AREA)))
    mask = Image.new("L", (px, px), 0)
    mask.paste(rounded_mask(tile), ((px - tile) // 2, (px - tile) // 2))
    return mask


def clip_macos_tile(canvas: Image.Image) -> Image.Image:
    """Bake the macOS tile shape into a composed RGBA icon.

    Everything outside the rounded tile becomes transparent, so full-bleed
    artwork gets the platform's corners instead of covering them.
    """
    from PIL import ImageChops

    canvas = canvas.convert("RGBA")
    canvas.putalpha(ImageChops.multiply(canvas.getchannel("A"), macos_tile_mask(canvas.width)))
    return canvas


def device_icon(art: Image.Image, size: int, background: str = "#FFFFFF") -> Image.Image:
    """The icon as a device draws it: opaque, full bleed, corners masked."""
    spec = IconImage("", size, 1.0, True)
    flat = compose(art, spec, background).convert("RGBA")
    flat.putalpha(rounded_mask(size))
    return flat


def readme(platforms: Iterable[str]) -> str:
    names = ", ".join(platforms)
    return (
        f"App icons.\nPlatforms: {names}\n\n"
        "ios/AppIcon.appiconset drops straight into an Xcode asset catalog.\n"
        "android/ mirrors a res/ directory: copy mipmap-* and values/ into your module.\n"
        "  Adaptive layers are a 108dp canvas at every density with the artwork inside\n"
        "  the inner 72dp, which is the area no launcher mask crops.\n"
        "web/ files belong at the site root; head-snippet.html shows the tags.\n"
        "Every size is an independent render of the source wherever the source is vector.\n"
    )
