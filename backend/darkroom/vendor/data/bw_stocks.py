"""
Black & white film stock profiles for ComfyUI-Darkroom.

Comprehensive library of B&W film stocks including classic, modern,
pushed processing, and specialty films.

Spectral sensitivity coefficients derived from darktable's published data
where available, refined with Capture One channel-mix data, estimated from
known film characteristics for others.
"""

from dataclasses import dataclass
from typing import Tuple

from .color_stocks import CurveParams


@dataclass(frozen=True)
class BWFilmStock:
    name: str
    red_weight: float
    green_weight: float
    blue_weight: float
    contrast_curve: CurveParams
    base_fog: float
    description: str


def _bw(name, desc, r, g, b, toe, shoulder, slope, fog=0.015):
    return BWFilmStock(
        name=name, red_weight=r, green_weight=g, blue_weight=b,
        contrast_curve=CurveParams(toe, shoulder, slope, 0.18, 0.18),
        base_fog=fog, description=desc,
    )


# =============================================================================
# ILFORD
# =============================================================================

BW_ILFORD = {
    "Ilford HP5 Plus 400": _bw(
        "Ilford HP5+", "Classic all-rounder. Medium contrast, versatile, pushable.",
        0.289, 0.347, 0.364, 1.4, 1.5, 1.0, 0.02),
    "Ilford HP5 Plus 400 - Pushed 1 Stop": _bw(
        "Ilford HP5+ Push 1", "HP5 pushed to 800. More contrast, deeper blacks.",
        0.289, 0.347, 0.364, 1.3, 1.4, 1.12, 0.025),
    "Ilford HP5 Plus 400 - Pushed 2 Stops": _bw(
        "Ilford HP5+ Push 2", "HP5 pushed to 1600. High contrast, gritty.",
        0.289, 0.347, 0.364, 1.2, 1.3, 1.25, 0.03),
    "Ilford FP4 Plus 125": _bw(
        "Ilford FP4+", "Fine grain, lower speed. Beautiful tonal rendering. Studio favorite.",
        0.241, 0.221, 0.537, 1.5, 1.6, 1.08, 0.01),
    "Ilford Delta 100": _bw(
        "Ilford Delta 100", "Tabular grain, extremely fine. Smooth gradations.",
        0.246, 0.254, 0.501, 1.5, 1.6, 1.05, 0.01),
    "Ilford Delta 400": _bw(
        "Ilford Delta 400", "Tabular grain, medium speed. Good all-round stock.",
        0.244, 0.236, 0.520, 1.4, 1.5, 1.02, 0.015),
    "Ilford Delta 3200": _bw(
        "Ilford Delta 3200", "Ultra-high speed. Visible grain, moody. Push to 6400+.",
        0.354, 0.373, 0.273, 1.3, 1.4, 1.05, 0.025),
    "Ilford PanF Plus 50": _bw(
        "Ilford PanF+", "Ultra fine grain. Extremely sharp. Needs good light.",
        0.46, 0.45, 0.09, 1.55, 1.65, 1.1, 0.008),
    "Ilford XP2 Super": _bw(
        "Ilford XP2 Super", "C-41 process B&W. Chromogenic, extremely fine grain, wide latitude.",
        0.25, 0.26, 0.49, 1.35, 1.65, 0.95, 0.01),
    "Ilford Ortho Plus": _bw(
        "Ilford Ortho Plus", "Orthochromatic: blind to red. Dark lips, ethereal skies.",
        0.0, 0.50, 0.50, 1.6, 1.4, 1.10, 0.01),
    "Ilford SFX 200": _bw(
        "Ilford SFX 200", "Extended red sensitivity. Near-infrared capable with R72 filter.",
        0.40, 0.25, 0.35, 1.5, 1.45, 1.05, 0.015),
}

# =============================================================================
# KODAK
# =============================================================================

