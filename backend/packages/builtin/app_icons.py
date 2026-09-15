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
    version=13,
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
        Param("artwork_fit", type="choice", options=["auto", "canvas"], default="auto",
              description="Auto measures transparent or uniform-background margins and fits the mark to each platform. Canvas preserves a deliberately composed full-bleed source. Inspect Platform Study before saving"),
        *[Param(f"{platform}_scale", type="number", default=1.0, minimum=0.1, maximum=2.0,
                description=f"Artwork scale for {platform} only, relative to its default fit: 0.9 makes the mark 10% smaller, 1.1 makes it 10% larger. Changes exports and previews together. Refuses scaling beyond the canvas or adaptive safe zone; does not change the platform canvas size")
          for platform in icon_spec.PLATFORMS],
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
parameter. Do not add another padded canvas. The recipe's default `artwork_fit="auto"`
measures transparent or uniform-background margins and fits the visible mark
for each platform. iOS uses a full-bleed opaque canvas, macOS adds its outer
margin once, Windows/Linux use the available transparent icon canvas, and the
Android foreground fits the guaranteed 66dp circle in its 108dp layer. The
optical fill of a mark is a default recipe policy; no one percentage fits all designs.
Use `artwork_fit="canvas"` only for intentionally composed full-bleed artwork
whose existing internal spacing must be retained. Inspect the cutout and the
resulting Platform Study before saving. Never enlarge only a preview to hide
an undersized exported icon.

For a requested size/padding adjustment, set ios_scale, android_scale,
macos_scale, windows_scale, linux_scale or web_scale on the run. Each is a
multiplier relative to that platform's normal fit (1.0): 0.9 is 10% smaller,
with more padding. Change only the requested platform. The renderer refuses
clipping or exceeding the Android safe zone; if enlargement is refused, explain
the limit instead of silently clipping. Re-run and inspect the exported icon
and its Platform Study. Do not edit only a preview or change the shared SVG
master to compensate for one platform. Keep the SVG as a reusable member.

Read `references/platform-study.md` in the Packaging skill for this recipe.
Read it through the skill's resource path supplied at activation, using the
normal read_file tool. Do not search the Python SDK or leave the workspace to
find templates. The recipe already supplies the context images as run files.

The following cover composition is a default, not a required design. Honor
requested colors, branding, grouping and emphasis; keep refs valid and show
the requested deliverables.
Group each OS in a sibling <stimma-section page label="Platform Study · OS">.
Use layout="pair" for iOS, Android and Linux, layout="stack" for Windows,
and layout="single" for macOS.
The kit makes responsive HTML and one landscape PDF page per OS from that group.
Use the current skill reference as a starting point. Custom CSS, including
@media print and @page, can adapt the shared cover to the requested design.
For each selected platform:
- iOS: `previews/device-studio.png` and `previews/device-lifestyle.png` (4K).
- Android: `previews/platform-android-studio.png` (large icon beside Galaxy phone)
  and `previews/platform-android.png` (4K Galaxy lifestyle scene, populated screen).
  Include both Android views in Platform Study.
- macOS: `previews/platform-macos.png` (Dock, dark capsule tooltip).
- Windows: BOTH `previews/platform-windows-start.png` and
  `previews/platform-windows-taskbar.png`.
- Linux: `previews/platform-linux.png` (Ubuntu Dock) and
  `previews/platform-linux-kde.png` (KDE Plasma panel), both at 2×.
  Show them side by side with Ubuntu and KDE Plasma captions.
These are built only for selected platforms, using the delivered files and app
name. They need no generation, upscaling, model, external tool, demo directory,
or manual compositing. Inspect them in the folder returned by pkg.preview().
Use the manifest's actual paths, including its run root, as stimma-media refs.
The authored cover includes every requested platform and every relevant run.
The cover is still your design; the recipe emits images, never HTML.

