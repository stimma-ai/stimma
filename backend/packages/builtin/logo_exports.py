"""Export prepared identity artwork without making new design decisions."""
from __future__ import annotations

import base64
import re

from PIL import Image

from packages.recipes import Build, Input, Param, png_bytes, recipe


def _pdf(data: bytes, width: int, height: int) -> bytes:
    from weasyprint import HTML, default_url_fetcher

    def local_only(url, **kwargs):
        if not url.startswith("data:"):
            raise ValueError("Logo PDF resources must be embedded in the SVG")
        return default_url_fetcher(url, **kwargs)

    encoded = base64.b64encode(data).decode("ascii")
    return HTML(string=(
        f'<style>@page{{size:{width}px {height}px;margin:0}}'
        'html,body{margin:0;padding:0;font-size:0}img{display:block;width:100%;height:100%}</style>'
        f'<img src="data:image/svg+xml;base64,{encoded}">'
    ), url_fetcher=local_only).write_pdf()


@recipe(
    id="logo-exports", version=1, display_name="Logo exports",
    description="Export one prepared logo treatment: original master, proportionate PNGs, and vector-source PDF",
    inputs=[Input("artwork", kind="image", description="One prepared mark, wordmark, or lockup; SVG or raster")],
    params=[
        Param("variant", default="primary", description="Descriptive label, including direction/treatment when needed"),
        Param("png_sizes", default="256,512,1024,2048", description="Comma-separated longest edges in pixels (16–8192); raster sources are never enlarged"),
        Param("pdf", type="boolean", default=True, description="Include a PDF for SVG input; raster sources retain their original format"),
        Param("naming", type="naming", fields=["slug", "variant", "size"], default="{slug}-{variant}-{size}"),
    ],
    guidance="""Use for prepared brand artwork, including candidates. Each run exports exactly the supplied
treatment; it does not recolor, compose lockups, remove a background, or make avatars.
Choose and inspect those changes before packaging. Use separate runs for independent
directions or treatments, and state their decision status on the authored cover.
png_sizes specifies LONGEST EDGE, preserving wide and tall artwork. Raster output never
exceeds its source resolution; an opaque source stays opaque. SVG originals are copied
byte for byte. PDF retains vector paths but embedded raster imagery stays raster.
Prepare portable SVGs: embed images, outline logo lettering or use available fonts,
and inspect PDF/PNG output. A generic logo PDF is not a PDF/X print-ready layout.
The original/ folder preserves the input; png/ contains exports; vector PDF is in pdf/.
README.txt reports actual outputs. Author the package cover independently with Packaging
and Brand Kits guidance; app icons, if requested, are a separate run from the same master.""",
)
async def build(b: Build) -> None:
    raw = b.params.png_sizes
    if not isinstance(raw, str) or not re.fullmatch(r"\s*\d+(?:\s*,\s*\d+)*\s*", raw):
        b.fail("png_sizes must be comma-separated integer longest edges, for example 256,512,1024")
    sizes = sorted(set(int(s.strip()) for s in raw.split(",")))
    if len(sizes) > 12 or any(s < 16 or s > 8192 for s in sizes):
        b.fail("Choose up to 12 PNG longest edges, each between 16 and 8192 pixels")
    source = b.input("artwork")
    data = source.path.read_bytes()
    fields = {"slug": b.slug, "variant": b.params.variant}
    original = b.derive("original/" + b.name(ext=source.path.suffix.lstrip("."), **fields), data, source="artwork")
    lines = ["Logo exports", "", f"Original master: {original}", "Artwork and color treatment preserved as supplied.", "", "PNG files (width × height):"]
    produced = set()
    for size in sizes:
        img = await b.image("artwork", size=size)
        actual = min(size, max(img.size))
        if actual in produced:
            continue
        produced.add(actual)
        img.thumbnail((actual, actual), Image.Resampling.LANCZOS)
        path = b.derive("png/" + b.name(ext="png", size=actual, **fields), png_bytes(img), source="artwork")
        lines.append(f"{path}: {img.width} × {img.height} px")
    if source.kind == "vector" and b.params.pdf:
        pdf = _pdf(data, max(source.width, 1), max(source.height, 1))
        path = b.derive("pdf/" + b.name(ext="pdf", **fields), pdf, source="artwork")
        lines.extend(["", f"Vector-source PDF: {path}", "Embedded raster images remain raster. This is artwork, not a printer-specific production layout."])
    elif source.kind != "vector":
        lines.extend(["", "Raster source: no vector master or vector PDF has been invented. PNG exports are capped at source resolution."])
    lines.extend(["", "Use PNG when your editor asks for an image. Use SVG for scalable artwork where supported.", "Transparent artwork stays transparent; existing backgrounds are retained.", "See the package guide for direction status, intended backgrounds, and usage decisions."])
    b.file("README.txt", "\n".join(lines) + "\n")
