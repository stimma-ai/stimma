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


def _preview_paths(run: dict) -> dict[str, str]:
    root = run.get("root") or ""
    out: dict[str, str] = {}
    for entry in run.get("files") or []:
        path = entry["path"]
        if path.startswith(f"{root}previews/"):
            out[path.rsplit("/", 1)[-1][:-4]] = path
    return out


_ROW = 'display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:center;gap:{gap}px'


def _pair(previews: dict[str, str], key: str, *, width: str, gap: int) -> str:
    """A light and a dark rendering side by side, each captioned."""
    cells = "".join(
        f'<stimma-media ref="{kit.escape(previews[f"{key}-{mode}"])}" caption="{mode.title()}"'
        f' style="width:{width};text-align:center"></stimma-media>'
        for mode in ("light", "dark")
    )
    return f'<div style="{_ROW.format(gap=gap)}">{cells}</div>'


def present(run: dict, manifest: dict) -> str:
    """Show the icon where it will be seen, from the rendered previews the package ships."""
    by_px = _by_px(run)
    previews = _preview_paths(run)
    if not by_px:
        return ""

    def have(key: str) -> bool:
        return f"{key}-light" in previews and f"{key}-dark" in previews

    out: list[str] = []
    if have("home"):
        out.append(kit.section(_pair(previews, "home", width="min(320px,44vw)", gap=40), label="On a home screen"))

    swatches = [kit.media(by_px[px], size=px) for px in PREVIEW_SIZES if px in by_px]
    if swatches:
        out.append(kit.section(kit.sizes(swatches), label="At actual size"))

    surfaces = [k for k in ("app-store", "settings", "notification", "spotlight") if have(k)]
    if surfaces:
        rows = "".join(_pair(previews, k, width="min(390px,46vw)", gap=24) for k in surfaces)
        out.append(kit.section(f'<div style="display:grid;gap:28px">{rows}</div>',
                               label="Everywhere else it appears"))

    included = [
        PLATFORM_BLURB.get(key, (key.title(), ""))
        for key in (run.get("params") or {}).get("platforms") or []
    ]
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
        Param("background", type="color", default=None,
              description="Canvas behind the mark where a platform forbids transparency (iOS, the Play Store icon, the Apple touch icon), and the Android adaptive background layer. Required when the master is transparent: it is the person's decision, made before packaging"),
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

`background` is required when the master is transparent, because iOS forbids
alpha and something has to go behind the mark. It is not yours to invent: it is
the person's decision, made before packaging. If they have not made it, stop
and ask. The useful way to ask is to show it — put the mark on three or four
candidate grounds (a white, a near-black, one or two drawn from the artwork's
own palette that the mark is not made of), show them side by side, and let the
person pick. Then package with the one they chose. The build refuses a canvas
the mark disappears into, so a bad pick comes back as a reason, not a file.

If the icon wants a coloured or illustrated ground rather than a flat one, that
is design and belongs in the master — make the artwork, then package the
artwork.

Supply `android_foreground` when the mark needs to sit differently inside
Android's mask — the adaptive foreground is cropped to a circle-ish safe zone,
so a wide lockup that works on iOS loses its edges there.

An SVG master is worth more than a raster: every size is drawn at that size
rather than resampled.""",
)
async def build(b: Build) -> None:
    platforms = b.params.platforms
    fg_role = "android_foreground" if b.has("android_foreground") else "master"

    # iOS forbids alpha, so a transparent mark needs a canvas behind it. What
    # that canvas is, is a decision — and packaging does not make decisions, it
    # applies them. A missing one is a gap, and a gap is refused so the person
    # gets asked rather than surprised.
    master = b.input("master")
    ink = icon_spec.ink_color(await b.image("master", size=256))
    background = b.params.background
    if master.has_alpha and not background:
        suggested = icon_spec.neutral_ground(ink)
        b.fail(
            "the master is transparent, so a canvas has to go behind it where iOS forbids "
            "alpha, and that is a decision nobody has made. Ask which background the icon "
            "should sit on — show the mark on a few candidates and let the person pick — "
            f"then pass it as background. A neutral that would read is {suggested}."
        )
    if not background:
        background = "#FFFFFF"  # an opaque master never shows it; something must be written

    if master.has_alpha and not b.params.allow_low_contrast and ink is not None:
        ratio = icon_spec.contrast_ratio(ink, icon_spec.parse_hex(background))
        if ratio < icon_spec.MIN_ICON_CONTRAST:
            b.fail(
                f"the artwork and the chosen background are the same tone "
                f"(contrast {ratio:.2f}:1, needs {icon_spec.MIN_ICON_CONTRAST:.2f}). "
                f"The mark averages #{'%02X%02X%02X' % ink} and the background is "
                f"{background}, so the icon reads as a solid square. Pick one much darker "
                f"or lighter than the mark, or pass allow_low_contrast=true if the flat "
                f"look is deliberate."
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

    # Presentation images, shipped with the deliverable: the icon on a home
    # screen and on the other surfaces it has to survive, in both appearances.
    # A designer would build these in a mockup kit; here they come from the
    # same artwork, so they are never out of date.
    from packages import mockups

    device = icon_spec.device_icon(await b.image("master", size=1024), 1024, background)
    name = b.params.app_name if b.params.app_name and b.params.app_name != "App" else b.slug.replace("-", " ").title()
    for mode in ("light", "dark"):
        b.derive(f"previews/home-{mode}.png",
                 icon_spec.png_bytes(mockups.render_iphone(device, name, mode=mode, scale=2.0)),
                 source="master", fixed=True)
        b.derive(f"previews/app-store-{mode}.png",
                 icon_spec.png_bytes(mockups.render_app_store_row(device, name, "Productivity", mode=mode)),
                 source="master", fixed=True)
        b.derive(f"previews/settings-{mode}.png",
                 icon_spec.png_bytes(mockups.render_settings_row(device, name, mode=mode)),
                 source="master", fixed=True)
        b.derive(f"previews/notification-{mode}.png",
                 icon_spec.png_bytes(mockups.render_notification(device, name, "Your weekly summary is ready.", mode=mode)),
                 source="master", fixed=True)
        b.derive(f"previews/spotlight-{mode}.png",
                 icon_spec.png_bytes(mockups.render_spotlight_row(device, name, mode=mode)),
                 source="master", fixed=True)

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
