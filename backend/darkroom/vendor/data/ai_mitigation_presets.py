"""
AI-Mitigation presets for ComfyUI-Darkroom.

Tuned to mitigate the rendering signature of generative-image models
(Gemini 3 Pro Image, SDXL, Flux): atmospheric haze in open air,
highlight bloom halos, soft-gradient shadow edges on hard casts,
smoothed stone / fabric / skin micro-texture, creamy warm palette
convergence.

These do NOT remove the AI-feel. Per 2026-04-19 brain patterns:
deterministic post can MITIGATE but cannot REMOVE the distributed AI
signature. Three tiers, paired across Clarity/Texture/Dehaze and
HSL Selective. Pick the same tier on both nodes for a consistent stack.

Manual sliders ADD on top of preset values, so the preset is a starting
point, not a lock.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class CTDPreset:
    """Clarity / Texture / Dehaze values."""
    clarity: float = 0.0
    texture: float = 0.0
    dehaze: float = 0.0


@dataclass
class HSLPreset:
    """Per-hue HSL adjustments. Zero entries are skipped."""
    red_hue: float = 0.0
    red_saturation: float = 0.0
    red_luminance: float = 0.0
    orange_hue: float = 0.0
    orange_saturation: float = 0.0
    orange_luminance: float = 0.0
    yellow_hue: float = 0.0
    yellow_saturation: float = 0.0
    yellow_luminance: float = 0.0
    green_hue: float = 0.0
    green_saturation: float = 0.0
    green_luminance: float = 0.0
    aqua_hue: float = 0.0
    aqua_saturation: float = 0.0
    aqua_luminance: float = 0.0
    blue_hue: float = 0.0
    blue_saturation: float = 0.0
    blue_luminance: float = 0.0
    purple_hue: float = 0.0
    purple_saturation: float = 0.0
    purple_luminance: float = 0.0
    magenta_hue: float = 0.0
    magenta_saturation: float = 0.0
    magenta_luminance: float = 0.0


# Subtle: light AI signature, mostly clean source.
# Standard: typical first-pass Gemini render with the full artifact list.
# Strong: multi-pass / heavily-smoothed output (still won't erase, just dial back).

AI_MITIGATION_CTD: Dict[str, CTDPreset] = {
    "AI Mitigation: Subtle":   CTDPreset(clarity=12, texture=18, dehaze=12),
    "AI Mitigation: Standard": CTDPreset(clarity=20, texture=28, dehaze=22),
    "AI Mitigation: Strong":   CTDPreset(clarity=32, texture=42, dehaze=35),
}

# Palette nudge: unpick the warm convergence (everything drifts orange/yellow,
# cools are under-represented). Pull warms down, push cools up. Slight
# orange-luminance cut at Standard+ adds skin dimensionality back.
AI_MITIGATION_HSL: Dict[str, HSLPreset] = {
    "AI Mitigation: Subtle": HSLPreset(
        red_saturation=-3,
        orange_saturation=-8,
        yellow_saturation=-6,
        aqua_saturation=6,
        blue_saturation=6,
    ),
    "AI Mitigation: Standard": HSLPreset(
        red_saturation=-6,
        orange_saturation=-15, orange_luminance=-3,
        yellow_saturation=-12,
        aqua_saturation=10,
        blue_saturation=12,
    ),
    "AI Mitigation: Strong": HSLPreset(
        red_saturation=-10,
        orange_saturation=-25, orange_luminance=-5,
        yellow_saturation=-18,
        aqua_saturation=15,
        blue_saturation=18,
    ),
}

CTD_PRESET_NAMES = ["Custom (manual)"] + list(AI_MITIGATION_CTD.keys())
HSL_PRESET_NAMES = ["Custom (manual)"] + list(AI_MITIGATION_HSL.keys())
