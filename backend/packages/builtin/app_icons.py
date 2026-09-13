"""App icon sets from one square master.

Every platform rule lives in ``icon_spec``, which the SVG export reads too, so
the two producers cannot drift. This recipe's job is to ask for artwork at each
size the spec names and write the files where each platform expects them.
"""

from __future__ import annotations

import html as htmllib

import icon_spec
from packages.recipes import Build, Input, Param, recipe

# Sizes worth showing at their true scale: the ones that decide whether a mark
# survives. A designer checks the small end first.
PREVIEW_SIZES = (180, 120, 87, 60, 40, 29, 20)

# What each folder holds, in the recipient's words. No instructions: the page
# has no affordance behind a "drag this into Xcode", so it does not say one.
PLATFORM_BLURB = {
    "ios": ("iPhone and iPad", "An Xcode asset catalog, every size with its Contents.json."),
    "android": ("Android", "Launcher icons per density, adaptive layers, and the Play Store icon."),
    "macos": ("macOS", "An .icns, and every size as a PNG."),
    "windows": ("Windows", "A multi-resolution .ico, 16 through 256."),
    "web": ("Web", "Favicons, an Apple touch icon, a manifest, and the head tags."),
}


def _by_px(run: dict) -> dict[int, str]:
    """Bundle paths of the iOS renders, keyed by pixel size."""
    root = run.get("root") or ""
    found: dict[int, str] = {}
    for entry in run.get("files") or []:
        path = entry["path"]
        name = path.rsplit("/", 1)[-1]
        if not path.startswith(f"{root}ios/AppIcon.appiconset/") or not name.startswith("icon-"):
            continue
        try:
            found[int(name[5:-4])] = path
        except ValueError:
            continue
    return found


# Tints for the placeholder apps around ours, so the mockup reads as a home
# screen rather than a wireframe of grey boxes.
_NEIGHBOURS = (
    "rgba(255,255,255,.18)", "rgba(120,180,255,.30)", "rgba(255,190,120,.26)",
    "rgba(150,230,190,.26)", "rgba(220,150,235,.24)", "rgba(255,255,255,.13)",
    "rgba(255,150,150,.24)", "rgba(160,190,255,.22)", "rgba(255,255,255,.20)",
    "rgba(200,235,150,.24)", "rgba(255,255,255,.15)",
)


def _home_screen(hero: str, app_name: str) -> str:
    """A believable springboard: status bar, a grid of apps, a dock."""
    cells = [
        f'<div class="sp-app sp-mine"><img src="{hero}" alt=""><em>{htmllib.escape(app_name)}</em></div>'
    ]
    for tint in _NEIGHBOURS:
        cells.append(f'<div class="sp-app"><i style="background:{tint}"></i><em></em></div>')
    status = (
        '<div class="sp-statusbar"><span>9:41</span>'
        '<span style="display:flex;align-items:center;gap:4px">'
        '<span class="sp-bars"><i style="height:3px"></i><i style="height:5px"></i>'
        '<i style="height:7px"></i><i style="height:9px"></i></span>'
        '<span class="sp-batt"></span></span></div>'
    )
    dock = '<div class="sp-dock">' + "<i></i>" * 4 + "</div>"
    return (
        f'<div class="sp-phone"><div class="sp-screen">{status}'
        f'<div class="sp-apps">{"".join(cells)}</div>{dock}</div></div>'
    )


def present(run: dict, manifest: dict) -> str:
    """Show the icon the way it will be seen: on a home screen, and at real size."""
    by_px = _by_px(run)
    if not by_px:
        return ""
    hero = htmllib.escape(by_px[max(by_px)], quote=True)
    app_name = (run.get("params") or {}).get("app_name") or ""
    if not app_name or app_name == "App":
        app_name = (manifest.get("title") or "").split()[0] if manifest.get("title") else "App"
    platforms = (run.get("params") or {}).get("platforms") or []

    swatches = []
    for px in PREVIEW_SIZES:
        path = by_px.get(px)
        if not path:
            continue
        src = htmllib.escape(path, quote=True)
        swatches.append(
            f'<div class="sp-size"><img src="{src}" width="{px}" height="{px}" alt="{px} pixels">'
            f'<span>{px}</span></div>'
        )

    cards = []
    for key in platforms:
        name, blurb = PLATFORM_BLURB.get(key, (key.title(), ""))
        cards.append(
            f'<div class="sp-platform"><h3>{htmllib.escape(name)}</h3>'
            f'<p>{htmllib.escape(blurb)}</p></div>'
        )

    return (
        '<div class="sp-hero">'
        f'<div class="sp-hero-icon"><img src="{hero}" alt=""></div>'
        f'{_home_screen(hero, app_name)}</div>'
        '<div class="sp-section"><p class="sp-label">At actual size</p>'
        f'<div class="sp-sizes">{"".join(swatches)}</div></div>'
        + (f'<div class="sp-section"><p class="sp-label">Included</p>'
           f'<div class="sp-platforms">{"".join(cards)}</div></div>' if cards else "")
    )


