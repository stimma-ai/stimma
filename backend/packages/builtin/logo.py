"""Logo delivery: every variant, in every color treatment, in the formats people ask for.

Vector masters stay vector (the SVG is copied through untouched and a PDF is
written from it when a converter is available). Raster renditions come from
the pre-rendered sizes the framework provides for vector inputs, or from the
raster master itself.
"""

from __future__ import annotations

import shutil
import subprocess

from PIL import Image

from packages.recipes import Build, Input, Param, flatten, png_bytes, recipe

VARIANTS = ("primary", "mark", "wordmark", "stacked")
PNG_WIDTHS = (2048, 1024, 512, 256)
AVATAR_SIZES = {"social-avatar": 800, "social-avatar-small": 400}


def _svg_to_pdf(svg_path, out_path) -> bool:
    """Best effort SVG -> PDF using rsvg-convert when present. Returns True on success."""
    exe = shutil.which("rsvg-convert")
    if not exe:
        return False
    try:
        subprocess.run([exe, "-f", "pdf", "-o", str(out_path), str(svg_path)], check=True, timeout=60,
                       capture_output=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def _one_color(img: Image.Image, rgb: tuple[int, int, int]) -> Image.Image:
    """Recolor every opaque pixel to ``rgb``, preserving alpha."""
    img = img.convert("RGBA")
    alpha = img.getchannel("A")
    solid = Image.new("RGBA", img.size, rgb + (0,))
    solid.putalpha(alpha)
    return solid


def _fit_width(img: Image.Image, width: int) -> Image.Image:
    if img.width == 0:
        return img
    ratio = width / img.width
    return img.resize((width, max(1, int(round(img.height * ratio)))), Image.LANCZOS)


def _avatar(img: Image.Image, size: int, background: str) -> Image.Image:
    art = img.convert("RGBA").copy()
    art.thumbnail((int(size * 0.7), int(size * 0.7)), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), background)
    canvas.paste(art, ((size - art.width) // 2, (size - art.height) // 2), art)
    return canvas.convert("RGB")


@recipe(
    id="logo",
    version=1,
    display_name="Logo kit",
    description="Logo variants in full color, one-color black and reversed, as SVG/PDF/PNG plus social avatars",
    inputs=[
        Input("primary", kind="image", description="Primary lockup on a transparent background"),
        Input("mark", kind="image", required=False, description="Icon mark alone"),
        Input("wordmark", kind="image", required=False, description="Wordmark alone"),
        Input("stacked", kind="image", required=False, description="Stacked or secondary lockup"),
    ],
    params=[
        Param("black", type="color", default="#111111", description="Ink for the one-color treatment"),
        Param("reversed_background", type="color", default="#111111",
              description="Background baked behind the reversed (white) PNGs so they are visible in a file browser"),
        Param("avatar_background", type="color", default=None,
              description="Ground for the social avatars. Unset derives a neutral from the mark's own tone; set it only when someone asked for a colour"),
        Param("png_widths", type="multi", options=[str(w) for w in PNG_WIDTHS], default=["2048", "1024", "512"],
              description="PNG widths to write per variant and color"),
        Param("naming", type="naming", fields=["slug", "variant", "color", "size"],
              default="{slug}-logo-{variant}-{color}-{size}", description="Template for every free filename"),
    ],
)
async def build(b: Build) -> None:
    slug = b.slug
    widths = [int(w) for w in b.params.png_widths]
    ink = b.params.black
    black_rgb = tuple(int(ink[i:i + 2], 16) for i in (1, 3, 5))

    for variant in VARIANTS:
        if not b.has(variant):
            continue
        given = b.input(variant)
        folder = variant
        # Vector: copy through and try a PDF.
        if given.kind == "vector":
            b.derive(f"{folder}/" + b.name(ext="svg", slug=slug, variant=variant, color="fullcolor"),
                     given.path.read_bytes(), source=variant)
            pdf_target = b.out_dir / "_tmp.pdf"
            if _svg_to_pdf(given.path, pdf_target):
                data = pdf_target.read_bytes()
                pdf_target.unlink(missing_ok=True)
                b.derive(f"{folder}/" + b.name(ext="pdf", slug=slug, variant=variant, color="fullcolor"), data, source=variant)
        master = await b.image(variant, size=max(widths))
        treatments: dict[str, Image.Image] = {
            "fullcolor": master,
            "black": _one_color(master, black_rgb),
            "reversed": _one_color(master, (255, 255, 255)),
        }
        for color, img in treatments.items():
            produced: set[int] = set()
            for width in widths:
                out = _fit_width(img, min(width, img.width))  # never upscale
                if out.width in produced:
                    continue
                produced.add(out.width)
                if color == "reversed":
                    out = flatten(out, b.params.reversed_background)
                b.derive(f"{folder}/png/" + b.name(ext="png", slug=slug, variant=variant, color=color, size=out.width),
                         png_bytes(out), source=variant)

    avatar_source = "mark" if b.has("mark") else "primary"
    avatar_img = await b.image(avatar_source, size=max(AVATAR_SIZES.values()))
    # An avatar is a square of solid colour with the mark on it, so the ground
    # decides whether the mark is visible at all. Derive a neutral from the
    # mark rather than assuming white: a reversed logo on white is nothing.
    import icon_spec

    avatar_ground = b.params.avatar_background or icon_spec.neutral_ground(icon_spec.ink_color(avatar_img))
    for label, size in AVATAR_SIZES.items():
        b.derive("social/" + b.name(ext="png", slug=slug, variant=label, color="", size=size),
                 png_bytes(_avatar(avatar_img, size, avatar_ground)), source=avatar_source)

    b.file("README.txt", (
        "Logo kit generated by Stimma.\n"
        "One folder per variant. Inside: SVG/PDF masters where the source was vector, and png/ renditions\n"
        "in full color, one-color black, and reversed (white on the chosen background).\n"
        "social/ holds square avatars with the mark centered on a solid background.\n"
    ))
