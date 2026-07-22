"""
Cross-processing curve data for ComfyUI-Darkroom.

Cross-processing = developing film in the wrong chemistry.
Produces extreme, unpredictable color shifts.

E-6 in C-41: slide film in negative chemistry → extreme saturation, color shifts
C-41 in E-6: negative film in slide chemistry → muted, orange/amber cast
"""

from dataclasses import dataclass
from typing import Tuple

from .color_stocks import CurveParams


@dataclass(frozen=True)
class CrossProcessProfile:
    name: str
    r_curve: CurveParams
    g_curve: CurveParams
    b_curve: CurveParams
    saturation: float
    description: str


E6_IN_C41 = CrossProcessProfile(
    name="E-6 in C-41",
    # Slide film developed as negative. Classic cross-process look:
    # - Extreme contrast boost
    # - Green-yellow color shift
    # - Blue channel heavily suppressed in shadows
    # - Red channel boosted in highlights
    # - Very high saturation
    r_curve=CurveParams(toe_power=1.2, shoulder_power=1.3, slope=1.30, pivot_x=0.20, pivot_y=0.22),
    g_curve=CurveParams(toe_power=1.0, shoulder_power=1.5, slope=1.25, pivot_x=0.18, pivot_y=0.22),
    b_curve=CurveParams(toe_power=2.0, shoulder_power=1.2, slope=0.85, pivot_x=0.18, pivot_y=0.12),
    saturation=1.35,
    description="Slide film in negative chemistry. Extreme saturation, green-yellow shift, crushed blue shadows."
)

C41_IN_E6 = CrossProcessProfile(
    name="C-41 in E-6",
    # Negative film developed as slide. The orange mask becomes visible:
    # - Low contrast
    # - Heavy orange/amber cast
    # - Muted, muddy colors
    # - Flat tonal range
    r_curve=CurveParams(toe_power=1.3, shoulder_power=1.8, slope=0.80, pivot_x=0.18, pivot_y=0.22),
    g_curve=CurveParams(toe_power=1.4, shoulder_power=1.7, slope=0.75, pivot_x=0.18, pivot_y=0.17),
    b_curve=CurveParams(toe_power=1.6, shoulder_power=1.6, slope=0.65, pivot_x=0.18, pivot_y=0.12),
    saturation=0.70,
    description="Negative film in slide chemistry. Muted, orange cast, flat contrast. The orange mask shows."
)


CROSS_PROCESS_PROFILES = {
    "E-6 in C-41 (slide → negative)": E6_IN_C41,
    "C-41 in E-6 (negative → slide)": C41_IN_E6,
}

CROSS_PROCESS_NAMES = list(CROSS_PROCESS_PROFILES.keys())
