"""
Demo STP provider for documentation screenshots.

Presents a small set of ComfyUI-style local tools that produce deterministic
procedural art instead of running real models. Used by the docs screenshot
harness (frontend/e2e/docs-shots) so tool-panel, queue, and post-processing
shots show realistic tools and pleasant images without any model weights,
GPU, or cloud spend.

Run via the stimma-tools-python sibling repo's environment:

    uv run --project ../stimma-tools-python python scripts/docs-shots/demo_provider.py --stdio

The docs-demo sandbox's config.yaml registers it as a stdio tool provider.
STIMMA_DEMO_DELAY (seconds per progress step, default 0.12) slows execution
down for in-progress screenshots; set to 0 for fast seeding.
"""

import asyncio
import io
import math
import os
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from stimma_tools_protocol import (
    Group,
    Param,
    Provider,
    ProviderConfig,
    ToolParameter,
    create_argument_parser,
    run_provider,
    setup_logging,
    tool,
)
from stimma_tools_protocol.provider import ExecutionContext

STEP_DELAY = float(os.environ.get("STIMMA_DEMO_DELAY", "0.12"))

# --- Procedural art -----------------------------------------------------------
# Deterministic from (prompt, seed): same inputs, same image. Looks like
# deliberate abstract art at both thumbnail and full size.

PALETTES = [
    ["#0d3b4f", "#11698e", "#19a7ce", "#f6f1e9", "#e8aa42"],  # harbor
    ["#1f1d36", "#3f3351", "#864879", "#e9a6a6", "#f9f5eb"],  # dusk
    ["#234d20", "#36802d", "#77ab59", "#c9df8a", "#f0f7da"],  # meadow
    ["#3d0000", "#950101", "#ff5733", "#ffba4a", "#fff5e4"],  # ember
    ["#27374d", "#526d82", "#9db2bf", "#dde6ed", "#e8c872"],  # slate
    ["#4c3a51", "#774360", "#b25068", "#e7ab79", "#f9f5eb"],  # plum
    ["#142850", "#27496d", "#0c7b93", "#00a8cc", "#f3f6f4"],  # depth
    ["#3a4750", "#d72323", "#f5eded", "#eeeeee", "#303841"],  # poster
]


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))


def _gradient(size: tuple, stops: list, vertical: bool) -> Image.Image:
    """Multi-stop gradient built from a tiny strip resized up."""
    strip = Image.new("RGB", (1, len(stops)) if vertical else (len(stops), 1))
    for i, color in enumerate(stops):
        strip.putpixel((0, i) if vertical else (i, 0), _hex(color))
    return strip.resize(size, Image.BICUBIC)


