"""App icon sets from one square master.

Every platform rule lives in ``icon_spec``, which the SVG export reads too, so
the two producers cannot drift. This recipe's job is to ask for artwork at each
size the spec names and write the files where each platform expects them.
"""

from __future__ import annotations

import icon_spec
from packages import kit
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


def present(run: dict, manifest: dict) -> str:
    """Show the icon the way it will be seen: on a home screen, and at real size.

    Built from kit components, so this reads like every other Stimma cover and
    picks up any change to the look without being touched.
    """
    by_px = _by_px(run)
    if not by_px:
        return ""
    hero_ref = by_px[max(by_px)]
    app_name = (run.get("params") or {}).get("app_name") or ""
    if not app_name or app_name == "App":
        title = manifest.get("title") or ""
        app_name = title.split()[0] if title else "App"

    swatches = [kit.media(by_px[px], size=px) for px in PREVIEW_SIZES if px in by_px]
    included = [
        PLATFORM_BLURB.get(key, (key.title(), ""))
        for key in (run.get("params") or {}).get("platforms") or []
    ]

    out = [kit.section(kit.device_pair(hero_ref, app_name), label="On a home screen")]
    if swatches:
        out.append(kit.section(kit.sizes(swatches), label="At actual size"))
    out.append(kit.section(kit.contexts_markup(hero_ref, app_name), label="Everywhere else it appears"))
    if included:
        out.append(kit.section(kit.columns(included), label="Included"))
    return "".join(out)


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
        Param("allow_low_contrast", type="boolean", default=False,
              description="Build even when the artwork barely separates from the background. Only for a deliberately tonal icon"),
        Param("naming", type="naming", fields=["slug", "size", "platform"],
              default="{slug}-{platform}-{size}",
              description="Template for free filenames; platform-fixed names are exempt"),
    ],
    present=present,
    guidance="""\
The master does the work: a square mark that still reads at 20px. Thin strokes
and fine detail disappear at the small end — check the actual-size row before
calling it done, and simplify the mark rather than the sizes.

`background` is the icon's own canvas — composited behind the artwork wherever
a platform forbids transparency (iOS, the Play Store icon, the Apple touch
icon) and used as the Android adaptive background layer. Its job is to make
the mark read, so it must contrast with the mark, never echo it: a warm mark
on a warm ground is a solid square at 29px. Reach for a deep tone or a near
white, or a colour from the artwork that the mark is not made of. The build
measures this and refuses a canvas the mark disappears into. The cover then
shows the result on a light and a dark home screen; check both before
settling.

Supply `android_foreground` when the mark needs to sit differently inside
Android's mask — the adaptive foreground is cropped to a circle-ish safe zone,
so a wide lockup that works on iOS loses its edges there.

An SVG master is worth more than a raster: every size is drawn at that size
rather than resampled.""",
)
async def build(b: Build) -> None:
    platforms = b.params.platforms
    background = b.params.background
    fg_role = "android_foreground" if b.has("android_foreground") else "master"

    # The canvas exists to make the mark readable. Choosing it from the
    # artwork's own hue is the easy mistake — an orange sun on an orange
    # ground is invisible — and it is cheap to measure rather than warn about.
    if not b.params.allow_low_contrast:
        ink = icon_spec.ink_color(await b.image("master", size=256))
        if ink is not None:
            ratio = icon_spec.contrast_ratio(ink, icon_spec.parse_hex(background))
            if ratio < icon_spec.MIN_ICON_CONTRAST:
                b.fail(
                    f"the artwork and the background are the same tone "
                    f"(contrast {ratio:.2f}:1, needs {icon_spec.MIN_ICON_CONTRAST:.2f}). "
                    f"The mark averages #{'%02X%02X%02X' % ink} and the background is "
                    f"{background}, so the icon reads as a solid square. Pick a canvas "
                    f"much darker or much lighter than the mark — not another shade of it. "
                    f"Pass allow_low_contrast=true if the flat look is deliberate."
                )

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
