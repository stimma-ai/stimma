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
# Legacy launcher icon px per density, and the adaptive-icon layer canvas.
# Both adaptive layers are 108dp regardless of density, with the artwork living
# in the inner 72dp — the system masks everything outside it, so shipping the
# foreground at the launcher size (the mistake that is easy to make here) both
# softens it and pushes art into the masked ring.
ANDROID_DENSITIES = [("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)]
ADAPTIVE_DP = 108
LAUNCHER_DP = 48
ADAPTIVE_SAFE_FRACTION = 72 / 108  # inner 72dp of the 108dp canvas
MACOS_SIZES = [16, 32, 64, 128, 256, 512, 1024]
WINDOWS_SIZES = [16, 24, 32, 48, 64, 128, 256]
WEB_SIZES = [16, 32, 48, 180, 192, 512]


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
        Input("master", kind="image", square=True, min_size=1024,
              description="Square master icon: an SVG, or a raster 1024px or larger"),
        Input("android_foreground", kind="image", required=False, alpha=True, square=True,
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
async def build(b: Build) -> None:
    platforms = b.params.platforms
    background = b.params.background
    slug = b.slug

    async def art(role: str, px: int):
        """Artwork for one output size, drawn at that size when it can be."""
        return await b.image(role, size=px)

    if "ios" in platforms:
        name_for: dict[int, str] = {}
        for *_rest, px in IOS_ENTRIES:
            if px in name_for:
                continue
            name = f"icon-{px}.png"
            name_for[px] = name
            b.derive(f"ios/AppIcon.appiconset/{name}",
                     png_bytes(fit_square(await art("master", px), px, background=background)),
                     source="master", fixed=True)
        b.file("ios/AppIcon.appiconset/Contents.json", _contents_json(name_for))
        b.derive("ios/" + b.name(ext="png", slug=slug, platform="appstore", size=1024),
                 png_bytes(flatten(fit_square(await art("master", 1024), 1024), background)), source="master")

    if "android" in platforms:
        fg_role = "android_foreground" if b.has("android_foreground") else "master"
        for density, px in ANDROID_DENSITIES:
            b.derive(f"android/mipmap-{density}/ic_launcher.png",
                     png_bytes(fit_square(await art("master", px), px, background=background)),
                     source="master", fixed=True)
            # Adaptive layers are 108dp at every density, with the art inside
            # the inner 72dp so no launcher mask can clip it.
            layer_px = round(px * ADAPTIVE_DP / LAUNCHER_DP)
            b.derive(f"android/mipmap-{density}/ic_launcher_foreground.png",
                     png_bytes(fit_square(await art(fg_role, layer_px), layer_px,
                                          safe_area=ADAPTIVE_SAFE_FRACTION)),
                     source=fg_role, fixed=True)
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
                 png_bytes(flatten(fit_square(await art("master", 512), 512), background)), source="master")

    if "macos" in platforms:
        macos = {px: fit_square(await art("master", px), px, safe_area=0.82) for px in MACOS_SIZES}
        b.derive("macos/" + b.name(ext="icns", slug=slug, platform="macos", size=""),
                 _icns({px: img for px, img in macos.items() if px >= 32}), source="master")
        for px in MACOS_SIZES:
            b.derive("macos/" + b.name(ext="png", slug=slug, platform="macos", size=px),
                     png_bytes(macos[px]), source="master")

    if "windows" in platforms:
        images = {px: fit_square(await art("master", px), px) for px in WINDOWS_SIZES}
        b.derive("windows/" + b.name(ext="ico", slug=slug, platform="windows", size=""), _ico(images), source="master")

    if "web" in platforms:
        web = {px: fit_square(await art("master", px), px) for px in sorted(set(WEB_SIZES))}
        b.derive("web/favicon.ico", _ico({px: web[px] for px in (16, 32, 48)}), source="master", fixed=True)
        for px in (16, 32, 192, 512):
            b.derive(f"web/icon-{px}.png", png_bytes(web[px]), source="master", fixed=True)
        b.derive("web/apple-touch-icon.png", png_bytes(flatten(web[180], background)),
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
