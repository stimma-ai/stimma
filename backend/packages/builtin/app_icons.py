"""App icon sets from one square master.

Every platform rule lives in ``icon_spec``, which the SVG export reads too, so
the two producers cannot drift. This recipe's job is to ask for artwork at each
size the spec names and write the files where each platform expects them.
"""

from __future__ import annotations

import icon_spec
from packages.recipes import Build, Input, Param, recipe

@recipe(
    id="app-icons",
    version=3,
    display_name="App icon set",
    description="iOS, Android, macOS, Windows, Linux and web icon sets from one square master image",
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
        Param("app_name", type="string", default=None,
              description="What the app is called: the name under the icon on the home screen, in the store row, in Settings and notifications, and in the web manifest. Required: it is the person's to say, not yours to invent — ask if you do not know"),
        Param("allow_low_contrast", type="boolean", default=False,
              description="Build even when the artwork barely separates from the background. Only for a deliberately tonal icon"),
        Param("naming", type="naming", fields=["slug", "size", "platform"],
              default="{slug}-{platform}-{size}",
              description="Template for free filenames; platform-fixed names are exempt"),
    ],
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
so a wide lockup that works on iOS loses its edges there. Inspect that layer
over the chosen background: removing a backdrop must preserve the mark's
interior colors and opacity. A faded cutout is not an acceptable foreground.

`app_name` is required too, for the same reason. The previews put the name
under the icon on a home screen, in a store row, in Settings and in a
notification, and the web manifest carries it — so a made-up name ships in the
deliverable. If the person has not said what the app is called, ask before
building; do not derive one from a filename or a slug.

Use the supplied format when it meets the input constraints. SVG inputs are
rendered at each size; raster inputs are resampled. A raster master does not
need vectorization to be packaged.

`background` fills transparency; it does not recolor opaque pixels. If the
supplied master already has a different background, prepare that background
before running the recipe. Check the resulting iOS icon against the requested
color, not just the parameter value recorded in the manifest.
For removing a baked-in background, load Subject Isolation and use its
background-removal workflow. A square cutout of at least 1024px already meets
the master constraints: use that output directly, with the requested background
parameter. Keep its existing scale and placement unless the artwork needs an
adjustment; no extra canvas or separate Android foreground is required for the
same centered mark. Inspect the cutout before building.

The Packaging skill has recipe-specific starting points under its resource
directory. Read `references/app-icons.py` for an editable draft/preview/save
script to run with run_file after preparing the master. For an iOS-only cover,
read `references/app-icons.html`. For a mixed
platform pack, read `references/app-icons-mixed.html`. Use read_file.
Use the draft manifest to replace its run-root and run-id placeholders. Adapt
it for the whole package: a mixed pack should also show actual Android, macOS,
Windows and Linux outputs, with a file browser for every run. Keep captions
factual and short; do not add claims about polish, readability or readiness.

What the run gives the cover. `previews/` holds rendered mockups of the icon
in place — `home-light.png` / `home-dark.png` (a phone home screen),
`app-store-*`, `settings-*`, `notification-*`, `spotlight-*` — real files the
person can drop into a deck. Show the home screen large, one appearance at a
time behind `<stimma-appearance>`; put the iOS renders in a `<stimma-sizes>`
row at 180, 120, 87, 60, 40, 29 and 20 so the small end is judged at true
scale; end with `<stimma-files>` for the run. Say what each folder is, in
the recipient's words: iOS is `AppIcon.appiconset`, ready for an Xcode asset
catalog, every iPhone and iPad size with its Contents.json. Android is
launcher icons for every density, the adaptive foreground and background
layers, and the 512px Play Store icon, laid out like a res/ folder. macOS is
an .icns for the app bundle plus every size as a PNG. Windows is one .ico
holding 16 through 256. Linux is PNGs preserving the master's alpha in hicolor/<size>/apps/
with one consistent application basename; install into the existing icon theme.
Web is favicon.ico, an Apple touch icon, a web
manifest and the <head> tags to paste in.""",
)
async def build(b: Build) -> None:
    platforms = b.params.platforms
    fg_role = "android_foreground" if b.has("android_foreground") else "master"

    # iOS forbids alpha, so a transparent mark needs a canvas behind it. What
    # that canvas is, is a decision — and packaging does not make decisions, it
    # applies them. A missing one is a gap, and a gap is refused so the person
    # gets asked rather than surprised.
    # The name is the person's too. It is printed under the icon in every
    # preview and written into the web manifest, so a guess would ship.
    name = (b.params.app_name or "").strip()
    if not name:
        b.fail(
            "the app's name is not set, and the previews put it under the icon on a home "
            "screen, in a store row, in Settings and in a notification, and the web manifest "
            "carries it. Ask what the app is called, then pass it as app_name. Do not make "
            "one up from a filename."
        )

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
            path = spec.path
            if platform == "linux":
                # Same application name at every size: the theme lookup uses
                # the directory for size, and the basename for identity.
                path = f"hicolor/{spec.px}x{spec.px}/apps/{b.slug}.png"
            b.derive(f"{platform}/{path}", icon_spec.png_bytes(img),
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
            b.file("web/site.webmanifest", icon_spec.web_manifest(name))
            b.file("web/head-snippet.html", icon_spec.WEB_HEAD_SNIPPET)

    readme = icon_spec.readme(platforms)
    if "linux" in platforms:
        readme += (
            "\nLinux: copy the contents of linux/hicolor/ into the existing hicolor\n"
            "icon theme under your installation prefix's share/icons/ directory.\n"
            f"Use Icon={b.slug} (without extension) in your application's .desktop file.\n"
            "The PNGs preserve transparency. No executable or .desktop launcher is included.\n"
        )
    b.file("README.txt", readme)

    # Context previews, shipped with the deliverable: the icon on a home
    # screen and on the other surfaces it has to survive, in both appearances.
    # A designer would build these in a mockup kit; here they come from the
    # same artwork, so they are never out of date.
    from packages import mockups

    device = icon_spec.device_icon(await b.image("master", size=1024), 1024, background)
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
