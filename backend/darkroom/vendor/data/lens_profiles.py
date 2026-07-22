"""
Lens profile database for ComfyUI-Darkroom.

Real lens models organized by brand with distortion, chromatic aberration,
and vignette coefficients. Data derived from published lens reviews,
optical bench tests, and manufacturer specs.

Distortion: Brown-Conrady k1/k2 (negative=barrel, positive=pincushion)
CA: lateral shift in pixels at image edge (normalized to 1024px)
Vignette: corner darkening (stops) and falloff midpoint

Each profile can be used by: Chromatic Aberration, Vignette,
Lens Distortion, and Lens Profile nodes.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class LensProfile:
    name: str           # Display name: "Canon EF 50mm f/1.4 USM"
    brand: str          # Brand category
    focal_length: str   # "50mm" or "24-70mm"
    max_aperture: str   # "f/1.4" or "f/2.8"
    # Distortion (Brown-Conrady)
    k1: float           # Primary radial coefficient
    k2: float           # Secondary radial coefficient
    # Chromatic aberration (pixels at edge, normalized to 1024px)
    ca_r: float         # Red channel shift (negative = inward)
    ca_b: float         # Blue channel shift (positive = outward)
    # Vignette
    vig_strength: float # Corner darkening (0-1 scale, ~stops/3)
    vig_midpoint: float # Where falloff begins (0-1, center to edge)
    description: str    # One-line character description


def _lp(name, brand, fl, ap, k1, k2, ca_r, ca_b, vig, vig_mid, desc):
    return LensProfile(name, brand, fl, ap, k1, k2, ca_r, ca_b, vig, vig_mid, desc)


# =============================================================================
# CANON
# =============================================================================

CANON = {
    "Canon EF 24mm f/1.4L II USM": _lp(
        "Canon EF 24mm f/1.4L II", "Canon", "24mm", "f/1.4",
        -0.12, 0.02, -0.9, 1.1, 0.55, 0.38,
        "Fast wide L-series. Moderate barrel, noticeable CA wide open"),
    "Canon EF 35mm f/1.4L II USM": _lp(
        "Canon EF 35mm f/1.4L II", "Canon", "35mm", "f/1.4",
        -0.05, 0.005, -0.5, 0.6, 0.40, 0.45,
        "Modern L-series wide. Well corrected, mild vignette wide open"),
    "Canon EF 50mm f/1.2L USM": _lp(
        "Canon EF 50mm f/1.2L", "Canon", "50mm", "f/1.2",
        -0.02, 0.0, -0.6, 0.7, 0.50, 0.40,
        "Ultra-fast fifty. Heavy vignette and CA wide open, dreamy character"),
    "Canon EF 50mm f/1.4 USM": _lp(
        "Canon EF 50mm f/1.4", "Canon", "50mm", "f/1.4",
        -0.015, 0.0, -0.4, 0.5, 0.35, 0.50,
        "Classic nifty fifty. Slight barrel, moderate CA"),
    "Canon EF 50mm f/1.8 STM": _lp(
        "Canon EF 50mm f/1.8 STM", "Canon", "50mm", "f/1.8",
        -0.01, 0.0, -0.3, 0.4, 0.30, 0.55,
        "Budget fifty. Surprisingly well-corrected for the price"),
    "Canon EF 85mm f/1.2L II USM": _lp(
        "Canon EF 85mm f/1.2L II", "Canon", "85mm", "f/1.2",
        0.01, 0.0, -0.4, 0.5, 0.45, 0.42,
        "The portrait king. Heavy vignette wide open, gorgeous rendering"),
    "Canon EF 85mm f/1.4L IS USM": _lp(
        "Canon EF 85mm f/1.4L IS", "Canon", "85mm", "f/1.4",
        0.01, 0.0, -0.2, 0.25, 0.30, 0.55,
        "Modern portrait L. Much better corrected than the 1.2"),
    "Canon EF 135mm f/2L USM": _lp(
        "Canon EF 135mm f/2L", "Canon", "135mm", "f/2",
        0.03, -0.005, -0.15, 0.15, 0.15, 0.65,
        "Legendary portrait/event tele. Minimal distortion, clean"),
    "Canon EF 16-35mm f/2.8L III USM": _lp(
        "Canon EF 16-35mm f/2.8L III", "Canon", "16-35mm", "f/2.8",
        -0.25, 0.05, -1.2, 1.5, 0.50, 0.35,
        "Pro wide zoom. Barrel at 16mm, corrects by 35mm"),
    "Canon EF 24-70mm f/2.8L II USM": _lp(
        "Canon EF 24-70mm f/2.8L II", "Canon", "24-70mm", "f/2.8",
        -0.08, 0.01, -0.6, 0.7, 0.35, 0.45,
        "Workhorse pro zoom. Barrel at 24mm, slight pincushion at 70mm"),
    "Canon EF 70-200mm f/2.8L IS III USM": _lp(
        "Canon EF 70-200mm f/2.8L IS III", "Canon", "70-200mm", "f/2.8",
        0.03, -0.005, -0.2, 0.25, 0.20, 0.60,
        "The event/sport standard. Slight pincushion, well-corrected"),
    "Canon RF 50mm f/1.2L USM": _lp(
        "Canon RF 50mm f/1.2L", "Canon", "50mm", "f/1.2",
        -0.01, 0.0, -0.3, 0.35, 0.40, 0.45,
        "Mirrorless flagship fifty. Better corrected than EF version"),
    "Canon RF 28-70mm f/2L USM": _lp(
        "Canon RF 28-70mm f/2L", "Canon", "28-70mm", "f/2",
        -0.06, 0.01, -0.5, 0.6, 0.45, 0.40,
        "Unique f/2 zoom. Heavy, excellent optics, some vignette"),
}

# =============================================================================
# NIKON
# =============================================================================

NIKON = {
    "Nikon AF-S 24mm f/1.4G ED": _lp(
        "Nikon 24mm f/1.4G", "Nikon", "24mm", "f/1.4",
        -0.13, 0.02, -0.8, 1.0, 0.50, 0.40,
        "Fast wide Nikkor. Barrel distortion, moderate CA"),
    "Nikon AF-S 35mm f/1.4G": _lp(
        "Nikon 35mm f/1.4G", "Nikon", "35mm", "f/1.4",
        -0.06, 0.008, -0.5, 0.6, 0.40, 0.45,
        "Classic fast 35. Good correction, some field curvature"),
    "Nikon AF-S 50mm f/1.4G": _lp(
        "Nikon 50mm f/1.4G", "Nikon", "50mm", "f/1.4",
        -0.015, 0.0, -0.4, 0.5, 0.35, 0.50,
        "Standard fast fifty. Slight barrel, typical CA"),
    "Nikon AF-S 50mm f/1.8G": _lp(
        "Nikon 50mm f/1.8G", "Nikon", "50mm", "f/1.8",
        -0.012, 0.0, -0.3, 0.35, 0.25, 0.55,
        "Budget champion. Remarkably clean for the price"),
    "Nikon AF-S 58mm f/1.4G": _lp(
        "Nikon 58mm f/1.4G", "Nikon", "58mm", "f/1.4",
        -0.01, 0.0, -0.3, 0.35, 0.45, 0.42,
        "Noct tribute. Designed for rendering character, not sharpness"),
    "Nikon AF-S 85mm f/1.4G": _lp(
        "Nikon 85mm f/1.4G", "Nikon", "85mm", "f/1.4",
        0.01, 0.0, -0.2, 0.25, 0.30, 0.55,
        "Portrait standard. Clean, slight pincushion"),
    "Nikon AF-S 105mm f/1.4E ED": _lp(
        "Nikon 105mm f/1.4E", "Nikon", "105mm", "f/1.4",
        0.02, 0.0, -0.15, 0.2, 0.25, 0.58,
        "Unique fast 105. Beautiful bokeh, slight vignette"),
    "Nikon AF-S 14-24mm f/2.8G ED": _lp(
        "Nikon 14-24mm f/2.8G", "Nikon", "14-24mm", "f/2.8",
        -0.35, 0.08, -1.5, 1.8, 0.55, 0.32,
        "Legendary ultra-wide. Strong barrel at 14mm, heavy CA"),
    "Nikon AF-S 24-70mm f/2.8E ED VR": _lp(
        "Nikon 24-70mm f/2.8E VR", "Nikon", "24-70mm", "f/2.8",
        -0.07, 0.01, -0.5, 0.6, 0.30, 0.48,
        "Pro standard zoom. Well corrected with VR"),
    "Nikon AF-S 70-200mm f/2.8E FL ED VR": _lp(
        "Nikon 70-200mm f/2.8E FL", "Nikon", "70-200mm", "f/2.8",
        0.03, -0.005, -0.2, 0.2, 0.18, 0.62,
        "Pro tele zoom. Extremely well corrected, minimal aberrations"),
    "Nikon Z 50mm f/1.2 S": _lp(
        "Nikon Z 50mm f/1.2 S", "Nikon", "50mm", "f/1.2",
        -0.01, 0.0, -0.25, 0.3, 0.35, 0.48,
        "Z-mount flagship. Superb correction for f/1.2"),
    "Nikon Z 50mm f/1.8 S": _lp(
        "Nikon Z 50mm f/1.8 S", "Nikon", "50mm", "f/1.8",
        -0.008, 0.0, -0.15, 0.2, 0.18, 0.60,
        "The benchmark fifty. Incredibly well corrected"),
}

# =============================================================================
# SONY
# =============================================================================

SONY = {
    "Sony FE 24mm f/1.4 GM": _lp(
        "Sony 24mm f/1.4 GM", "Sony", "24mm", "f/1.4",
        -0.10, 0.015, -0.7, 0.9, 0.45, 0.42,
        "Compact fast wide. Good correction for its size"),
    "Sony FE 35mm f/1.4 GM": _lp(
        "Sony 35mm f/1.4 GM", "Sony", "35mm", "f/1.4",
        -0.04, 0.005, -0.4, 0.5, 0.35, 0.48,
        "Lightweight GM 35. Excellent optical quality"),
    "Sony FE 50mm f/1.2 GM": _lp(
        "Sony 50mm f/1.2 GM", "Sony", "50mm", "f/1.2",
        -0.01, 0.0, -0.25, 0.3, 0.38, 0.45,
        "Sony's fastest fifty. Superb across the frame"),
    "Sony FE 50mm f/1.4 GM": _lp(
        "Sony 50mm f/1.4 GM", "Sony", "50mm", "f/1.4",
        -0.012, 0.0, -0.2, 0.25, 0.28, 0.52,
        "Compact GM fifty. Near-perfect correction"),
    "Sony FE 85mm f/1.4 GM": _lp(
        "Sony 85mm f/1.4 GM", "Sony", "85mm", "f/1.4",
        0.01, 0.0, -0.2, 0.25, 0.28, 0.55,
        "Portrait GM. Beautiful bokeh, clean correction"),
    "Sony FE 135mm f/1.8 GM": _lp(
        "Sony 135mm f/1.8 GM", "Sony", "135mm", "f/1.8",
        0.025, -0.003, -0.1, 0.12, 0.15, 0.65,
        "Incredible portrait tele. Almost zero aberrations"),
    "Sony FE 12-24mm f/2.8 GM": _lp(
        "Sony 12-24mm f/2.8 GM", "Sony", "12-24mm", "f/2.8",
        -0.38, 0.09, -1.6, 2.0, 0.55, 0.30,
        "Ultra-wide zoom. Strong barrel at 12mm"),
    "Sony FE 24-70mm f/2.8 GM II": _lp(
        "Sony 24-70mm f/2.8 GM II", "Sony", "24-70mm", "f/2.8",
        -0.06, 0.008, -0.4, 0.5, 0.28, 0.50,
        "Best-in-class standard zoom. Remarkably compact"),
    "Sony FE 70-200mm f/2.8 GM II": _lp(
        "Sony 70-200mm f/2.8 GM II", "Sony", "70-200mm", "f/2.8",
        0.03, -0.004, -0.15, 0.18, 0.15, 0.63,
        "Lightest in class. Excellent correction throughout"),
    "Sony Zeiss Sonnar T* 55mm f/1.8 ZA": _lp(
        "Sony Zeiss 55mm f/1.8", "Sony", "55mm", "f/1.8",
        -0.01, 0.0, -0.3, 0.35, 0.25, 0.55,
        "Zeiss-designed. Sharp with subtle character"),
}

# =============================================================================
# LEICA
# =============================================================================

LEICA = {
    "Leica Summicron-M 28mm f/2 ASPH": _lp(
        "Summicron-M 28mm f/2", "Leica", "28mm", "f/2",
        -0.10, 0.015, -0.7, 0.8, 0.45, 0.40,
        "Compact M wide. Barrel distortion typical of rangefinder wides"),
    "Leica Summicron-M 35mm f/2 ASPH": _lp(
        "Summicron-M 35mm f/2", "Leica", "35mm", "f/2",
        -0.04, 0.005, -0.4, 0.5, 0.35, 0.48,
        "The classic M lens. Benchmark for 35mm rendering"),
    "Leica Summilux-M 35mm f/1.4 ASPH": _lp(
        "Summilux-M 35mm f/1.4", "Leica", "35mm", "f/1.4",
        -0.05, 0.006, -0.6, 0.7, 0.50, 0.38,
        "Fast M 35. More vignette and character wide open"),
    "Leica Summicron-M 50mm f/2": _lp(
        "Summicron-M 50mm f/2", "Leica", "50mm", "f/2",
        -0.008, 0.0, -0.25, 0.3, 0.25, 0.55,
        "The quintessential M lens. Clean, sharp, timeless"),
    "Leica Summilux-M 50mm f/1.4 ASPH": _lp(
        "Summilux-M 50mm f/1.4", "Leica", "50mm", "f/1.4",
        -0.012, 0.0, -0.35, 0.4, 0.40, 0.42,
        "Fast fifty with Leica character. Glow wide open"),
    "Leica Noctilux-M 50mm f/0.95 ASPH": _lp(
        "Noctilux-M 50mm f/0.95", "Leica", "50mm", "f/0.95",
        -0.02, 0.0, -0.8, 1.0, 0.65, 0.32,
        "The Noctilux. Extreme vignette and CA wide open, legendary rendering"),
    "Leica Elmarit-M 28mm f/2.8 ASPH": _lp(
        "Elmarit-M 28mm f/2.8", "Leica", "28mm", "f/2.8",
        -0.09, 0.012, -0.5, 0.6, 0.35, 0.45,
        "Compact M wide. Less vignette than the Summicron"),
    "Leica Elmarit-M 90mm f/2.8": _lp(
        "Elmarit-M 90mm f/2.8", "Leica", "90mm", "f/2.8",
        0.015, 0.0, -0.15, 0.18, 0.15, 0.62,
        "M portrait lens. Very clean, slight pincushion"),
    "Leica APO-Summicron-M 50mm f/2 ASPH": _lp(
        "APO-Summicron-M 50mm f/2", "Leica", "50mm", "f/2",
        -0.005, 0.0, -0.08, 0.1, 0.18, 0.60,
        "The holy grail. Near-zero CA, virtually perfect correction"),
    "Leica Super-Elmar-M 21mm f/3.4 ASPH": _lp(
        "Super-Elmar-M 21mm f/3.4", "Leica", "21mm", "f/3.4",
        -0.18, 0.03, -0.8, 1.0, 0.45, 0.38,
        "Ultra-wide M. Excellent for its focal length, moderate barrel"),
}

# =============================================================================
# ZEISS
# =============================================================================

ZEISS = {
    "Zeiss Otus 55mm f/1.4": _lp(
        "Zeiss Otus 55mm f/1.4", "Zeiss", "55mm", "f/1.4",
        -0.008, 0.0, -0.15, 0.18, 0.25, 0.55,
        "Reference-grade. One of the best-corrected lenses ever made"),
    "Zeiss Otus 85mm f/1.4": _lp(
        "Zeiss Otus 85mm f/1.4", "Zeiss", "85mm", "f/1.4",
        0.008, 0.0, -0.1, 0.12, 0.20, 0.58,
        "Reference portrait. Nearly zero aberrations at any aperture"),
    "Zeiss Milvus 35mm f/1.4": _lp(
        "Zeiss Milvus 35mm f/1.4", "Zeiss", "35mm", "f/1.4",
        -0.05, 0.006, -0.45, 0.55, 0.38, 0.45,
        "Modern Distagon design. Excellent but some CA wide open"),
    "Zeiss Milvus 50mm f/1.4": _lp(
        "Zeiss Milvus 50mm f/1.4", "Zeiss", "50mm", "f/1.4",
        -0.012, 0.0, -0.3, 0.35, 0.30, 0.52,
        "Planar design. Classic Zeiss rendering, well corrected"),
    "Zeiss Milvus 85mm f/1.4": _lp(
        "Zeiss Milvus 85mm f/1.4", "Zeiss", "85mm", "f/1.4",
        0.01, 0.0, -0.18, 0.22, 0.28, 0.55,
        "Planar portrait. Beautiful bokeh, very clean"),
    "Zeiss Batis 25mm f/2": _lp(
        "Zeiss Batis 25mm f/2", "Zeiss", "25mm", "f/2",
        -0.12, 0.018, -0.6, 0.75, 0.35, 0.45,
        "E-mount wide. Compact, well-corrected Distagon"),
    "Zeiss Batis 85mm f/1.8": _lp(
        "Zeiss Batis 85mm f/1.8", "Zeiss", "85mm", "f/1.8",
        0.008, 0.0, -0.15, 0.18, 0.22, 0.58,
        "E-mount portrait. Sonnnar design, smooth bokeh"),
    "Zeiss Loxia 50mm f/2": _lp(
        "Zeiss Loxia 50mm f/2", "Zeiss", "50mm", "f/2",
        -0.01, 0.0, -0.2, 0.25, 0.22, 0.55,
        "Manual focus E-mount. Planar design, compact and sharp"),
}

# =============================================================================
# SIGMA (ART series + others)
# =============================================================================

SIGMA = {
    "Sigma 14mm f/1.8 DG HSM Art": _lp(
        "Sigma 14mm f/1.8 Art", "Sigma", "14mm", "f/1.8",
        -0.38, 0.09, -1.8, 2.2, 0.55, 0.30,
        "Unique ultra-wide. Strong barrel, heavy CA, dramatic"),
    "Sigma 20mm f/1.4 DG HSM Art": _lp(
        "Sigma 20mm f/1.4 Art", "Sigma", "20mm", "f/1.4",
        -0.20, 0.04, -1.2, 1.5, 0.50, 0.35,
        "Fast wide Art. Barrel and vignette, astro favorite"),
    "Sigma 24mm f/1.4 DG HSM Art": _lp(
        "Sigma 24mm f/1.4 Art", "Sigma", "24mm", "f/1.4",
        -0.11, 0.015, -0.8, 1.0, 0.45, 0.40,
        "Affordable fast wide. Good correction for the price"),
    "Sigma 35mm f/1.4 DG HSM Art": _lp(
        "Sigma 35mm f/1.4 Art", "Sigma", "35mm", "f/1.4",
        -0.05, 0.006, -0.5, 0.6, 0.38, 0.45,
        "The lens that launched the Art line. Still excellent"),
    "Sigma 50mm f/1.4 DG HSM Art": _lp(
        "Sigma 50mm f/1.4 Art", "Sigma", "50mm", "f/1.4",
        -0.01, 0.0, -0.3, 0.35, 0.30, 0.50,
        "Reference fifty. Matches or beats Canon/Nikon equivalents"),
    "Sigma 85mm f/1.4 DG HSM Art": _lp(
        "Sigma 85mm f/1.4 Art", "Sigma", "85mm", "f/1.4",
        0.01, 0.0, -0.18, 0.22, 0.25, 0.55,
        "Best-in-class portrait. Extremely sharp, clean bokeh"),
    "Sigma 105mm f/1.4 DG HSM Art": _lp(
        "Sigma 105mm f/1.4 Art", "Sigma", "105mm", "f/1.4",
        0.015, 0.0, -0.12, 0.15, 0.22, 0.58,
        "The Bokeh Master. Massive but optically superb"),
    "Sigma 135mm f/1.8 DG HSM Art": _lp(
        "Sigma 135mm f/1.8 Art", "Sigma", "135mm", "f/1.8",
        0.025, -0.003, -0.1, 0.12, 0.15, 0.63,
        "Sharpest 135mm available. Almost zero aberrations"),
    "Sigma 24-70mm f/2.8 DG DN Art": _lp(
        "Sigma 24-70mm f/2.8 Art", "Sigma", "24-70mm", "f/2.8",
        -0.07, 0.01, -0.5, 0.6, 0.30, 0.48,
        "Mirrorless standard zoom. Rivals first-party options"),
}

# =============================================================================
# FUJIFILM (XF + GF)
# =============================================================================

FUJIFILM = {
    "Fujifilm XF 23mm f/1.4 R": _lp(
        "Fuji XF 23mm f/1.4", "Fujifilm", "23mm", "f/1.4",
        -0.06, 0.008, -0.6, 0.7, 0.40, 0.42,
        "Classic X-mount wide. ~35mm equiv. Character wide open"),
    "Fujifilm XF 23mm f/2 R WR": _lp(
        "Fuji XF 23mm f/2 WR", "Fujifilm", "23mm", "f/2",
        -0.05, 0.006, -0.4, 0.5, 0.28, 0.50,
        "Compact weather-sealed wide. Clean and sharp"),
    "Fujifilm XF 35mm f/1.4 R": _lp(
        "Fuji XF 35mm f/1.4", "Fujifilm", "35mm", "f/1.4",
        -0.02, 0.002, -0.4, 0.5, 0.35, 0.48,
        "~50mm equiv. The classic Fuji rendering lens"),
    "Fujifilm XF 35mm f/2 R WR": _lp(
        "Fuji XF 35mm f/2 WR", "Fujifilm", "35mm", "f/2",
        -0.015, 0.0, -0.25, 0.3, 0.22, 0.55,
        "Compact normal. Very well corrected for its size"),
    "Fujifilm XF 56mm f/1.2 R": _lp(
        "Fuji XF 56mm f/1.2", "Fujifilm", "56mm", "f/1.2",
        0.005, 0.0, -0.3, 0.35, 0.40, 0.42,
        "~85mm equiv portrait. Dreamy wide open, gorgeous bokeh"),
    "Fujifilm XF 56mm f/1.2 R WR (II)": _lp(
        "Fuji XF 56mm f/1.2 II", "Fujifilm", "56mm", "f/1.2",
        0.003, 0.0, -0.15, 0.2, 0.30, 0.50,
        "Updated portrait lens. Better corrected, faster AF"),
    "Fujifilm XF 90mm f/2 R LM WR": _lp(
        "Fuji XF 90mm f/2 WR", "Fujifilm", "90mm", "f/2",
        0.012, 0.0, -0.12, 0.15, 0.15, 0.62,
        "~135mm equiv. Incredibly sharp, minimal aberrations"),
    "Fujifilm XF 16-55mm f/2.8 R LM WR": _lp(
        "Fuji XF 16-55mm f/2.8", "Fujifilm", "16-55mm", "f/2.8",
        -0.12, 0.02, -0.7, 0.85, 0.30, 0.45,
        "Pro standard zoom. Barrel at 16mm, well corrected at 55mm"),
    "Fujifilm GF 80mm f/1.7 R WR": _lp(
        "Fuji GF 80mm f/1.7", "Fujifilm", "80mm (GFX)", "f/1.7",
        0.005, 0.0, -0.15, 0.18, 0.25, 0.55,
        "Medium format ~63mm equiv. Stunning resolution and bokeh"),
    "Fujifilm GF 110mm f/2 R LM WR": _lp(
        "Fuji GF 110mm f/2", "Fujifilm", "110mm (GFX)", "f/2",
        0.01, 0.0, -0.1, 0.12, 0.18, 0.60,
        "Medium format portrait. ~87mm equiv. Reference quality"),
}

# =============================================================================
# VOIGTLANDER
# =============================================================================

VOIGTLANDER = {
    "Voigtlander Nokton 35mm f/1.2 ASPH": _lp(
        "Nokton 35mm f/1.2", "Voigtlander", "35mm", "f/1.2",
        -0.06, 0.008, -0.7, 0.85, 0.55, 0.35,
        "Ultra-fast M-mount. Heavy vignette, dreamy character"),
    "Voigtlander Nokton 40mm f/1.2 ASPH": _lp(
        "Nokton 40mm f/1.2", "Voigtlander", "40mm", "f/1.2",
        -0.03, 0.003, -0.5, 0.6, 0.50, 0.38,
        "Compact ultra-fast. Street photographer's dream"),
    "Voigtlander Nokton 50mm f/1.1": _lp(
        "Nokton 50mm f/1.1", "Voigtlander", "50mm", "f/1.1",
        -0.015, 0.0, -0.6, 0.7, 0.55, 0.35,
        "M-mount ultra-fast. Heavy vignette, vintage rendering"),
    "Voigtlander Nokton 50mm f/1.5 ASPH": _lp(
        "Nokton 50mm f/1.5", "Voigtlander", "50mm", "f/1.5",
        -0.01, 0.0, -0.3, 0.4, 0.35, 0.45,
        "Modern classic fifty. Good correction, Leica-compatible"),
    "Voigtlander APO-Lanthar 50mm f/2 ASPH": _lp(
        "APO-Lanthar 50mm f/2", "Voigtlander", "50mm", "f/2",
        -0.005, 0.0, -0.06, 0.08, 0.15, 0.62,
        "Apochromatic. Near-zero CA, rivals Leica APO-Summicron"),
    "Voigtlander Ultra Wide-Heliar 12mm f/5.6": _lp(
        "Ultra Wide-Heliar 12mm f/5.6", "Voigtlander", "12mm", "f/5.6",
        -0.40, 0.10, -1.5, 1.8, 0.40, 0.35,
        "Extreme ultra-wide. Strong barrel, unique perspective"),
    "Voigtlander Color-Skopar 21mm f/3.5": _lp(
        "Color-Skopar 21mm f/3.5", "Voigtlander", "21mm", "f/3.5",
        -0.15, 0.025, -0.7, 0.85, 0.30, 0.45,
        "Tiny M-mount wide. Impressive correction for the size"),
}

# =============================================================================
# VINTAGE / CLASSIC
# =============================================================================

VINTAGE = {
    "Helios 44-2 58mm f/2": _lp(
        "Helios 44-2 58mm f/2", "Vintage", "58mm", "f/2",
        -0.02, 0.005, -0.8, 1.0, 0.45, 0.38,
        "Soviet swirly bokeh legend. Strong CA, field curvature"),
    "Jupiter-8 50mm f/2": _lp(
        "Jupiter-8 50mm f/2", "Vintage", "50mm", "f/2",
        -0.03, 0.006, -0.9, 1.1, 0.50, 0.35,
        "Sonnar copy. Low contrast wide open, vintage character"),
    "Canon FD 50mm f/1.4 SSC": _lp(
        "Canon FD 50mm f/1.4 SSC", "Vintage", "50mm", "f/1.4",
        -0.02, 0.002, -0.7, 0.8, 0.45, 0.40,
        "70s Canon classic. Warm rendering, moderate flaws"),
    "Canon FD 85mm f/1.2L": _lp(
        "Canon FD 85mm f/1.2L", "Vintage", "85mm", "f/1.2",
        0.01, 0.0, -0.6, 0.7, 0.55, 0.35,
        "Legendary aspherical portrait. Dreamy wide open"),
    "Nikon Nikkor 50mm f/1.4 AI-S": _lp(
        "Nikkor 50mm f/1.4 AI-S", "Vintage", "50mm", "f/1.4",
        -0.015, 0.0, -0.6, 0.7, 0.40, 0.42,
        "Manual focus classic. Clean, well-built, timeless"),
    "Nikon Nikkor 105mm f/2.5 AI-S": _lp(
        "Nikkor 105mm f/2.5 AI-S", "Vintage", "105mm", "f/2.5",
        0.02, 0.0, -0.2, 0.25, 0.18, 0.60,
        "The Afghan Girl lens. Portrait legend, beautiful rendering"),
    "Pentax SMC Takumar 50mm f/1.4": _lp(
        "Takumar 50mm f/1.4", "Vintage", "50mm", "f/1.4",
        -0.02, 0.003, -0.7, 0.85, 0.42, 0.40,
        "Radioactive classic. Warm yellowing, beautiful flare"),
    "Pentax SMC Takumar 55mm f/1.8": _lp(
        "Takumar 55mm f/1.8", "Vintage", "55mm", "f/1.8",
        -0.015, 0.002, -0.5, 0.6, 0.32, 0.48,
        "Budget classic. Sharp stopped down, characterful wide open"),
    "Meyer-Optik Trioplan 100mm f/2.8": _lp(
        "Trioplan 100mm f/2.8", "Vintage", "100mm", "f/2.8",
        0.02, 0.0, -0.4, 0.5, 0.25, 0.55,
        "Soap bubble bokeh. Unique 3-element design, artistic tool"),
    "Minolta MC Rokkor 58mm f/1.2": _lp(
        "Rokkor 58mm f/1.2", "Vintage", "58mm", "f/1.2",
        -0.02, 0.003, -0.8, 1.0, 0.55, 0.35,
        "Ultra-fast Minolta. Dreamy wide open, strong vignette"),
    "Leica Summitar 50mm f/2": _lp(
        "Leica Summitar 50mm f/2", "Vintage", "50mm", "f/2",
        -0.02, 0.003, -0.9, 1.1, 0.50, 0.38,
        "1940s-50s Leica. Low contrast, flare-prone, romantic rendering"),
    "Petzval 85mm f/2.2": _lp(
        "Petzval 85mm f/2.2", "Vintage", "85mm", "f/2.2",
        0.015, 0.0, -0.6, 0.8, 0.50, 0.35,
        "19th century design. Extreme swirl bokeh, sharp center"),
    "Biotar 58mm f/2": _lp(
        "Biotar 58mm f/2", "Vintage", "58mm", "f/2",
        -0.02, 0.004, -0.7, 0.9, 0.42, 0.40,
        "Pre-war Zeiss. Helios ancestor, swirly bokeh original"),
}

# =============================================================================
# CINEMA
# =============================================================================

CINEMA = {
    "Cooke S4/i 25mm T2": _lp(
        "Cooke S4/i 25mm T2", "Cinema", "25mm", "T2",
        -0.08, 0.01, -0.3, 0.35, 0.25, 0.50,
        "The Cooke Look. Warm, gentle, flattering skin tones"),
    "Cooke S4/i 50mm T2": _lp(
        "Cooke S4/i 50mm T2", "Cinema", "50mm", "T2",
        -0.01, 0.0, -0.15, 0.18, 0.15, 0.60,
        "Cinema standard. Matched set, minimal aberrations"),
    "Cooke S4/i 100mm T2": _lp(
        "Cooke S4/i 100mm T2", "Cinema", "100mm", "T2",
        0.015, 0.0, -0.08, 0.1, 0.10, 0.68,
        "Cinema portrait. Clean with the Cooke warmth"),
    "Zeiss Master Prime 35mm T1.3": _lp(
        "Zeiss Master Prime 35mm T1.3", "Cinema", "35mm", "T1.3",
        -0.03, 0.003, -0.15, 0.18, 0.20, 0.55,
        "Reference cinema glass. Near-perfect correction"),
    "Zeiss Master Prime 50mm T1.3": _lp(
        "Zeiss Master Prime 50mm T1.3", "Cinema", "50mm", "T1.3",
        -0.008, 0.0, -0.08, 0.1, 0.15, 0.60,
        "Cinema benchmark. Extremely well corrected"),
    "Zeiss CP.3 85mm T2.1": _lp(
        "Zeiss CP.3 85mm T2.1", "Cinema", "85mm", "T2.1",
        0.008, 0.0, -0.1, 0.12, 0.12, 0.65,
        "Affordable cinema prime. Good all-round performance"),
    "ARRI/Zeiss Master Anamorphic 50mm T1.9": _lp(
        "ARRI Master Anamorphic 50mm", "Cinema", "50mm", "T1.9",
        -0.06, 0.015, -0.5, 0.65, 0.30, 0.45,
        "Anamorphic cinema. Oval bokeh, horizontal flares, 2x squeeze"),
    "Panavision Primo 50mm T1.6": _lp(
        "Panavision Primo 50mm T1.6", "Cinema", "50mm", "T1.6",
        -0.01, 0.0, -0.1, 0.12, 0.12, 0.62,
        "Hollywood standard. Neutral, clean, consistent"),
    "Panavision C-Series Anamorphic 50mm T2.3": _lp(
        "Panavision C-Series 50mm", "Cinema", "50mm", "T2.3",
        -0.08, 0.02, -0.8, 1.0, 0.40, 0.38,
        "Vintage anamorphic character. Flares, aberrations, organic"),
    "Canon K35 50mm T1.3": _lp(
        "Canon K35 50mm T1.3", "Cinema", "50mm", "T1.3",
        -0.015, 0.002, -0.6, 0.75, 0.40, 0.42,
        "1970s cinema classic. Used on Alien, Blade Runner. Warm flares"),
}


# =============================================================================
# MASTER REGISTRY
# =============================================================================

ALL_PROFILES: Dict[str, Dict[str, LensProfile]] = {
    "Canon": CANON,
    "Nikon": NIKON,
    "Sony": SONY,
    "Leica": LEICA,
    "Zeiss": ZEISS,
    "Sigma": SIGMA,
    "Fujifilm": FUJIFILM,
    "Voigtlander": VOIGTLANDER,
    "Vintage": VINTAGE,
    "Cinema": CINEMA,
}

# Flat lookup: "Canon / Canon EF 50mm f/1.4 USM" → LensProfile
LENS_PROFILES_FLAT: Dict[str, LensProfile] = {}
for brand_name, brand_lenses in ALL_PROFILES.items():
    for lens_key, profile in brand_lenses.items():
        flat_key = f"{brand_name} / {lens_key}"
        LENS_PROFILES_FLAT[flat_key] = profile

LENS_PROFILE_NAMES = sorted(LENS_PROFILES_FLAT.keys())

# Brand list for filtering
BRAND_NAMES = sorted(ALL_PROFILES.keys())
