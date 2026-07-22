"""
Color grading preset data for ComfyUI-Darkroom Wave 3.
All presets are frozen dataclasses — immutable, shared across nodes.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional


# ---------------------------------------------------------------------------
# Dataclass definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToneCurvePreset:
    """5-point tone curve preset. Points are (input, output) with input at 0/0.25/0.5/0.75/1.0."""
    name: str
    # Master RGB curve: offsets from identity at each of the 5 positions
    # (shadows_offset, darks_offset, midtones_offset, lights_offset, highlights_offset)
    master: Tuple[float, float, float, float, float]
    # Per-channel shadow/highlight offsets (from identity)
    red_shadows: float = 0.0
    red_highlights: float = 0.0
    green_shadows: float = 0.0
    green_highlights: float = 0.0
    blue_shadows: float = 0.0
    blue_highlights: float = 0.0


@dataclass(frozen=True)
class ColorBalancePreset:
    """3-Way Color Balance preset. Hue angle (0-360) + intensity (0-100) per zone."""
    name: str
    shadow_hue: float
    shadow_intensity: float
    midtone_hue: float
    midtone_intensity: float
    highlight_hue: float
    highlight_intensity: float
    master_saturation: float = 0.0  # -50 to 50


@dataclass(frozen=True)
class LogWheelsPreset:
    """Log Wheels preset. Hue/sat/density per zone + zone boundaries."""
    name: str
    shadow_hue: float
    shadow_saturation: float
    shadow_density: float
    midtone_hue: float
    midtone_saturation: float
    midtone_density: float
    highlight_hue: float
    highlight_saturation: float
    highlight_density: float
    shadow_range: float = 0.15
    highlight_range: float = 0.85


@dataclass(frozen=True)
class HueVsHuePreset:
    """Hue vs Hue preset. Shift per 8 hue bands."""
    name: str
    red: float = 0.0
    orange: float = 0.0
    yellow: float = 0.0
    green: float = 0.0
    aqua: float = 0.0
    blue: float = 0.0
    purple: float = 0.0
    magenta: float = 0.0


@dataclass(frozen=True)
class HueVsSatPreset:
    """Hue vs Sat preset. Saturation adjustment per 8 hue bands."""
    name: str
    red: float = 0.0
    orange: float = 0.0
    yellow: float = 0.0
    green: float = 0.0
    aqua: float = 0.0
    blue: float = 0.0
    purple: float = 0.0
    magenta: float = 0.0


@dataclass(frozen=True)
class LumVsSatPreset:
    """Lum vs Sat preset. Saturation adjustment per 5 luminance zones."""
    name: str
    blacks: float = 0.0
    shadows: float = 0.0
    midtones: float = 0.0
    highlights: float = 0.0
    whites: float = 0.0


@dataclass(frozen=True)
class SatVsSatPreset:
    """Sat vs Sat preset. Saturation adjustment per 4 saturation zones."""
    name: str
    low: float = 0.0
    mid_low: float = 0.0
    mid_high: float = 0.0
    high: float = 0.0


@dataclass(frozen=True)
class ColorWarperRegion:
    """A single color warper region: source selection + target shift."""
    src_hue: float          # center hue of source region
    src_hue_width: float    # hue width in degrees
    src_sat_min: float      # min saturation (0-1)
    src_sat_max: float      # max saturation (0-1)
    hue_shift: float        # degrees to shift
    sat_shift: float        # saturation adjustment (-100 to 100)


@dataclass(frozen=True)
class ColorWarperPreset:
    """Color Warper preset. Multiple regions that work together."""
    name: str
    regions: Tuple[ColorWarperRegion, ...]


# ---------------------------------------------------------------------------
# Tone Curve presets
# ---------------------------------------------------------------------------

TONE_CURVE_PRESETS = {
    "S-Curve \u2014 Light": ToneCurvePreset(
        name="S-Curve \u2014 Light",
        master=(-5, -3, 0, 3, 5),
    ),
    "S-Curve \u2014 Medium": ToneCurvePreset(
        name="S-Curve \u2014 Medium",
        master=(-10, -5, 0, 5, 10),
    ),
    "S-Curve \u2014 Strong": ToneCurvePreset(
        name="S-Curve \u2014 Strong",
        master=(-18, -8, 0, 8, 18),
    ),
    "Faded Blacks": ToneCurvePreset(
        name="Faded Blacks",
        master=(15, 5, 0, -3, -8),
    ),
    "Crushed Blacks": ToneCurvePreset(
        name="Crushed Blacks",
        master=(-20, -5, 0, 3, 5),
    ),
    "High Key": ToneCurvePreset(
        name="High Key",
        master=(10, 8, 5, 3, 0),
    ),
    "Low Key": ToneCurvePreset(
        name="Low Key",
        master=(0, -3, -5, -8, -10),
    ),
    "Cross-over Red Push": ToneCurvePreset(
        name="Cross-over Red Push",
        master=(0, 0, 0, 0, 0),
        red_shadows=5, red_highlights=8,
        blue_shadows=-3, blue_highlights=-5,
    ),
    "Cross-over Blue Push": ToneCurvePreset(
        name="Cross-over Blue Push",
        master=(0, 0, 0, 0, 0),
        blue_shadows=5, blue_highlights=8,
        red_shadows=-3, red_highlights=-5,
    ),
    "Linear Contrast": ToneCurvePreset(
        name="Linear Contrast",
        master=(-12, -6, 0, 6, 12),
    ),
    "Matte Film": ToneCurvePreset(
        name="Matte Film",
        master=(12, 4, 0, -2, -6),
    ),
}

TONE_CURVE_PRESET_NAMES = ["Custom (manual)"] + list(TONE_CURVE_PRESETS.keys())


# ---------------------------------------------------------------------------
# Color Balance presets (3-Way)
# ---------------------------------------------------------------------------

COLOR_BALANCE_PRESETS = {
    "Orange & Teal \u2014 cinematic": ColorBalancePreset(
        name="Orange & Teal \u2014 cinematic",
        shadow_hue=195, shadow_intensity=35,
        midtone_hue=30, midtone_intensity=10,
        highlight_hue=40, highlight_intensity=25,
    ),
    "Orange & Teal \u2014 subtle": ColorBalancePreset(
        name="Orange & Teal \u2014 subtle",
        shadow_hue=195, shadow_intensity=18,
        midtone_hue=0, midtone_intensity=0,
        highlight_hue=35, highlight_intensity=12,
    ),
    "Vintage Warm": ColorBalancePreset(
        name="Vintage Warm",
        shadow_hue=30, shadow_intensity=20,
        midtone_hue=45, midtone_intensity=8,
        highlight_hue=55, highlight_intensity=15,
    ),
    "Vintage Cool": ColorBalancePreset(
        name="Vintage Cool",
        shadow_hue=220, shadow_intensity=25,
        midtone_hue=200, midtone_intensity=8,
        highlight_hue=180, highlight_intensity=12,
    ),
    "Moonlight Blue": ColorBalancePreset(
        name="Moonlight Blue",
        shadow_hue=230, shadow_intensity=40,
        midtone_hue=215, midtone_intensity=15,
        highlight_hue=200, highlight_intensity=10,
    ),
    "Golden Hour": ColorBalancePreset(
        name="Golden Hour",
        shadow_hue=20, shadow_intensity=15,
        midtone_hue=35, midtone_intensity=20,
        highlight_hue=50, highlight_intensity=30,
    ),
    "Pastel Dream": ColorBalancePreset(
        name="Pastel Dream",
        shadow_hue=270, shadow_intensity=15,
        midtone_hue=330, midtone_intensity=10,
        highlight_hue=50, highlight_intensity=18,
        master_saturation=-15,
    ),
    "Film Noir \u2014 cold": ColorBalancePreset(
        name="Film Noir \u2014 cold",
        shadow_hue=220, shadow_intensity=20,
        midtone_hue=0, midtone_intensity=0,
        highlight_hue=200, highlight_intensity=8,
        master_saturation=-30,
    ),
    "Autumn Warmth": ColorBalancePreset(
        name="Autumn Warmth",
        shadow_hue=15, shadow_intensity=20,
        midtone_hue=30, midtone_intensity=15,
        highlight_hue=45, highlight_intensity=10,
    ),
    "Summer Vibrance": ColorBalancePreset(
        name="Summer Vibrance",
        shadow_hue=180, shadow_intensity=10,
        midtone_hue=60, midtone_intensity=8,
        highlight_hue=45, highlight_intensity=15,
        master_saturation=15,
    ),
    "Desaturated Teal": ColorBalancePreset(
        name="Desaturated Teal",
        shadow_hue=190, shadow_intensity=30,
        midtone_hue=185, midtone_intensity=12,
        highlight_hue=180, highlight_intensity=8,
        master_saturation=-20,
    ),
    "Magenta Mood": ColorBalancePreset(
        name="Magenta Mood",
        shadow_hue=300, shadow_intensity=25,
        midtone_hue=320, midtone_intensity=10,
        highlight_hue=340, highlight_intensity=15,
    ),
    "Bleach Bypass": ColorBalancePreset(
        name="Bleach Bypass",
        shadow_hue=210, shadow_intensity=12,
        midtone_hue=0, midtone_intensity=0,
        highlight_hue=40, highlight_intensity=8,
        master_saturation=-35,
    ),
    "Cross-processed": ColorBalancePreset(
        name="Cross-processed",
        shadow_hue=160, shadow_intensity=30,
        midtone_hue=60, midtone_intensity=15,
        highlight_hue=320, highlight_intensity=20,
    ),
    "Muted Earth Tones": ColorBalancePreset(
        name="Muted Earth Tones",
        shadow_hue=25, shadow_intensity=15,
        midtone_hue=35, midtone_intensity=10,
        highlight_hue=45, highlight_intensity=8,
        master_saturation=-25,
    ),
}

COLOR_BALANCE_PRESET_NAMES = ["Custom (manual)"] + list(COLOR_BALANCE_PRESETS.keys())


# ---------------------------------------------------------------------------
# Log Wheels presets
# ---------------------------------------------------------------------------

LOG_WHEELS_PRESETS = {
    "Warm Shadows, Cool Highlights": LogWheelsPreset(
        name="Warm Shadows, Cool Highlights",
        shadow_hue=30, shadow_saturation=25, shadow_density=0,
        midtone_hue=0, midtone_saturation=0, midtone_density=0,
        highlight_hue=210, highlight_saturation=20, highlight_density=0,
    ),
    "Cool Shadows, Warm Highlights": LogWheelsPreset(
        name="Cool Shadows, Warm Highlights",
        shadow_hue=220, shadow_saturation=25, shadow_density=0,
        midtone_hue=0, midtone_saturation=0, midtone_density=0,
        highlight_hue=40, highlight_saturation=20, highlight_density=0,
    ),
    "Teal & Orange \u2014 cinematic": LogWheelsPreset(
        name="Teal & Orange \u2014 cinematic",
        shadow_hue=190, shadow_saturation=35, shadow_density=-5,
        midtone_hue=25, midtone_saturation=10, midtone_density=0,
        highlight_hue=40, highlight_saturation=25, highlight_density=5,
    ),
    "Bleach Bypass \u2014 low sat, high con": LogWheelsPreset(
        name="Bleach Bypass \u2014 low sat, high con",
        shadow_hue=210, shadow_saturation=10, shadow_density=-15,
        midtone_hue=0, midtone_saturation=0, midtone_density=0,
        highlight_hue=40, highlight_saturation=5, highlight_density=10,
    ),
    "Day for Night \u2014 blue push": LogWheelsPreset(
        name="Day for Night \u2014 blue push",
        shadow_hue=230, shadow_saturation=45, shadow_density=-25,
        midtone_hue=220, midtone_saturation=20, midtone_density=-15,
        highlight_hue=210, highlight_saturation=15, highlight_density=-10,
    ),
    "Golden Hour enhancement": LogWheelsPreset(
        name="Golden Hour enhancement",
        shadow_hue=20, shadow_saturation=15, shadow_density=5,
        midtone_hue=35, midtone_saturation=18, midtone_density=0,
        highlight_hue=50, highlight_saturation=25, highlight_density=8,
    ),
    "Moonlight \u2014 cold blue shadows": LogWheelsPreset(
        name="Moonlight \u2014 cold blue shadows",
        shadow_hue=230, shadow_saturation=40, shadow_density=-10,
        midtone_hue=215, midtone_saturation=12, midtone_density=-5,
        highlight_hue=200, highlight_saturation=8, highlight_density=0,
    ),
}

LOG_WHEELS_PRESET_NAMES = ["Custom (manual)", "Neutral \u2014 reset all"] + list(LOG_WHEELS_PRESETS.keys())


# ---------------------------------------------------------------------------
# Hue vs Hue presets
# ---------------------------------------------------------------------------

HUE_VS_HUE_PRESETS = {
    "Fix green skin \u2192 warm": HueVsHuePreset(
        name="Fix green skin \u2192 warm",
        yellow=-8, green=-15, orange=5,
    ),
    "Fix magenta skin \u2192 natural": HueVsHuePreset(
        name="Fix magenta skin \u2192 natural",
        red=-10, magenta=-15, orange=5,
    ),
    "Sky blue \u2192 deeper blue": HueVsHuePreset(
        name="Sky blue \u2192 deeper blue",
        aqua=15, blue=10,
    ),
    "Sky blue \u2192 teal": HueVsHuePreset(
        name="Sky blue \u2192 teal",
        blue=-25, aqua=-10,
    ),
    "Greens \u2192 warmer (autumn)": HueVsHuePreset(
        name="Greens \u2192 warmer (autumn)",
        green=-30, yellow=-10, aqua=-15,
    ),
    "Greens \u2192 cooler (emerald)": HueVsHuePreset(
        name="Greens \u2192 cooler (emerald)",
        green=15, yellow=10,
    ),
    "Yellows \u2192 gold": HueVsHuePreset(
        name="Yellows \u2192 gold",
        yellow=-15, orange=-5,
    ),
    "Reds \u2192 orange (warmer)": HueVsHuePreset(
        name="Reds \u2192 orange (warmer)",
        red=15, magenta=10,
    ),
    "Reds \u2192 magenta (cooler)": HueVsHuePreset(
        name="Reds \u2192 magenta (cooler)",
        red=-15, orange=-10,
    ),
}

HUE_VS_HUE_PRESET_NAMES = ["Custom (manual)"] + list(HUE_VS_HUE_PRESETS.keys())


# ---------------------------------------------------------------------------
# Hue vs Sat presets
# ---------------------------------------------------------------------------

HUE_VS_SAT_PRESETS = {
    "Desaturate greens": HueVsSatPreset(
        name="Desaturate greens",
        green=-60, aqua=-30, yellow=-15,
    ),
    "Pop blues": HueVsSatPreset(
        name="Pop blues",
        blue=50, aqua=30, purple=20,
    ),
    "Pop reds & oranges": HueVsSatPreset(
        name="Pop reds & oranges",
        red=40, orange=50, yellow=15,
    ),
    "Mute everything except skin": HueVsSatPreset(
        name="Mute everything except skin",
        red=10, orange=10,
        yellow=-40, green=-60, aqua=-60, blue=-50, purple=-40, magenta=-30,
    ),
    "Vivid sunset": HueVsSatPreset(
        name="Vivid sunset",
        red=50, orange=60, yellow=40, magenta=20,
    ),
    "Teal & Orange pop": HueVsSatPreset(
        name="Teal & Orange pop",
        orange=45, aqua=40,
        green=-30, yellow=-15, blue=-10, purple=-20,
    ),
    "Pastel \u2014 reduce all gently": HueVsSatPreset(
        name="Pastel \u2014 reduce all gently",
        red=-25, orange=-25, yellow=-25, green=-25,
        aqua=-25, blue=-25, purple=-25, magenta=-25,
    ),
    "Hyper color \u2014 boost all": HueVsSatPreset(
        name="Hyper color \u2014 boost all",
        red=35, orange=35, yellow=35, green=35,
        aqua=35, blue=35, purple=35, magenta=35,
    ),
}

HUE_VS_SAT_PRESET_NAMES = ["Custom (manual)"] + list(HUE_VS_SAT_PRESETS.keys())


# ---------------------------------------------------------------------------
# Lum vs Sat presets
# ---------------------------------------------------------------------------

LUM_VS_SAT_PRESETS = {
    "Film look \u2014 desat highlights": LumVsSatPreset(
        name="Film look \u2014 desat highlights",
        highlights=-40, whites=-60,
    ),
    "Film look \u2014 desat shadows + highlights": LumVsSatPreset(
        name="Film look \u2014 desat shadows + highlights",
        blacks=-50, shadows=-30, highlights=-35, whites=-55,
    ),
    "Punch midtones": LumVsSatPreset(
        name="Punch midtones",
        midtones=45, shadows=15, highlights=15,
    ),
    "Pastel highlights": LumVsSatPreset(
        name="Pastel highlights",
        highlights=-50, whites=-70, midtones=-10,
    ),
    "Rich shadows": LumVsSatPreset(
        name="Rich shadows",
        blacks=30, shadows=45, midtones=10,
    ),
    "Bleach bypass \u2014 heavy desat": LumVsSatPreset(
        name="Bleach bypass \u2014 heavy desat",
        blacks=-60, shadows=-50, midtones=-40, highlights=-50, whites=-60,
    ),
    "Vibrant midrange": LumVsSatPreset(
        name="Vibrant midrange",
        shadows=20, midtones=40, highlights=20,
    ),
}

LUM_VS_SAT_PRESET_NAMES = ["Custom (manual)"] + list(LUM_VS_SAT_PRESETS.keys())


# ---------------------------------------------------------------------------
# Sat vs Sat presets
# ---------------------------------------------------------------------------

SAT_VS_SAT_PRESETS = {
    "Compress oversaturated": SatVsSatPreset(
        name="Compress oversaturated",
        mid_high=-30, high=-60,
    ),
    "Boost muted tones": SatVsSatPreset(
        name="Boost muted tones",
        low=50, mid_low=30,
    ),
    "Uniform saturation": SatVsSatPreset(
        name="Uniform saturation",
        low=40, mid_low=20, mid_high=-20, high=-40,
    ),
    "Hyper saturated push": SatVsSatPreset(
        name="Hyper saturated push",
        low=30, mid_low=40, mid_high=30, high=15,
    ),
    "Gentle mute": SatVsSatPreset(
        name="Gentle mute",
        low=-10, mid_low=-15, mid_high=-20, high=-30,
    ),
    "Protect saturated, boost muted": SatVsSatPreset(
        name="Protect saturated, boost muted",
        low=60, mid_low=35, mid_high=0, high=-10,
    ),
}

SAT_VS_SAT_PRESET_NAMES = ["Custom (manual)"] + list(SAT_VS_SAT_PRESETS.keys())


# ---------------------------------------------------------------------------
# Color Warper presets
# ---------------------------------------------------------------------------

COLOR_WARPER_PRESETS = {
    "Orange & Teal push": ColorWarperPreset(
        name="Orange & Teal push",
        regions=(
            ColorWarperRegion(25, 60, 0.1, 1.0, 10, 20),   # skin/warm → more orange
            ColorWarperRegion(200, 80, 0.1, 1.0, -15, 25),  # blues → teal + boost
        ),
    ),
    "Skin tone cleanup": ColorWarperPreset(
        name="Skin tone cleanup",
        regions=(
            ColorWarperRegion(20, 40, 0.15, 0.8, 5, -10),   # pull skin toward center
            ColorWarperRegion(45, 30, 0.1, 0.6, -10, -5),   # pull yellow-ish skin
        ),
    ),
    "Sky blue intensify": ColorWarperPreset(
        name="Sky blue intensify",
        regions=(
            ColorWarperRegion(210, 70, 0.1, 1.0, 0, 40),    # boost blue sat
            ColorWarperRegion(190, 50, 0.1, 0.8, 10, 25),   # cyan → bluer + boost
        ),
    ),
    "Green \u2192 teal shift": ColorWarperPreset(
        name="Green \u2192 teal shift",
        regions=(
            ColorWarperRegion(120, 60, 0.1, 1.0, 50, 10),   # green → teal
            ColorWarperRegion(90, 40, 0.1, 0.8, 30, 5),     # yellow-green → greener
        ),
    ),
    "Warm color expansion": ColorWarperPreset(
        name="Warm color expansion",
        regions=(
            ColorWarperRegion(15, 50, 0.15, 1.0, 0, 30),    # reds boost
            ColorWarperRegion(35, 50, 0.15, 1.0, 0, 25),    # oranges boost
            ColorWarperRegion(55, 40, 0.1, 1.0, 0, 20),     # yellows boost
        ),
    ),
    "Cool color expansion": ColorWarperPreset(
        name="Cool color expansion",
        regions=(
            ColorWarperRegion(190, 50, 0.1, 1.0, 0, 30),    # cyans boost
            ColorWarperRegion(230, 60, 0.1, 1.0, 0, 25),    # blues boost
            ColorWarperRegion(270, 40, 0.1, 1.0, 0, 20),    # purples boost
        ),
    ),
    "Complementary contrast": ColorWarperPreset(
        name="Complementary contrast",
        regions=(
            ColorWarperRegion(30, 70, 0.1, 1.0, 0, 30),     # warm boost
            ColorWarperRegion(210, 70, 0.1, 1.0, 0, 30),    # cool boost
            ColorWarperRegion(120, 60, 0.1, 0.8, 0, -25),   # mute greens
        ),
    ),
    "Monochromatic squeeze": ColorWarperPreset(
        name="Monochromatic squeeze",
        regions=(
            ColorWarperRegion(0, 180, 0.0, 0.3, 0, -50),    # kill low-sat globally
            ColorWarperRegion(0, 180, 0.3, 0.6, 0, -30),    # reduce mid-sat
        ),
    ),
    "Sunset spectrum enhance": ColorWarperPreset(
        name="Sunset spectrum enhance",
        regions=(
            ColorWarperRegion(0, 40, 0.15, 1.0, -5, 35),    # reds → deeper + boost
            ColorWarperRegion(30, 40, 0.15, 1.0, 5, 40),    # oranges → warmer + boost
            ColorWarperRegion(55, 35, 0.1, 1.0, -5, 30),    # yellows → amber + boost
            ColorWarperRegion(270, 50, 0.1, 1.0, 10, 20),   # purples → more magenta + boost
        ),
    ),
}

COLOR_WARPER_PRESET_NAMES = ["Custom (manual)"] + list(COLOR_WARPER_PRESETS.keys())
