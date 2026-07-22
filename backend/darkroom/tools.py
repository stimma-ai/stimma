"""Built-in Darkroom tool definitions.

The "Darkroom: *" image tools built from the vendored ComfyUI-Darkroom
engine (see vendor/ATTRIBUTION.md): Film Stock, Develop, Color Grade, and
Lens & Optics.
Registered by the lightweight provider; task type "filter" so they are
ordinary catalog tools usable from ToolView, the chat agent, flows, and
post-processing chains.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .ops import Stage, build_tool_layout, build_tool_schema, run_pipeline

ATTRIBUTION = {
    "label": "Based on Darkroom by Jérémie Louvaert",
    "url": "https://github.com/jeremieLouvaert/ComfyUI-Darkroom",
}

_CREDIT = (
    " Built on ComfyUI-Darkroom by Jérémie Louvaert "
    "(github.com/jeremieLouvaert/ComfyUI-Darkroom, MIT)."
)


@dataclass(frozen=True)
class DarkroomToolDef:
    id: str
    name: str
    description: str
    stages: List[Stage]
    mode_param: Optional[Dict[str, Any]] = None

    @property
    def parameter_schema(self) -> Dict[str, Any]:
        return build_tool_schema(self.stages, self.mode_param)

    @property
    def layout(self) -> List[Dict[str, Any]]:
        return build_tool_layout(self.stages, self.mode_param)

    def run(self, params: Dict[str, Any], image):
        mode_name = self.mode_param["name"] if self.mode_param else None
        return run_pipeline(self.stages, params, image, mode_name)


FILM_STOCK_TOOL = DarkroomToolDef(
    id="darkroom-film-stock",
    name="Darkroom: Film Stock",
    description=(
        "Give a digital image the look of real film: 161 film stocks with "
        "physics-based characteristic curves, plus optional cross-processing, "
        "print stock, halation, vignette, and grain stages applied in one pass."
        + _CREDIT
    ),
    mode_param={
        "name": "stock_type",
        "label": "Film Type",
        "description": "Which kind of film emulation to apply",
        "options": {
            "color": "Color (negative / slide)",
            "bw": "Black & White",
            "spectral_bw": "Spectral B&W (ortho/pan)",
            "none": "None (stages only)",
        },
        "default": "color",
    },
    stages=[
        Stage(key="color", label="Color Stock", module="film_stock_color",
              cls="FilmStockColor", mode_value="color"),
        Stage(key="bw", label="B&W Stock", module="film_stock_bw",
              cls="FilmStockBW", mode_value="bw"),
        Stage(key="spectral", label="Spectral B&W", module="spectral_bw",
              cls="SpectralBW", mode_value="spectral_bw"),
        Stage(key="crossprocess", label="Cross Process", module="cross_process",
              cls="CrossProcess", toggle=True,
              toggle_label="Develop in the wrong chemistry"),
        Stage(key="print", label="Print Stock", module="print_stock",
              cls="PrintStock", toggle=True,
              toggle_label="Print through cinema stock"),
        Stage(key="halation", label="Halation", module="halation",
              cls="Halation", toggle=True,
              toggle_label="Glow around bright highlights",
              exclude=("tint_r", "tint_g", "tint_b", "blur_type"),
              custom_only=("threshold", "radius")),
        Stage(key="vignette", label="Vignette", module="vignette",
              cls="Vignette", toggle=True,
              toggle_label="Darken toward the corners",
              fixed={"lens": "Custom"},
              exclude=("cos4_falloff", "tint_r", "tint_g", "tint_b")),
        Stage(key="grain", label="Film Grain", module="film_grain",
              cls="FilmGrain", toggle=True,
              toggle_label="ISO-scaled grain"),
        Stage(key="grainpro", label="Film Grain Pro (slow)", module="film_grain_pro",
              cls="FilmGrainPro", source="port", toggle=True,
              toggle_label="Physically simulated grain (slow)"),
        Stage(key="halftone", label="Halftone", module="halftone",
              cls="Halftone", toggle=True,
              toggle_label="Newsprint dot screen"),
    ],
)

DEVELOP_TOOL = DarkroomToolDef(
    id="darkroom-develop",
    name="Darkroom: Develop",
    description=(
        "Camera-raw style image development: white balance (manual Kelvin or "
        "auto), exposure and tonal controls, clarity/texture/dehaze, optional "
        "noise reduction and sharpening, and vibrance with skin protection."
        + _CREDIT
    ),
    mode_param={
        "name": "wb_mode",
        "label": "White Balance",
        "description": "Manual temperature/tint, automatic estimation, or leave as shot",
        "options": {
            "manual": "Manual (temperature / tint)",
            "auto": "Automatic",
            "off": "As shot",
        },
        "default": "off",
    },
    stages=[
        Stage(key="wb", label="White Balance", module="white_balance",
              cls="WhiteBalance", mode_value="manual", exclude=("strength",)),
        Stage(key="awb", label="Auto White Balance", module="auto_white_balance",
              cls="AutoWhiteBalance", mode_value="auto", exclude=("strength",)),
        Stage(key="tone", label="Exposure & Tone", module="exposure_tone",
              cls="ExposureTone", exclude=("strength",)),
        Stage(key="clarity", label="Clarity / Texture / Dehaze",
              module="clarity_texture_dehaze", cls="ClarityTextureDehaze",
              exclude=("strength", "preset")),
        Stage(key="nr", label="Noise Reduction", module="noise_reduction",
              cls="NoiseReduction", toggle=True, exclude=("strength",),
              toggle_label="Reduce luminance & color noise",
              custom_only=("luminance_amount", "luminance_detail",
                           "luminance_contrast", "color_amount", "color_detail")),
        Stage(key="sharpen", label="Sharpening", module="sharpening_pro",
              cls="SharpeningPro", toggle=True, exclude=("strength",),
              toggle_label="Edge-aware unsharp mask"),
        Stage(key="skin", label="Skin Tone Uniformity", module="skin_tone_uniformity",
              cls="SkinToneUniformity", source="port", toggle=True,
              exclude=("strength",),
              toggle_label="Even out skin color",
              custom_only=("hue_center", "hue_width", "saturation_min",
                           "saturation_max", "luminance_min", "luminance_max")),
        Stage(key="vibrance", label="Vibrance", module="vibrance",
              cls="Vibrance", exclude=("strength",)),
    ],
)

COLOR_GRADE_TOOL = DarkroomToolDef(
    id="darkroom-color-grade",
    name="Darkroom: Color Grade",
    description=(
        "Professional color grading, one corrector at a time: tone curves, "
        "lift/gamma/gain, log wheels, 3-way color balance, perceptual OkLab "
        "adjustments, and hue/saturation/luminance curve controls — each with "
        "curated presets." + _CREDIT
    ),
    mode_param={
        "name": "mode",
        "label": "Corrector",
        "description": "Which grading corrector to apply",
        "options": {
            "tone_curve": "Tone Curve",
            "lift_gamma_gain": "Lift / Gamma / Gain",
            "log_wheels": "Log Wheels",
            "color_balance": "3-Way Color Balance",
            "oklab": "OkLab Color",
            "hue_vs_hue": "Hue vs Hue",
            "hue_vs_sat": "Hue vs Sat",
            "lum_vs_sat": "Lum vs Sat",
            "sat_vs_sat": "Sat vs Sat",
            "color_warper": "Color Warper",
        },
        "default": "tone_curve",
    },
    stages=[
        Stage(key="tc", label="Tone Curve", module="tone_curve",
              cls="ToneCurve", mode_value="tone_curve",
              custom_value="Custom (manual)",
              custom_only=("shadows", "darks", "midtones", "lights",
                           "highlights", "red_shadows", "red_highlights",
                           "green_shadows", "green_highlights",
                           "blue_shadows", "blue_highlights")),
        Stage(key="lgg", label="Lift / Gamma / Gain", module="lift_gamma_gain",
              cls="LiftGammaGain", mode_value="lift_gamma_gain"),
        Stage(key="lw", label="Log Wheels", module="log_wheels",
              cls="LogWheels", mode_value="log_wheels",
              custom_value="Custom (manual)",
              custom_only=("shadow_hue", "shadow_saturation", "shadow_density",
                           "midtone_hue", "midtone_saturation", "midtone_density",
                           "highlight_hue", "highlight_saturation",
                           "highlight_density", "shadow_range", "highlight_range")),
        Stage(key="cb", label="3-Way Color Balance",
              module="three_way_color_balance", cls="ThreeWayColorBalance",
              mode_value="color_balance",
              custom_value="Custom (manual)",
              custom_only=("shadow_hue", "shadow_intensity", "midtone_hue",
                           "midtone_intensity", "highlight_hue",
                           "highlight_intensity")),
        Stage(key="ok", label="OkLab Color", module="oklab_color",
              cls="OkLabColor", mode_value="oklab"),
        Stage(key="hh", label="Hue vs Hue", module="hue_vs_hue",
              cls="HueVsHue", mode_value="hue_vs_hue",
              custom_value="Custom (manual)",
              custom_only=("red_shift", "orange_shift", "yellow_shift",
                           "green_shift", "aqua_shift", "blue_shift",
                           "purple_shift", "magenta_shift")),
        Stage(key="hs", label="Hue vs Sat", module="hue_vs_sat",
              cls="HueVsSat", mode_value="hue_vs_sat",
              custom_value="Custom (manual)",
              custom_only=("red_saturation", "orange_saturation",
                           "yellow_saturation", "green_saturation",
                           "aqua_saturation", "blue_saturation",
                           "purple_saturation", "magenta_saturation")),
        Stage(key="ls", label="Lum vs Sat", module="lum_vs_sat",
              cls="LumVsSat", mode_value="lum_vs_sat",
              custom_value="Custom (manual)",
              custom_only=("blacks_saturation", "shadows_saturation",
                           "midtones_saturation", "highlights_saturation",
                           "whites_saturation")),
        Stage(key="ss", label="Sat vs Sat", module="sat_vs_sat",
              cls="SatVsSat", mode_value="sat_vs_sat",
              custom_value="Custom (manual)",
              custom_only=("low_sat_adjust", "mid_low_sat_adjust",
                           "mid_high_sat_adjust", "high_sat_adjust")),
        Stage(key="cw", label="Color Warper", module="color_warper",
              cls="ColorWarper", source="port", mode_value="color_warper",
              custom_value="Custom (manual)",
              custom_only=("source_hue", "source_hue_width", "source_sat_min",
                           "source_sat_max", "hue_shift", "sat_shift")),
    ],
)

LENS_TOOL = DarkroomToolDef(
    id="darkroom-lens",
    name="Darkroom: Lens & Optics",
    description=(
        "Simulate or correct real lens optics: 102 measured lens profiles "
        "(distortion + chromatic aberration + vignette in one pass), or "
        "individual Brown-Conrady distortion, lateral chromatic aberration, "
        "and optical vignette controls." + _CREDIT
    ),
    mode_param={
        "name": "mode",
        "label": "Optic",
        "description": "Which optical effect to apply",
        "options": {
            "profile": "Lens Profile (all-in-one)",
            "distortion": "Lens Distortion",
            "ca": "Chromatic Aberration",
            "vignette": "Vignette",
        },
        "default": "profile",
    },
    stages=[
        Stage(key="profile", label="Lens Profile", module="lens_profile",
              cls="LensProfile", source="port", mode_value="profile"),
        Stage(key="distortion", label="Lens Distortion", module="lens_distortion",
              cls="LensDistortion", source="port", mode_value="distortion"),
        Stage(key="ca", label="Chromatic Aberration", module="chromatic_aberration",
              cls="ChromaticAberration", source="port", mode_value="ca"),
        Stage(key="vignette", label="Vignette", module="vignette",
              cls="Vignette", mode_value="vignette"),
    ],
)

DARKROOM_TOOLS: List[DarkroomToolDef] = [
    FILM_STOCK_TOOL,
    DEVELOP_TOOL,
    COLOR_GRADE_TOOL,
    LENS_TOOL,
]