def _glow(base: Image.Image, rng: random.Random, palette: list) -> None:
    """Soft radial glows screened onto the base."""
    w, h = base.size
    for _ in range(rng.randint(3, 5)):
        r = rng.randint(min(w, h) // 5, min(w, h) // 2)
        cx, cy = rng.randint(0, w), rng.randint(0, h)
        layer = Image.new("RGB", base.size, (0, 0, 0))
        draw = ImageDraw.Draw(layer)
        color = _hex(rng.choice(palette))
        dimmed = tuple(int(c * rng.uniform(0.45, 0.8)) for c in color)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=dimmed)
        layer = layer.filter(ImageFilter.GaussianBlur(r // 2))
        glowed = ImageChops.screen(base, layer)
        base.paste(glowed, (0, 0))


def _dunes(base: Image.Image, rng: random.Random, palette: list) -> None:
    """Layered sine-wave silhouettes, back to front."""
    w, h = base.size
    layers = rng.randint(3, 5)
    draw = ImageDraw.Draw(base)
    for i in range(layers):
        baseline = h * (0.35 + 0.6 * (i + 1) / (layers + 1))
        amp = h * rng.uniform(0.04, 0.12)
        freq = rng.uniform(1.2, 3.0)
        phase = rng.uniform(0, math.tau)
        points = [(x, baseline + amp * math.sin(freq * math.tau * x / w + phase)) for x in range(0, w + 8, 8)]
        points += [(w, h), (0, h)]
        draw.polygon(points, fill=_hex(palette[min(i + 1, len(palette) - 1)]))


def _ribbons(base: Image.Image, rng: random.Random, palette: list) -> None:
    """Overlapping translucent sine ribbons."""
    w, h = base.size
    for i in range(rng.randint(3, 5)):
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        mid = h * rng.uniform(0.2, 0.8)
        amp = h * rng.uniform(0.05, 0.18)
        freq = rng.uniform(0.8, 2.2)
        phase = rng.uniform(0, math.tau)
        thick = h * rng.uniform(0.06, 0.16)
        top = [(x, mid + amp * math.sin(freq * math.tau * x / w + phase)) for x in range(0, w + 8, 8)]
        bottom = [(x, y + thick) for x, y in reversed(top)]
        draw.polygon(top + bottom, fill=_hex(rng.choice(palette)) + (rng.randint(120, 200),))
        base.paste(Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB"), (0, 0))


def _geo(base: Image.Image, rng: random.Random, palette: list) -> None:
    """Mid-century geometric poster shapes."""
    w, h = base.size
    draw = ImageDraw.Draw(base, "RGBA")
    for _ in range(rng.randint(4, 7)):
        color = _hex(rng.choice(palette)) + (rng.randint(170, 255),)
        kind = rng.random()
        x, y = rng.randint(-w // 4, w), rng.randint(-h // 4, h)
        s = rng.randint(min(w, h) // 8, min(w, h) // 2)
        if kind < 0.4:
            draw.ellipse([x, y, x + s, y + s], fill=color)
        elif kind < 0.75:
            draw.rectangle([x, y, x + s, y + int(s * rng.uniform(0.4, 1.6))], fill=color)
        else:
            draw.pieslice([x, y, x + s * 2, y + s * 2], 180, 270, fill=color)


def _finish(img: Image.Image, rng: random.Random) -> Image.Image:
    """Grain + vignette so renders read as intentional."""
    noise = Image.effect_noise(img.size, 14).convert("L")
    img = Image.composite(img, Image.new("RGB", img.size, (12, 12, 16)), noise.point(lambda v: 255 - abs(v - 128) // 6))
    mask = Image.new("L", (img.width // 4, img.height // 4), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-mask.width // 4, -mask.height // 4, mask.width * 5 // 4, mask.height * 5 // 4], fill=255)
    mask = mask.resize(img.size).filter(ImageFilter.GaussianBlur(min(img.size) // 8))
    return Image.composite(img, Image.eval(img, lambda v: int(v * 0.82)), mask)


def make_art(prompt: str, seed: int, width: int, height: int) -> Image.Image:
    rng = random.Random(f"{seed}:{prompt}")
    palette = rng.choice(PALETTES)
    style = rng.choice([_glow, _dunes, _ribbons, _geo])
    if style is _glow:
        # Glows read best screened over a dark base.
        stops = sorted(palette, key=lambda c: sum(_hex(c)))[:3]
        rng.shuffle(stops)
    else:
        stops = rng.sample(palette, k=3)
    img = _gradient((width, height), stops, vertical=rng.random() < 0.5)
    style(img, rng, palette)
    return _finish(img, rng)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _progress(context: ExecutionContext, steps: int = 8) -> None:
    for i in range(steps):
        await context.report_progress(i / steps)
        await asyncio.sleep(STEP_DELAY)


async def _load_input(context: ExecutionContext, parameters: dict) -> Image.Image:
    images = parameters.get("input_images") or []
    if not images:
        raise ValueError("No input images provided")
    data = await context.assets.download(images[0])
    return Image.open(io.BytesIO(data)).convert("RGB")


# --- Tools --------------------------------------------------------------------

def _t2i_params(default_steps: int, default_guidance: float) -> list:
    return [
        ToolParameter(name="prompt", type="string", required=True, ui_hints={"control": "prompt_editor"}),
        ToolParameter(
            name="width", type="integer", default=1024, minimum=512, maximum=2048,
            description="Image width in pixels",
            ui_hints={"control": "resolution", "step": 64, "paired-with": "height"},
        ),
        ToolParameter(
            name="height", type="integer", default=1024, minimum=512, maximum=2048,
            description="Image height in pixels",
            ui_hints={"control": "resolution", "step": 64, "paired-with": "width"},
        ),
        ToolParameter(name="seed", type="integer", description="Random seed", ui_hints={"control": "seed"}),
        ToolParameter(name="steps", type="integer", default=default_steps, minimum=4, maximum=60,
                      description="Denoising steps", ui_hints={"control": "slider"}),
        ToolParameter(name="guidance", type="number", default=default_guidance, minimum=0, maximum=12,
                      description="Guidance (CFG scale)", ui_hints={"control": "slider", "step": 0.1}),
        ToolParameter(name="sampler", type="string", default="euler",
                      enum=["euler", "dpmpp_2m", "uni_pc"], description="Sampler",
                      ui_hints={"control": "dropdown"}),
    ]


_T2I_LAYOUT = [
    Group(label="Advanced", collapsed=True, params=[Param("steps"), Param("guidance"), Param("sampler")]),
]


async def _run_t2i(context: ExecutionContext, parameters: dict) -> dict:
    await _progress(context)
    seed = parameters.get("seed") or random.randint(0, 2**31)
    img = make_art(parameters["prompt"], int(seed),
                   int(parameters.get("width", 1024)), int(parameters.get("height", 1024)))
    asset_id = await context.assets.upload(_png(img), extension=".png")
    await context.report_progress(1.0)
    return {"asset_id": asset_id}


@tool(slug="flux-dev", display_name="Flux Dev", task_types="text-to-image",
      description="Flux Dev text-to-image workflow.",
      parameters=_t2i_params(28, 3.5), layout=_T2I_LAYOUT)
async def flux_dev(context: ExecutionContext, parameters: dict) -> dict:
    return await _run_t2i(context, parameters)


@tool(slug="sdxl", display_name="SDXL", task_types="text-to-image",
      description="SDXL base workflow.",
      parameters=_t2i_params(30, 6.5), layout=_T2I_LAYOUT)
async def sdxl(context: ExecutionContext, parameters: dict) -> dict:
    return await _run_t2i(context, parameters)


@tool(
    slug="kontext-edit", display_name="Kontext Edit", task_types="image-to-image",
    description="Prompt-guided image edit workflow.",
    parameters=[
        ToolParameter(name="prompt", type="string", required=True, ui_hints={"control": "prompt_editor"}),
        ToolParameter(name="input_images", type="array", required=True, items={"type": "string"},
                      ui_hints={"control": "image_picker", "min-items": 1, "max-items": 1}),
        ToolParameter(name="strength", type="number", default=0.7, minimum=0, maximum=1,
                      description="Edit strength", ui_hints={"control": "slider", "step": 0.05}),
        ToolParameter(name="seed", type="integer", description="Random seed", ui_hints={"control": "seed"}),
    ],
)
async def kontext_edit(context: ExecutionContext, parameters: dict) -> dict:
    source = await _load_input(context, parameters)
    await _progress(context)
    seed = parameters.get("seed") or random.randint(0, 2**31)
    restyle = make_art(parameters["prompt"], int(seed), source.width, source.height)
    strength = float(parameters.get("strength", 0.7))
    out = Image.blend(source, restyle, max(0.0, min(1.0, strength)))
    asset_id = await context.assets.upload(_png(out), extension=".png")
    await context.report_progress(1.0)
    return {"asset_id": asset_id}


@tool(
    slug="ultrasharp-4x", display_name="4x-UltraSharp", task_types="upscale-image",
    description="High-detail upscaling workflow.",
    parameters=[
        ToolParameter(name="input_images", type="array", required=True, items={"type": "string"},
                      ui_hints={"control": "image_picker", "min-items": 1, "max-items": 1}),
        ToolParameter(name="scale_factor", type="number", default=2, minimum=1, maximum=4,
                      description="Upscale factor", ui_hints={"control": "slider", "step": 0.5}),
    ],
)
async def ultrasharp(context: ExecutionContext, parameters: dict) -> dict:
    source = await _load_input(context, parameters)
    await _progress(context, steps=5)
    factor = float(parameters.get("scale_factor", 2))
    out = source.resize((int(source.width * factor), int(source.height * factor)), Image.LANCZOS)
    out = out.filter(ImageFilter.UnsharpMask(radius=2, percent=80, threshold=2))
    asset_id = await context.assets.upload(_png(out), extension=".png")
    await context.report_progress(1.0)
    return {"asset_id": asset_id}


@tool(
    slug="birefnet", display_name="BiRefNet Matting", task_types="remove-background",
    description="Background removal workflow.",
    parameters=[
        ToolParameter(name="input_images", type="array", required=True, items={"type": "string"},
                      ui_hints={"control": "image_picker", "min-items": 1, "max-items": 1}),
    ],
)
async def birefnet(context: ExecutionContext, parameters: dict) -> dict:
    source = await _load_input(context, parameters)
    await _progress(context, steps=5)
    # Feathered center matte: believable cutout silhouette for demo imagery.
    mask = Image.new("L", (source.width // 4, source.height // 4), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([mask.width // 8, mask.height // 12, mask.width * 7 // 8, mask.height * 11 // 12], fill=255)
    mask = mask.resize(source.size).filter(ImageFilter.GaussianBlur(min(source.size) // 24))
    out = source.convert("RGBA")
    out.putalpha(mask)
    asset_id = await context.assets.upload(_png(out), extension=".png")
    await context.report_progress(1.0)
    return {"asset_id": asset_id}


def main() -> None:
    parser = create_argument_parser(description="Stimma docs demo provider")
    args = parser.parse_args()
    setup_logging(args.log_level, "docs_demo")

    config = ProviderConfig(
        provider_id="comfyui",
        provider_name="ComfyUI",
        server="docs-demo/1.0.0",
        max_concurrent=3,
        supports_cancel=True,
    )

    from stimma_tools_protocol.transport import StdioTransport

    provider = Provider(config=config, transport=StdioTransport())
    asyncio.run(run_provider(provider, args))


if __name__ == "__main__":
    main()
