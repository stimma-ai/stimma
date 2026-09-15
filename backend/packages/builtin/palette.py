"""Serialize a chosen palette; neither extract nor choose colors."""
from __future__ import annotations

import json
import re

from packages.recipes import Build, Input, Param, recipe


def contrast(a: str, b: str) -> float:
    def luminance(color):
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    low, high = sorted((luminance(a), luminance(b)))
    return (high + 0.05) / (low + 0.05)


@recipe(
    id="palette-exports", version=1, display_name="Palette exports",
    description="Chosen colors and usage roles as JSON, CSS variables and a readable reference with optional pair contrast checks",
    inputs=[Input("palette", kind="file", description="JSON with colors [{name,hex,role?}] and optional pairs [{foreground,background}]")],
    params=[Param("naming", type="naming", fields=["slug", "kind"], default="{slug}-{kind}")],
    guidance="""Prepare a UTF-8 JSON member: {"colors":[{"name":"ink","hex":"#172334","role":"Body text"},
{"name":"paper","hex":"#F5F7FA","role":"Background"}],"pairs":[{"foreground":"ink","background":"paper"}]}.
Names must be unique lowercase kebab-case CSS identifiers. Roles are optional human-readable
usage notes. Pairs refer to color names. Select colors and pairings creatively before this run.
This recipe writes JSON, CSS variables and a text reference; it never chooses colors or authors
HTML. Contrast results describe only the supplied pair, not overall accessibility or print color
accuracy. Values are sRGB; no inferred CMYK/Pantone equivalents. Present the palette with the
cover kit's swatches and show actual applications. A package may contain multiple palette runs
for alternatives; identify which are candidates or selected, without inferring approval.""",
)
def build(b: Build) -> None:
    try:
        palette = json.loads(b.text("palette"))
    except (ValueError, UnicodeError):
        b.fail("palette must be valid UTF-8 JSON")
    if not isinstance(palette, dict) or not isinstance(palette.get("colors"), list) or not 1 <= len(palette["colors"]) <= 32:
        b.fail("palette needs a colors list containing 1–32 named colors")
    colors = []
    by_name = {}
    for color in palette["colors"]:
        if not isinstance(color, dict):
            b.fail("Each color needs name and hex fields")
        name, value, role = color.get("name"), color.get("hex"), color.get("role", "")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name) or name in by_name:
            b.fail("Color names must be unique lowercase kebab-case identifiers, such as primary or body-text")
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value) or not isinstance(role, str):
            b.fail("Each color needs a six-digit #RRGGBB hex value and an optional text role")
        entry = {"name": name, "hex": value.upper(), "role": role}
        colors.append(entry)
        by_name[name] = entry
    pairs = palette.get("pairs", [])
    if not isinstance(pairs, list) or len(pairs) > 128:
        b.fail("pairs must be a list of up to 128 foreground/background name pairs")
    checks = []
    for pair in pairs:
        if not isinstance(pair, dict) or not isinstance(pair.get("foreground"), str) or not isinstance(pair.get("background"), str):
            b.fail("Each pair needs foreground and background color names")
        fg, bg = pair["foreground"], pair["background"]
        if fg not in by_name or bg not in by_name:
            b.fail("Pair foreground and background must name colors in this palette")
        ratio = contrast(by_name[fg]["hex"], by_name[bg]["hex"])
        checks.append({"foreground": fg, "background": bg, "ratio": round(ratio, 4), "normal_text_aa": ratio >= 4.5, "large_text_aa": ratio >= 3})
    output = {"color_space": "sRGB", "colors": colors, "pairs": checks}
    b.derive(b.name(ext="json", slug=b.slug, kind="palette"), json.dumps(output, indent=2, ensure_ascii=False) + "\n", source="palette")
    css = ":root {\n" + "".join(f"  --{c['name']}: {c['hex']};\n" for c in colors) + "}\n"
    b.derive(b.name(ext="css", slug=b.slug, kind="palette"), css, source="palette")
    lines = ["Palette — sRGB", ""] + [f"{c['name']}: {c['hex']}" + (f" — {c['role']}" if c['role'] else "") for c in colors]
    if checks:
        lines += ["", "Text/background pair checks (WCAG AA contrast only):"]
        lines += [f"{c['foreground']} on {c['background']}: {c['ratio']:.4f}:1; normal text {'passes' if c['normal_text_aa'] else 'fails'}, large text {'passes' if c['large_text_aa'] else 'fails'}" for c in checks]
    lines += ["", "These checks do not certify a complete design. Inspect real text size and weight.", "Print appearance depends on the printer and stock; no CMYK or spot-color match is implied."]
    b.derive(b.name(ext="txt", slug=b.slug, kind="palette"), "\n".join(lines) + "\n", source="palette")