BW_KODAK = {
    "Kodak TRI-X 400": _bw(
        "Kodak Tri-X 400", "Legendary. High contrast, punchy midtones, street icon.",
        0.222, 0.433, 0.344, 1.3, 1.4, 1.12, 0.02),
    "Kodak TRI-X 400 - Pushed 1 Stop": _bw(
        "Kodak Tri-X Push 1", "Tri-X at 800. More contrast, deeper shadows.",
        0.222, 0.433, 0.344, 1.2, 1.3, 1.22, 0.025),
    "Kodak TRI-X 400 - Pushed 2 Stops": _bw(
        "Kodak Tri-X Push 2", "Tri-X at 1600. Classic photojournalism look. Very contrasty.",
        0.222, 0.433, 0.344, 1.15, 1.25, 1.35, 0.03),
    "Kodak TRI-X 320": _bw(
        "Kodak Tri-X 320", "Classic Tri-X in 320 speed. Slightly less contrasty than 400.",
        0.40, 0.52, 0.08, 1.35, 1.45, 1.08, 0.02),
    "Kodak T-MAX 100": _bw(
        "Kodak T-MAX 100", "Tabular grain, extremely fine. Modern Kodak B&W benchmark.",
        0.27, 0.30, 0.43, 1.5, 1.55, 1.08, 0.01),
    "Kodak T-MAX 400": _bw(
        "Kodak T-MAX 400", "Modern tabular grain 400. Finer than Tri-X, less character.",
        0.27, 0.29, 0.44, 1.45, 1.5, 1.05, 0.015),
    "Kodak T-MAX P3200": _bw(
        "Kodak T-MAX P3200", "Ultra-high speed. Push to 6400-12800. Visible grain, night work.",
        0.17, 0.78, 0.05, 1.25, 1.35, 1.1, 0.03),
    "Kodak PLUS-X 125": _bw(
        "Kodak Plus-X 125", "Discontinued classic. Medium speed, beautiful tonality. Timeless.",
        0.316, 0.516, 0.168, 1.45, 1.55, 1.05, 0.015),
    "Kodak Panatomic-X": _bw(
        "Kodak Panatomic-X", "Extremely fine grain, very slow (32 ASA). Studio/macro work.",
        0.26, 0.26, 0.48, 1.55, 1.6, 1.08, 0.008),
    "Kodak Panatomic-X - Pushed 1 Stop": _bw(
        "Kodak Panatomic-X Push", "Panatomic-X pushed to 64. Slightly more contrast.",
        0.26, 0.26, 0.48, 1.45, 1.5, 1.18, 0.012),
    "Kodak Recording 2745": _bw(
        "Kodak Recording 2475", "High-speed surveillance film. Extreme grain, high contrast.",
        0.30, 0.28, 0.42, 1.15, 1.25, 1.3, 0.035),
    "Kodak Technical Pan": _bw(
        "Kodak Technical Pan", "Copy/scientific film. Extremely fine grain, very high contrast.",
        0.25, 0.30, 0.45, 1.8, 1.3, 1.35, 0.005),
    "Kodak Technical Pan - Technidol": _bw(
        "Kodak Technical Pan Technidol", "Tech Pan in Technidol developer. Tamed contrast, beautiful tones.",
        0.25, 0.30, 0.45, 1.5, 1.6, 0.95, 0.008),
    "Kodalith": _bw(
        "Kodalith", "Litho film. Near-binary contrast. High-art graphic B&W.",
        0.28, 0.28, 0.44, 2.5, 1.1, 1.8, 0.005),
    "Kodak BW400CN": _bw(
        "Kodak BW400CN", "C-41 chromogenic B&W. Fine grain, wide latitude, easy processing.",
        0.249, 0.670, 0.081, 1.35, 1.6, 0.95, 0.015),
    "Kodak HIE Infrared": _bw(
        "Kodak HIE Infrared", "Infrared film. Extreme red sensitivity, halation, surreal.",
        0.55, 0.25, 0.20, 1.4, 1.35, 1.15, 0.02),
}

# =============================================================================
# FUJI
# =============================================================================

BW_FUJI = {
    "Fuji Neopan 100 Acros": _bw(
        "Fuji Neopan 100 Acros", "Extremely fine grain. Superb reciprocity. Clean, precise.",
        0.21, 0.32, 0.47, 1.5, 1.55, 1.05, 0.01),
    "Fuji Neopan 100 Acros II": _bw(
        "Fuji Neopan Acros II", "Reformulated Acros (2019). Same quality, modern emulsion.",
        0.22, 0.31, 0.47, 1.5, 1.55, 1.05, 0.01),
    "Fuji Neopan 400": _bw(
        "Fuji Neopan 400", "Discontinued. Fine grain for 400. Clean, sharp, slightly cool.",
        0.368, 0.411, 0.221, 1.42, 1.5, 1.03, 0.015),
    "Fuji Neopan 1600": _bw(
        "Fuji Neopan 1600", "High-speed Fuji. Pronounced grain, good tonality for speed.",
        0.260, 0.462, 0.278, 1.3, 1.4, 1.08, 0.025),
    "Fuji FP-3000b": _bw(
        "Fuji FP-3000b", "Instant peel-apart B&W. High contrast, unique grain. Cult classic.",
        0.372, 0.251, 0.377, 1.6, 1.3, 1.2, 0.02),
}

# =============================================================================
# AGFA
# =============================================================================

BW_AGFA = {
    "Agfa APX 25": _bw(
        "Agfa APX 25", "Ultra slow, ultra fine grain. Legendary sharpness. Discontinued.",
        0.24, 0.26, 0.50, 1.55, 1.6, 1.08, 0.008),
    "Agfa APX 100": _bw(
        "Agfa APX 100", "Fine grain general purpose. Slightly warm tone for Agfa.",
        0.25, 0.26, 0.49, 1.48, 1.55, 1.05, 0.012),
    "Agfa APX 400": _bw(
        "Agfa APX 400", "Medium speed Agfa. Good all-rounder, moderate grain.",
        0.26, 0.26, 0.48, 1.4, 1.48, 1.02, 0.018),
    "Agfa Scala 200": _bw(
        "Agfa Scala 200", "B&W reversal (slide) film. Direct positive, unique tonal range.",
        0.189, 0.411, 0.400, 1.6, 1.4, 1.15, 0.008),
}

