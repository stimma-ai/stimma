"""App icon output checked against the platform rules, transcribed from vendor docs.

The tables live here independently of the producers, so a typo or a dropped
size fails a test instead of reaching someone's app submission. Every rule runs
against *both* producers — the ``app-icons`` recipe and the SVG export — so the
two cannot drift apart again. These checks are what you can do without building
an app; ``xcrun actool`` on a Mac is the step beyond them.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from packages.recipes import ResolvedInput, describe_file, get_recipe, run_recipe
import icon_spec
from packages.manifest import sha256_file

# Apple: every (idiom, size, scale) an iOS AppIcon set is expected to carry.
# Transcribed from the asset catalog format, not from the recipe.
APPLE_IOS_ENTRIES = {
    ("iphone", "20x20", "2x"), ("iphone", "20x20", "3x"),
    ("iphone", "29x29", "2x"), ("iphone", "29x29", "3x"),
    ("iphone", "40x40", "2x"), ("iphone", "40x40", "3x"),
    ("iphone", "60x60", "2x"), ("iphone", "60x60", "3x"),
    ("ipad", "20x20", "1x"), ("ipad", "20x20", "2x"),
    ("ipad", "29x29", "1x"), ("ipad", "29x29", "2x"),
    ("ipad", "40x40", "1x"), ("ipad", "40x40", "2x"),
    ("ipad", "76x76", "2x"), ("ipad", "83.5x83.5", "2x"),
    ("ios-marketing", "1024x1024", "1x"),
}

# Android: launcher px per density bucket, and the adaptive layer canvas.
# Both adaptive layers are 108dp at every density; the launcher icon is 48dp.
ANDROID_LAUNCHER_PX = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
ANDROID_ADAPTIVE_PX = {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}


def _master(path: Path, size: int = 1200) -> Path:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((size * 0.1, size * 0.1, size * 0.9, size * 0.9), fill=(20, 120, 200, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")
    return path


def _resolved(role: str, path: Path) -> ResolvedInput:
    return ResolvedInput(role=role, path=path, hash=sha256_file(path), **describe_file(path))


async def _from_recipe(tmp_path: Path) -> Path:
    """The app-icons recipe, writing one tree with a folder per platform."""
    out = tmp_path / "recipe"
    await run_recipe(
        get_recipe("app-icons"),
        {"master": _resolved("master", _master(tmp_path / "master.png"))},
        {"background": "#FFFFFF", "platforms": list(icon_spec.PLATFORMS), "app_name": "Acme"},
        out,
        slug="acme",
    )
    return out


async def _from_svg_export(tmp_path: Path, monkeypatch) -> Path:
    """The SVG export, one target at a time, unpacked into the same layout.

    The renderer is stubbed because it needs the app's browser engine; what is
    under test is which files each target contains and how they are composed,
    not how a circle gets drawn.
    """
    import io as _io
    import zipfile

    from routes import svg_media

    async def fake_rasterize(svg_text, width, height, *, safe_area=1.0, opaque=False, background="#ffffff"):
        art = Image.new("RGBA", (max(1, round(width * safe_area)), max(1, round(height * safe_area))),
                        (20, 120, 200, 255))
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        canvas.paste(art, ((width - art.width) // 2, (height - art.height) // 2), art)
        if opaque:
            flat = Image.new("RGBA", (width, height), background)
            flat.alpha_composite(canvas)
            return flat.convert("RGB")
        return canvas

    monkeypatch.setattr(svg_media, "_rasterize", fake_rasterize)
    out = tmp_path / "svg"
    for fmt, target in svg_media.ICON_TARGETS.items():
        platform = target["platform"]
        payload, filename, _mt = await svg_media._build_icon_bundle("<svg/>", fmt, "Acme", "#FFFFFF")
        dest = out / platform
        dest.mkdir(parents=True, exist_ok=True)
        if filename.endswith(".zip"):
            with zipfile.ZipFile(_io.BytesIO(payload)) as zf:
                zf.extractall(dest)
        else:
            # macOS and Windows hand back a bare container; name it the way the
            # recipe does so one set of assertions covers both.
            suffix = Path(filename).suffix
            (dest / f"acme-{platform}{suffix}").write_bytes(payload)
    return out


@pytest.fixture(params=["recipe", "svg-export"])
async def icons(request, tmp_path, monkeypatch):
    """One icon tree per producer, in the same shape, for the same assertions."""
    if request.param == "recipe":
        return await _from_recipe(tmp_path)
    return await _from_svg_export(tmp_path, monkeypatch)


@pytest.mark.asyncio
async def test_ios_catalog_covers_every_apple_entry(icons):
    catalog = json.loads((icons / "ios/AppIcon.appiconset/Contents.json").read_text())
    present = {(e["idiom"], e["size"], e["scale"]) for e in catalog["images"]}
    assert present == APPLE_IOS_ENTRIES


@pytest.mark.asyncio
async def test_ios_files_exist_at_exactly_size_times_scale(icons):
    catalog = json.loads((icons / "ios/AppIcon.appiconset/Contents.json").read_text())
    for entry in catalog["images"]:
        assert "filename" in entry, f"{entry} has no file"
        path = icons / "ios/AppIcon.appiconset" / entry["filename"]
        assert path.is_file(), f"{entry['filename']} missing"
        want = round(float(entry["size"].split("x")[0]) * float(entry["scale"].rstrip("x")))
        with Image.open(path) as img:
            assert img.size == (want, want), f"{entry['filename']} is {img.size}, want {want}"


@pytest.mark.asyncio
async def test_app_store_icon_has_no_alpha(icons):
    """Apple rejects an App Store icon that carries an alpha channel."""
    store = icons / "ios/AppIcon.appiconset/icon-1024.png"
    with Image.open(store) as img:
        assert img.size == (1024, 1024)
        assert "A" not in img.mode and "transparency" not in img.info


@pytest.mark.asyncio
async def test_play_store_icon_is_512_and_opaque(icons):
    with Image.open(icons / "android/play-store-512.png") as img:
        assert img.size == (512, 512)
        assert "A" not in img.mode and "transparency" not in img.info


@pytest.mark.asyncio
async def test_android_adaptive_foreground_is_a_108dp_canvas(icons):
    """Both adaptive layers are 108dp at every density, not the launcher size.

    Shipping the foreground at the launcher size makes the system scale it up
    and pushes artwork into the ring the launcher mask crops.
    """
    for density, launcher_px in ANDROID_LAUNCHER_PX.items():
        with Image.open(icons / f"android/mipmap-{density}/ic_launcher.png") as legacy:
            assert legacy.size == (launcher_px, launcher_px)
        with Image.open(icons / f"android/mipmap-{density}/ic_launcher_foreground.png") as fg:
            want = ANDROID_ADAPTIVE_PX[density]
            assert fg.size == (want, want), f"{density} foreground is {fg.size}, want {want}"


@pytest.mark.asyncio
async def test_android_resources_resolve(icons):
    """Every resource ic_launcher.xml points at has to exist."""
    root = ET.fromstring((icons / "android/mipmap-anydpi-v26/ic_launcher.xml").read_text())
    ns = "{http://schemas.android.com/apk/res/android}"
    refs = {child.tag: child.attrib[f"{ns}drawable"] for child in root}
    assert refs["foreground"] == "@mipmap/ic_launcher_foreground"
    assert refs["background"] == "@color/ic_launcher_background"
    colors = ET.fromstring((icons / "android/values/ic_launcher_background.xml").read_text())
    assert {c.attrib["name"] for c in colors} == {"ic_launcher_background"}
    for density in ANDROID_LAUNCHER_PX:
        assert (icons / f"android/mipmap-{density}/ic_launcher_foreground.png").is_file()


@pytest.mark.asyncio
async def test_containers_carry_the_expected_sizes(icons):
    with Image.open(icons / "windows/acme-windows.ico") as ico:
        assert {s[0] for s in ico.info["sizes"]} >= {16, 24, 32, 48, 64, 128, 256}
    with Image.open(icons / "web/favicon.ico") as fav:
        assert {s[0] for s in fav.info["sizes"]} == {16, 32, 48}
    with Image.open(icons / "macos/acme-macos.icns") as icns:
        assert icns.size[0] >= 512


@pytest.mark.asyncio
async def test_web_manifest_points_at_files_that_exist(icons):
    manifest = json.loads((icons / "web/site.webmanifest").read_text())
    assert manifest["name"] == "Acme"
    for entry in manifest["icons"]:
        # Manifest srcs are site-root absolute; the files ship beside it.
        assert (icons / "web" / Path(entry["src"]).name).is_file()
        px = int(entry["sizes"].split("x")[0])
        with Image.open(icons / "web" / Path(entry["src"]).name) as img:
            assert img.size == (px, px)


# Vector masters --------------------------------------------------------------

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512">' \
      '<circle cx="256" cy="256" r="240" fill="#0a84ff"/></svg>'


@pytest.mark.asyncio
async def test_vector_master_is_rendered_natively_at_every_size(tmp_path):
    """A vector is drawn at each output size, never resampled from one render."""
    svg = tmp_path / "mark.svg"
    svg.write_text(SVG)
    asked: list[int] = []

    async def renderer(given: ResolvedInput, size: int) -> bytes:
        asked.append(size)
        import io

        img = Image.new("RGBA", (size, size), (10, 132, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    out = tmp_path / "out"
    await run_recipe(
        get_recipe("app-icons"),
        {"master": _resolved("master", svg)},
        {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["ios"]},
        out,
        slug="acme",
        renderer=renderer,
    )
    catalog = json.loads((out / "ios/AppIcon.appiconset/Contents.json").read_text())
    wanted = {round(float(e["size"].split("x")[0]) * float(e["scale"].rstrip("x"))) for e in catalog["images"]}
    assert wanted <= set(asked), f"sizes never rendered natively: {sorted(wanted - set(asked))}"


@pytest.mark.asyncio
async def test_non_square_vector_is_rejected_like_a_non_square_raster(tmp_path):
    """Shape constraints have to apply to vectors too, or a wide logo silently letterboxes."""
    from packages.recipes import RecipeError

    svg = tmp_path / "wide.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="300" height="80"><rect width="300" height="80"/></svg>')
    with pytest.raises(RecipeError, match="square"):
        await run_recipe(get_recipe("app-icons"), {"master": _resolved("master", svg)}, {}, tmp_path / "o")


@pytest.mark.asyncio
async def test_a_missing_app_name_is_refused_not_invented(tmp_path):
    """The name under the icon is the person's. A slug is not a name.

    The previews print it on a home screen and in a store row, and the web
    manifest carries it, so a guess would ship in the deliverable. The build
    stops with a reason that tells the agent to ask.
    """
    from packages.recipes import RecipeError

    out = tmp_path / "o"
    with pytest.raises(RecipeError, match="app_name") as info:
        await run_recipe(
            get_recipe("app-icons"), {"master": _resolved("master", _master(tmp_path / "master.png"))},
            {"background": "#FFFFFF", "platforms": ["ios"]}, out, slug="sunburst-app-icon",
        )
    assert "Ask" in str(info.value)
    assert not (out / "previews").exists()


@pytest.mark.asyncio
async def test_vector_without_a_renderer_says_so(tmp_path):
    from packages.recipes import RecipeError

    svg = tmp_path / "mark.svg"
    svg.write_text(SVG)
    with pytest.raises(RecipeError, match="renderer"):
        await run_recipe(
            get_recipe("app-icons"), {"master": _resolved("master", svg)},
            {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["web"]}, tmp_path / "o",
        )


# Presentation ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_cover_does_not_instruct_or_editorialize(tmp_path):
    """The page must not claim affordances it lacks or admire its own work.

    A cover that says "drag this into Xcode" is describing a gesture the page
    cannot offer, and a line explaining why the output is good is the sound of
    a machine talking to itself.
    """
    from packages.cover import render_cover_document
    from packages.manifest import new_manifest

    out = tmp_path / "out"
    result = await run_recipe(
        get_recipe("app-icons"),
        {"master": _resolved("master", _master(tmp_path / "master.png"))},
        {"background": "#FFFFFF", "platforms": ["ios"], "app_name": "Sunburst"},
        out,
        slug="sunburst",
    )
    manifest = new_manifest(title="Sunburst iOS icon")
    manifest["runs"] = [{
        "id": "r1",
        "recipe": {"id": "app-icons", "version": 2, "display_name": "App icon set"},
        "inputs": {}, "params": result.params, "root": "app-icons/",
        "files": [{"path": "app-icons/" + f.path, "hash": f.hash, "size": f.size} for f in result.files],
    }]
    html, problems = render_cover_document(manifest)
    assert not problems
    # Only what a reader sees: the manifest the kit reads is data, not prose.
    visible = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    visible = re.sub(r"<[^>]+>", " ", visible).lower()
    for phrase in ("drag ", "drop appicon", "click here", "simply ", "its own render"):
        assert phrase not in visible, f"cover says {phrase!r}"
    for jargon in ("recipe run", "member", "cache_key", "stimmapackage"):
        assert jargon not in visible, f"cover leaks {jargon!r}"


@pytest.mark.asyncio
async def test_file_downloads_never_navigate(tmp_path):
    """Every file link forces a download.

    Without download=1 the browser renders what it can — a JSON or a PNG opens
    in place of the cover, which inside the frame looks like the page broke.
    """
    from packages.cover import render_cover_document
    from packages.manifest import new_manifest

    out = tmp_path / "out"
    result = await run_recipe(
        get_recipe("app-icons"),
        {"master": _resolved("master", _master(tmp_path / "master.png"))},
        {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["ios"]}, out, slug="sunburst",
    )
    manifest = new_manifest(title="Icons")
    manifest["runs"] = [{
        "id": "r1", "recipe": {"id": "app-icons", "version": 2, "display_name": "App icon set"},
        "inputs": {}, "params": result.params, "root": "app-icons/",
        "files": [{"path": "app-icons/" + f.path, "hash": f.hash, "size": f.size} for f in result.files],
    }]
    html, _ = render_cover_document(manifest)
    hrefs = re.findall(r'<a class="sp-dl" href="([^"]+)"', html)
    assert hrefs, "no per-file download links"
    assert all("download=1" in href for href in hrefs)
    # The archive is the app's to offer, from its own header; the page only
    # opens into its contents.
    assert "app-icons.zip?download=1" not in html
    assert "View contents" in html


@pytest.mark.asyncio
async def test_previews_ship_with_the_run(tmp_path):
    """The run carries rendered mockups as real files, for the agent's cover.

    A recipe is a formula: it makes files, and says in its guidance what they
    are for. The cover is the agent's to design from them.
    """
    out = tmp_path / "out"
    result = await run_recipe(
        get_recipe("app-icons"),
        {"master": _resolved("master", _master(tmp_path / "master.png"))},
        {"background": "#FFFFFF", "platforms": ["ios", "android"], "app_name": "Sunburst"}, out, slug="sunburst",
    )
    shipped = {f.path for f in result.files}
    for name in ("previews/home-light.png", "previews/home-dark.png", "previews/app-store-light.png",
                 "previews/settings-dark.png", "previews/notification-light.png", "previews/spotlight-dark.png",
                 "previews/device-studio.png", "previews/device-lifestyle.png"):
        assert name in shipped, f"{name} not shipped"
    with Image.open(out / "previews/device-lifestyle.png") as image:
        assert image.size == (3840, 2560)
    for platform in ('ios', 'android'):
        for kind in ('store', 'notification'):
            for mode in ('light', 'dark'):
                name = f'previews/{platform}-{kind}-{mode}.png'
                assert name in shipped
                with Image.open(out / name) as image:
                    assert image.size == (1440, 300)
    spec = get_recipe("app-icons")
    assert not hasattr(spec, "present"), "recipes are formulas; the cover is the agent's"
    assert "previews/" in spec.guidance and 'slot="details"' in spec.guidance


def test_the_file_tree_is_one_shared_component():
    """Every surface that lists package files uses the same component."""
    from packages import cover, kit

    assert hasattr(kit, "_files_markup"), "the tree lives in the kit"
    assert not hasattr(cover, "_files_markup"), "the cover must not carry a second copy"
    assert "stimma-files" in kit.COMPONENTS


@pytest.mark.asyncio
async def test_a_canvas_the_mark_disappears_into_is_refused(tmp_path):
    """An orange mark on an orange ground is a solid square at 29px.

    This is measurable, so the recipe measures it rather than leaving it to
    whoever picks the colour — which is how a sunburst ended up invisible on
    its own hue.
    """
    from packages.recipes import RecipeError

    master = _master(tmp_path / "master.png")
    inputs = {"master": _resolved("master", master)}

    with pytest.raises(RecipeError, match="same tone"):
        await run_recipe(get_recipe("app-icons"), inputs,
                         {"platforms": ["web"], "background": "#1E7BC8", "app_name": "Acme"}, tmp_path / "clash")

    # Left unset on a transparent master, it is a gap, and gaps are refused
    # rather than filled: the person gets asked.
    with pytest.raises(RecipeError, match="decision"):
        await run_recipe(get_recipe("app-icons"), inputs, {"platforms": ["web"], "app_name": "Acme"}, tmp_path / "gap")

    # A deep ground and a near-white both separate it, and the flat look is
    # still reachable on purpose.
    await run_recipe(get_recipe("app-icons"), inputs,
                     {"platforms": ["web"], "background": "#0B1B2B", "app_name": "Acme"}, tmp_path / "deep")
    await run_recipe(get_recipe("app-icons"), inputs,
                     {"platforms": ["web"], "background": "#1E7BC8", "allow_low_contrast": True, "app_name": "Acme"},
                     tmp_path / "deliberate")


def test_a_suggested_neutral_always_reads():
    """The refusal suggests a neutral; the suggestion has to be one that works."""
    import icon_spec

    assert icon_spec.neutral_ground((18, 18, 20)) == icon_spec.NEUTRAL_LIGHT      # dark mark
    assert icon_spec.neutral_ground((250, 250, 250)) == icon_spec.NEUTRAL_DARK    # light mark
    assert icon_spec.neutral_ground((243, 164, 30)) == icon_spec.NEUTRAL_DARK     # a bright brand orange
    assert icon_spec.neutral_ground(None) == icon_spec.NEUTRAL_LIGHT              # nothing to read
    for ink in ((18, 18, 20), (250, 250, 250), (243, 164, 30)):
        ground = icon_spec.parse_hex(icon_spec.neutral_ground(ink))
        assert icon_spec.contrast_ratio(ink, ground) >= icon_spec.MIN_ICON_CONTRAST

@pytest.mark.asyncio
async def test_mixed_pack_includes_linux_hicolor_icons(tmp_path):
    tree = await _from_recipe(tmp_path)
    assert {p.name for p in tree.iterdir() if p.is_dir()} >= {"ios", "android", "macos", "windows", "linux"}
    for px in (16, 24, 32, 48, 64, 128, 256, 512):
        with Image.open(tree / f"linux/hicolor/{px}x{px}/apps/acme.png") as img:
            assert img.size == (px, px)
            assert img.mode == "RGBA"
            assert img.getpixel((0, 0))[3] == 0
    assert not (tree / "linux/hicolor/index.theme").exists()
    assert "Icon=acme" in (tree / "README.txt").read_text()


def test_icon_composition_preserves_translucent_artwork():
    art = Image.new("RGBA", (16, 16), (240, 120, 20, 128))
    transparent = icon_spec.compose(art, icon_spec.IconImage("icon.png", 16, 1.0, False))
    assert transparent.getpixel((8, 8)) == (240, 120, 20, 128)
    opaque = icon_spec.compose(art, icon_spec.IconImage("icon.png", 16, 1.0, True), "#FFFFFF")
    assert opaque.getpixel((8, 8)) == (247, 187, 137)


@pytest.mark.asyncio
@pytest.mark.parametrize('background', [None, '#FFF8F0'])
async def test_fully_opaque_rgba_master_does_not_need_a_transparency_background(tmp_path, background):
    # Image editors often retain an alpha channel after compositing onto a
    # background. Its presence does not make the artwork transparent.
    source = tmp_path / 'opaque.png'
    image = Image.new('RGBA', (1024, 1024), (255, 248, 240, 255))
    ImageDraw.Draw(image).ellipse((420, 420, 604, 604), fill=(180, 75, 0, 255))
    image.save(source)
    params = {'app_name': 'Example', 'platforms': ['ios']}
    if background is not None:
        params['background'] = background
    await run_recipe(get_recipe('app-icons'), {'master': _resolved('master', source)}, params, tmp_path / 'out')
    output = Image.open(tmp_path / 'out/ios/AppIcon.appiconset/icon-1024.png')
    assert output.convert('RGB').getpixel((0, 0)) == (255, 248, 240)


@pytest.mark.asyncio
async def test_platform_scale_changes_only_requested_exports_and_previews(tmp_path):
    from PIL import ImageChops
    source = _resolved('master', _master(tmp_path / 'master.png'))
    params = {'background': '#FFFFFF', 'app_name': 'Example', 'platforms': ['windows', 'linux']}
    results = []
    for name, scale in [('normal', 1.0), ('smaller', .8)]:
        result = await run_recipe(get_recipe('app-icons'), {'master': source},
                                 {**params, 'windows_scale': scale}, tmp_path / name, slug='example')
        assert result.params['windows_scale'] == scale
        results.append({f.path: f.hash for f in result.files})
    changed = {path for path in results[0] if results[0][path] != results[1][path]}
    assert 'windows/icon-256.png' in changed
    assert 'previews/platform-windows-start.png' in changed
    assert 'previews/platform-windows-taskbar.png' in changed
    assert not any(path.startswith('linux/') or 'platform-linux' in path for path in changed)
    a = Image.open(tmp_path / 'normal/windows/icon-256.png').convert('RGBA')
    b = Image.open(tmp_path / 'smaller/windows/icon-256.png').convert('RGBA')
    assert ImageChops.difference(a, b).getbbox()


async def test_web_study_uses_delivered_favicon_pixels(tmp_path):
    result = await run_recipe(get_recipe('app-icons'),
        {'master': _resolved('master', _master(tmp_path / 'master.png'))},
        {'platforms': ['web'], 'app_name': 'Example', 'background': '#FFFFFF'},
        tmp_path / 'web-study')
    paths = {f.path for f in result.files}
    assert {p for p in paths if p.startswith('previews/')} == {
        'previews/platform-web-light.png', 'previews/platform-web-dark.png'}
    icon = Image.open(tmp_path / 'web-study/web/icon-16.png').convert('RGBA')
    for mode, ground in [('light', '#ffffff'), ('dark', '#35363a')]:
        image = Image.open(tmp_path / f'web-study/previews/platform-web-{mode}.png')
        assert image.size == (1440, 320)
        expected = Image.new('RGB', (16, 16), ground)
        expected.paste(icon, (0, 0), icon.getchannel('A'))
        expected = expected.resize((32, 32), Image.Resampling.NEAREST)
        assert image.crop((56, 38, 88, 70)).tobytes() == expected.tobytes()
