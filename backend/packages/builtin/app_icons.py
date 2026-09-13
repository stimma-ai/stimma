"""App icon sets from one square master.

Every platform disagrees about safe areas and alpha, and getting that wrong is
what makes an icon look amateur. The tables here match the vector icon export
in ``routes/svg_media.py`` so the two never drift.
"""

from __future__ import annotations

import io
import json

from PIL import Image

from packages.recipes import Build, Input, Param, fit_square, flatten, png_bytes, recipe

IOS_ENTRIES = [
    ("iphone", "20x20", "2x", 40), ("iphone", "20x20", "3x", 60),
    ("iphone", "29x29", "2x", 58), ("iphone", "29x29", "3x", 87),
    ("iphone", "40x40", "2x", 80), ("iphone", "40x40", "3x", 120),
    ("iphone", "60x60", "2x", 120), ("iphone", "60x60", "3x", 180),
    ("ipad", "20x20", "1x", 20), ("ipad", "20x20", "2x", 40),
    ("ipad", "29x29", "1x", 29), ("ipad", "29x29", "2x", 58),
    ("ipad", "40x40", "1x", 40), ("ipad", "40x40", "2x", 80),
    ("ipad", "76x76", "2x", 152), ("ipad", "83.5x83.5", "2x", 167),
    ("ios-marketing", "1024x1024", "1x", 1024),
]
ANDROID_DENSITIES = [("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)]
MACOS_SIZES = [16, 32, 64, 128, 256, 512, 1024]
WINDOWS_SIZES = [16, 24, 32, 48, 64, 128, 256]
WEB_SIZES = [16, 32, 48, 180, 192, 512]
RASTER_SIZES = (1024, 512, 256)


def _icns(images: dict[int, Image.Image]) -> bytes:
    largest = images[max(images)].convert("RGBA")
    appended = [img.convert("RGBA") for size, img in sorted(images.items()) if size != max(images)]
    buf = io.BytesIO()
    largest.save(buf, "ICNS", append_images=appended)
    return buf.getvalue()


def _ico(images: dict[int, Image.Image]) -> bytes:
    sizes = sorted(images)
    largest = images[max(sizes)].convert("RGBA")
    buf = io.BytesIO()
    largest.save(buf, "ICO", sizes=[(s, s) for s in sizes],
                 append_images=[images[s].convert("RGBA") for s in sizes if s != max(sizes)])
    return buf.getvalue()


def _contents_json(name_for: dict[int, str]) -> str:
    images = []
    for idiom, size, scale, px in IOS_ENTRIES:
        entry = {"idiom": idiom, "size": size, "scale": scale}
        if px in name_for:
            entry["filename"] = name_for[px]
        images.append(entry)
    return json.dumps({"images": images, "info": {"version": 1, "author": "stimma"}}, indent=2) + "\n"


@recipe(
    id="app-icons",
    version=1,
    display_name="App icon set",
    description="iOS, Android, macOS, Windows and web icon sets from one square master image",
    inputs=[
        Input("master", kind="image", square=True, min_size=1024, raster=RASTER_SIZES,
              description="Square master icon, 1024px or larger (PNG or SVG)"),
        Input("android_foreground", kind="image", required=False, alpha=True, raster=RASTER_SIZES,
              description="Optional transparent foreground layer for Android adaptive icons"),
    ],
    params=[
        Param("platforms", type="multi", options=["ios", "android", "macos", "windows", "web"],
              default=["ios", "android", "web"], description="Which platform sets to produce"),
        Param("background", type="color", default="#FFFFFF",
              description="Background behind the artwork where a platform forbids transparency (iOS) or needs a layer color (Android)"),
        Param("app_name", type="string", default="App", description="Name used in the web manifest"),
        Param("naming", type="naming", fields=["slug", "size", "platform"], default="{slug}-{platform}-{size}",
              description="Template for free filenames; platform-fixed names are exempt"),
    ],
)
def build(b: Build) -> None:
    master = b.image("master", size=1024)
    platforms = b.params.platforms
    background = b.params.background
    slug = b.slug

    if "ios" in platforms:
        name_for: dict[int, str] = {}
        for *_rest, px in IOS_ENTRIES:
            if px in name_for:
                continue
            name = f"icon-{px}.png"
            name_for[px] = name
            b.derive(f"ios/AppIcon.appiconset/{name}", png_bytes(fit_square(master, px, background=background)),
                     source="master", fixed=True)
        b.file("ios/AppIcon.appiconset/Contents.json", _contents_json(name_for))
        b.derive("ios/" + b.name(ext="png", slug=slug, platform="appstore", size=1024),
                 png_bytes(flatten(fit_square(master, 1024), background)), source="master")

    if "android" in platforms:
        fg_role = "android_foreground" if b.has("android_foreground") else "master"
        fg = b.image(fg_role, size=1024)
        for density, px in ANDROID_DENSITIES:
            b.derive(f"android/mipmap-{density}/ic_launcher.png",
                     png_bytes(fit_square(master, px, background=background)), source="master", fixed=True)
            b.derive(f"android/mipmap-{density}/ic_launcher_foreground.png",
                     png_bytes(fit_square(fg, px, safe_area=0.66)), source=fg_role, fixed=True)
        b.file("android/mipmap-anydpi-v26/ic_launcher.xml", (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
            '    <background android:drawable="@color/ic_launcher_background"/>\n'
            '    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>\n'
            '</adaptive-icon>\n'
        ))
        b.file("android/values/ic_launcher_background.xml", (
            '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
            f'    <color name="ic_launcher_background">{background}</color>\n</resources>\n'
        ))
        b.derive("android/" + b.name(ext="png", slug=slug, platform="playstore", size=512),
                 png_bytes(flatten(fit_square(master, 512), background)), source="master")

    if "macos" in platforms:
        images = {px: fit_square(master, px, safe_area=0.82) for px in MACOS_SIZES if px >= 32}
        b.derive("macos/" + b.name(ext="icns", slug=slug, platform="macos", size=""), _icns(images), source="master")
        for px in MACOS_SIZES:
            b.derive("macos/" + b.name(ext="png", slug=slug, platform="macos", size=px),
                     png_bytes(fit_square(master, px, safe_area=0.82)), source="master")

    if "windows" in platforms:
        images = {px: fit_square(master, px) for px in WINDOWS_SIZES}
        b.derive("windows/" + b.name(ext="ico", slug=slug, platform="windows", size=""), _ico(images), source="master")

    if "web" in platforms:
        b.derive("web/favicon.ico", _ico({s: fit_square(master, s) for s in (16, 32, 48)}), source="master", fixed=True)
        for px in (16, 32, 192, 512):
            b.derive(f"web/icon-{px}.png", png_bytes(fit_square(master, px)), source="master", fixed=True)
        b.derive("web/apple-touch-icon.png", png_bytes(flatten(fit_square(master, 180), background)),
                 source="master", fixed=True)
        b.file("web/site.webmanifest", json.dumps({
            "name": b.params.app_name, "short_name": b.params.app_name,
            "icons": [
                {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
            ],
        }, indent=2) + "\n")
        b.file("web/head-snippet.html", (
            '<link rel="icon" href="/favicon.ico" sizes="any">\n'
            '<link rel="icon" type="image/png" sizes="32x32" href="/icon-32.png">\n'
            '<link rel="icon" type="image/png" sizes="16x16" href="/icon-16.png">\n'
            '<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">\n'
            '<link rel="manifest" href="/site.webmanifest">\n'
        ))

    b.file("README.txt", (
        "App icons generated by Stimma.\n"
        f"Platforms: {', '.join(platforms)}\n"
        "ios/AppIcon.appiconset drops straight into an Xcode asset catalog.\n"
        "android/ mirrors a res/ directory: copy mipmap-* and values/ into your module.\n"
        "web/ files are meant to sit at the site root; head-snippet.html shows the tags.\n"
    ))