# =============================================================================
# ROLLEI / FOMA / OTHER
# =============================================================================

BW_OTHER = {
    "Rollei RPX 25": _bw(
        "Rollei RPX 25", "Ultra fine grain. Sharp, excellent tonality. Modern slow film.",
        0.24, 0.26, 0.50, 1.55, 1.58, 1.08, 0.008),
    "Rollei RPX 100": _bw(
        "Rollei RPX 100", "Fine grain, moderate speed. Clean and versatile.",
        0.25, 0.27, 0.48, 1.48, 1.55, 1.05, 0.012),
    "Rollei RPX 400": _bw(
        "Rollei RPX 400", "Medium speed Rollei. Slightly contrasty, good tonality.",
        0.26, 0.27, 0.47, 1.4, 1.48, 1.05, 0.015),
    "Rollei Infrared 400": _bw(
        "Rollei Infrared 400", "Extended red/infrared sensitivity. Wood effect capable.",
        0.48, 0.27, 0.25, 1.45, 1.4, 1.1, 0.015),
    "Fomapan 100": _bw(
        "Fomapan 100", "Czech classic. Traditional cubic grain. Budget-friendly, characterful.",
        0.26, 0.27, 0.47, 1.48, 1.52, 1.05, 0.012),
    "Fomapan 200": _bw(
        "Fomapan 200", "Medium speed Foma. Slightly softer than 100. Good general use.",
        0.26, 0.27, 0.47, 1.42, 1.5, 1.02, 0.015),
    "Fomapan 400": _bw(
        "Fomapan 400", "Fast Foma. More grain, traditional look. Very affordable.",
        0.27, 0.27, 0.46, 1.35, 1.45, 1.03, 0.02),
    "Bergger Pancro 400": _bw(
        "Bergger Pancro 400", "French double-emulsion film. Rich midtones, long tonal scale.",
        0.28, 0.28, 0.44, 1.38, 1.55, 1.0, 0.015),
    "Shanghai GP3 100": _bw(
        "Shanghai GP3 100", "Chinese classic. Slightly soft, characterful. Budget option.",
        0.26, 0.27, 0.47, 1.42, 1.52, 1.0, 0.015),
    "Kentmere 100": _bw(
        "Kentmere 100", "Ilford's budget line. Fine grain, good sharpness. Great value.",
        0.25, 0.26, 0.49, 1.48, 1.55, 1.05, 0.012),
    "Kentmere 400": _bw(
        "Kentmere 400", "Ilford's budget 400. Slightly more grain than HP5+, good contrast.",
        0.25, 0.27, 0.48, 1.38, 1.48, 1.03, 0.018),
    "Lomography Earl Grey 100": _bw(
        "Lomo Earl Grey 100", "Rebadged Fomapan. Traditional look, lomo branding.",
        0.26, 0.27, 0.47, 1.48, 1.52, 1.05, 0.012),
    "Lomography Lady Grey 400": _bw(
        "Lomo Lady Grey 400", "Rebadged Fomapan 400. Lomo-branded character film.",
        0.27, 0.27, 0.46, 1.35, 1.45, 1.03, 0.02),
    "CineStill BWXX": _bw(
        "CineStill BWXX", "Double-X cinema stock for stills. Classic Hollywood B&W look.",
        0.29, 0.28, 0.43, 1.35, 1.45, 1.08, 0.02),
}


# =============================================================================
# COLOR FILTER SIMULATIONS
# =============================================================================

COLOR_FILTERS = {
    "None": (1.0, 1.0, 1.0),
    "Red (25A)": (1.8, 0.4, 0.1),
    "Deep Red (29)": (2.0, 0.2, 0.05),
    "Orange (21)": (1.5, 0.6, 0.2),
    "Yellow (8)": (1.2, 0.8, 0.3),
    "Yellow-Green (11)": (0.8, 1.2, 0.3),
    "Green (58)": (0.3, 1.4, 0.4),
    "Blue (47)": (0.2, 0.4, 1.5),
    "Deep Blue (47B)": (0.1, 0.3, 1.8),
    "IR (R72)": (2.5, 0.3, 0.05),
}


# =============================================================================
# MASTER REGISTRY
# =============================================================================

BW_STOCKS = {}
BW_STOCKS.update(BW_ILFORD)
BW_STOCKS.update(BW_KODAK)
BW_STOCKS.update(BW_FUJI)
BW_STOCKS.update(BW_AGFA)
BW_STOCKS.update(BW_OTHER)

BW_STOCK_NAMES = sorted(BW_STOCKS.keys())
FILTER_NAMES = list(COLOR_FILTERS.keys())