@recipe(
    id="app-icons",
    version=2,
    display_name="App icon set",
    description="iOS, Android, macOS, Windows and web icon sets from one square master image",
    inputs=[
        Input("master", kind="image", square=True, min_size=1024,
              description="Square master icon: an SVG, or a raster 1024px or larger"),
        Input("android_foreground", kind="image", required=False, alpha=True, square=True,
              description="Optional transparent foreground layer for Android adaptive icons"),
    ],
    params=[
        Param("platforms", type="multi", options=list(icon_spec.PLATFORMS),
              default=["ios", "android", "web"], description="Which platform sets to produce"),
        Param("background", type="color", default="#FFFFFF",
              description="Background baked in where a platform forbids transparency (iOS, the Play Store icon, Apple touch icon) and used as the Android adaptive background layer"),
        Param("app_name", type="string", default="App", description="Name used in the web manifest"),
        Param("naming", type="naming", fields=["slug", "size", "platform"],
              default="{slug}-{platform}-{size}",
              description="Template for free filenames; platform-fixed names are exempt"),
    ],
    present=present,
)
async def build(b: Build) -> None:
    platforms = b.params.platforms
    background = b.params.background
    fg_role = "android_foreground" if b.has("android_foreground") else "master"

    async def composed(spec: icon_spec.IconImage):
        # Vector artwork is drawn at this exact size; a raster is resampled.
        art = await b.image(spec.role if spec.role != "master" else "master", size=spec.px)
        return icon_spec.compose(art, spec, background)

    for platform in platforms:
        rendered: dict[int, object] = {}
        for spec in icon_spec.images_for(platform, foreground_role=fg_role):
            img = await composed(spec)
            rendered[spec.px] = img
            if platform == "macos":
                continue  # written below, named by the user's template
            b.derive(f"{platform}/{spec.path}", icon_spec.png_bytes(img),
                     source=spec.role, fixed=True)

        if platform == "ios":
            b.file("ios/AppIcon.appiconset/Contents.json", icon_spec.ios_contents_json())

        elif platform == "android":
            b.file("android/mipmap-anydpi-v26/ic_launcher.xml", icon_spec.ANDROID_ADAPTIVE_XML)
            b.file("android/values/ic_launcher_background.xml",
                   icon_spec.android_background_xml(background))

        elif platform == "macos":
            b.derive("macos/" + b.name(ext="icns", slug=b.slug, platform="macos", size=""),
                     icon_spec.build_icns(rendered), source="master")
            for spec in icon_spec.macos_images():
                b.derive("macos/" + b.name(ext="png", slug=b.slug, platform="macos", size=spec.px),
                         icon_spec.png_bytes(rendered[spec.px]), source="master")

        elif platform == "windows":
            b.derive("windows/" + b.name(ext="ico", slug=b.slug, platform="windows", size=""),
                     icon_spec.build_ico(rendered), source="master")

        elif platform == "web":
            b.derive("web/favicon.ico",
                     icon_spec.build_ico({px: rendered[px] for px in icon_spec.WEB_ICO_SIZES}),
                     source="master", fixed=True)
            b.file("web/site.webmanifest", icon_spec.web_manifest(b.params.app_name))
            b.file("web/head-snippet.html", icon_spec.WEB_HEAD_SNIPPET)

    b.file("README.txt", icon_spec.readme(platforms))

    # The package's face: the icon the way a device draws it, on a plate.
    # Better than anything computed from the file list afterwards, because the
    # recipe knows this is an app icon and knows how one is meant to look.
    b.tile(_tile_png(await b.image("master", size=1024), background))


def _tile_png(art, background: str) -> bytes:
    """A 640px plate with the masked icon centered and a soft drop shadow."""
    from PIL import Image, ImageFilter

    size, icon_px = 640, 416
    icon = icon_spec.device_icon(art, icon_px, background)
    plate = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    left = top = (size - icon_px) // 2

    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 90), (left, top + icon_px // 24), icon_spec.rounded_mask(icon_px))
    plate.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(icon_px // 22)))
    plate.alpha_composite(icon, (left, top))
    return icon_spec.png_bytes(plate)