Start with `references/app-icons-mixed.html` for multiple platforms or
`references/app-icons.html` for iOS alone. Remove unused platform sections;
never omit requested ones. Show scenes wide, keep copy factual, and retain
a few actual-size samples of the delivered PNGs on the opening page.
Lead with ONE generous finished icon, not a grid of near-identical platform
variants. Use a high-resolution delivered icon, not an unprepared source mark.
Keep transparency rules and file-format explanations with the relevant platform
or contents. Background studies belong to brand-mark work, not this icon cover.
Default to a dark cover unless the person requests a different cover theme;
a requested icon background does not set the cover's background.
For Web, use previews/platform-web-light.png or previews/platform-web-dark.png
(browser tab with the delivered 16px favicon) and show web/icon-16.png and
web/icon-32.png at native size alongside it on a Platform Study · Web page.
The browser image is a 2x view; the separate native-size samples judge fidelity.
Do not use the older flat phone home-light/home-dark previews in the cover. For iOS and Android, put store and notification examples inside a native
<details slot="details"> with <summary>Details</summary>, initially closed.
Inside it use one stimma-appearance, with light and dark stimma-grid children
marked when="light" / when="dark". Use previews/{platform}-store-{mode}.png and
previews/{platform}-notification-{mode}.png, captioned App Store / Google Play
and Notification. The switch fades between variants. Follow the skill reference.
The kit omits this disclosure from the PDF, giving both phone scenes the full
OS slide. Do not add separate In iOS, Settings, Spotlight or detail pages.
The kit repeats the PDF footer on every slide.
End with stimma-files for the run.
Say what each folder is, in
the recipient's words: iOS is `AppIcon.appiconset`, ready for an Xcode asset
catalog, every iPhone and iPad size with its Contents.json. Android is
launcher icons for every density, the adaptive foreground and background
layers, and the 512px Play Store icon, laid out like a res/ folder. macOS is
an .icns for the app bundle plus every size as a PNG. Windows is one .ico
holding 16 through 256. Linux is PNGs preserving the master's alpha in hicolor/<size>/apps/
with one consistent application basename; install into the existing icon theme.
Web is favicon.ico, an Apple touch icon, a web
manifest and the <head> tags to paste in.
""",
)
async def build(b: Build) -> None:
    platforms = b.params.platforms
    if not platforms:
        b.fail("select at least one platform for the icon package")
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

    sample = await b.image("master", size=256)
    transparent = sample.getchannel("A").getextrema()[0] < 255
    ink = icon_spec.ink_color(sample)
    background = b.params.background
    if transparent and not background:
        suggested = icon_spec.neutral_ground(ink)
        b.fail(
            "the master is transparent, so a canvas has to go behind it where iOS forbids "
            "alpha, and that is a decision nobody has made. Ask which background the icon "
            "should sit on — show the mark on a few candidates and let the person pick — "
            f"then pass it as background. A neutral that would read is {suggested}."
        )
    if not background:
        background = "#FFFFFF"  # an opaque master never shows it; something must be written

    if transparent and not b.params.allow_low_contrast and ink is not None:
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

    from packages.mockups.icon_artwork import Artwork

    plans = {"master": Artwork.measure(await b.image("master", size=1024), b.params.artwork_fit)}
    if b.params.background is None and plans["master"].backdrop:
        background = plans["master"].backdrop
    if fg_role != "master":
        plans[fg_role] = Artwork.measure(await b.image(fg_role, size=1024), b.params.artwork_fit)

    async def composed(spec: icon_spec.IconImage, platform: str):
        # Render vectors with enough pixels for the measured crop; resample rasters.
        plan = plans[spec.role]
        art = await b.image(spec.role, size=plan.render_size(spec.px))
        return plan.compose(art, spec, platform, background, scale=getattr(b.params, f"{platform}_scale"))

    study_icons = {}
    store_icons = {}
    for platform in platforms:
        rendered: dict[int, object] = {}
        for spec in icon_spec.images_for(platform, foreground_role=fg_role):
            img = await composed(spec, platform)
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

        if platform == "android":
            study_icons[platform] = rendered[432]
            store_icons[platform] = rendered[512]
        else:
            study_icons[platform] = rendered[max(rendered)]

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
            from packages.mockups.web import browser_preview
            for mode in ('light', 'dark'):
                b.derive(f"previews/platform-web-{mode}.png",
                         icon_spec.png_bytes(browser_preview(rendered[16], name, mode=mode)),
                         source="master", fixed=True)

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
    from packages.mockups.platform_study import ASSETS as study_assets, platform_previews

    if any(p in platforms for p in ("ios", "android", "macos", "windows", "linux")):
        b.file("previews/ATTRIBUTION.txt", (study_assets / "README.md").read_text())
    if "linux" in platforms:
        b.file("previews/LICENSE-YARU.txt", (study_assets / "YARU-LICENSE.txt").read_text())
        b.file("previews/LICENSE-BREEZE.txt", (study_assets / "BREEZE-LICENSE.txt").read_text())
    for filename, image in platform_previews(study_icons, name, background):
        b.derive(f"previews/{filename}", icon_spec.png_bytes(image), source="master", fixed=True)
    device = study_icons.get("ios")
    if device is not None:
        from packages.mockups.devices import device_previews
        for filename, image in device_previews(device, name):
            b.derive(f"previews/{filename}", icon_spec.png_bytes(image), source="master", fixed=True)
    from packages.mockups.mobile_details import render_store, render_notification
    from packages.mockups.platform_study import android_icon
    for platform in ('ios', 'android'):
        if platform not in study_icons:
            continue
        icon = study_icons[platform]
        notification_icon = android_icon(icon, background) if platform == 'android' else icon
        store_icon = store_icons.get(platform, icon)
        for mode in ('light', 'dark'):
            for kind, image in (
                ('store', render_store(store_icon, name, platform, mode=mode)),
                ('notification', render_notification(notification_icon, name, platform, mode=mode)),
            ):
                b.derive(f'previews/{platform}-{kind}-{mode}.png', icon_spec.png_bytes(image), source='master', fixed=True)
    # Existing localized iOS context rows remain available only for iOS runs.
    if device is not None:
        for mode in ("light", "dark"):
            b.derive(f"previews/home-{mode}.png",
                     icon_spec.png_bytes(mockups.render_iphone(device, name, mode=mode, scale=2.0)),
                     source="master", fixed=True)
            b.derive(f"previews/app-store-{mode}.png",
                     icon_spec.png_bytes(render_store(device, name, "ios", mode=mode)),
                     source="master", fixed=True)
            b.derive(f"previews/settings-{mode}.png",
                     icon_spec.png_bytes(mockups.render_settings_row(device, name, mode=mode)),
                     source="master", fixed=True)
            b.derive(f"previews/notification-{mode}.png",
                     icon_spec.png_bytes(render_notification(device, name, "ios", mode=mode)),
                     source="master", fixed=True)
            b.derive(f"previews/spotlight-{mode}.png",
                     icon_spec.png_bytes(mockups.render_spotlight_row(device, name, mode=mode)),
                     source="master", fixed=True)

    # The package's face: the icon the way a device draws it, on a plate.
    # Better than anything computed from the file list afterwards, because the
    # recipe knows this is an app icon and knows how one is meant to look.
    b.tile(_tile_png(study_icons.get("ios") or study_icons[next(iter(study_icons))], background))


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
