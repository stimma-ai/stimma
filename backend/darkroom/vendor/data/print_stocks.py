"""
Cinema print stock profiles for ComfyUI-Darkroom.

Print stocks are the second stage of the photochemical chain.
Camera negative → Print stock = the projected cinema look.

The negative's characteristic curve captures the scene;
the print stock's curve shapes how it's displayed.
This two-curve interaction is what gives cinema its unique character.
"""

from dataclasses import dataclass
from typing import Tuple

from .color_stocks import CurveParams


@dataclass(frozen=True)
class PrintStockProfile:
    name: str
    r_curve: CurveParams
    g_curve: CurveParams
    b_curve: CurveParams
    saturation: float
    black_density: float   # Floor for blacks (0.0 = pure black, >0 = lifted)
    description: str


KODAK_2383 = PrintStockProfile(
    name="Kodak 2383",
    # THE standard cinema print stock. Moderate contrast, warm midtones.
    # Slightly lifted blacks. This IS "the cinema look."
    r_curve=CurveParams(toe_power=1.5, shoulder_power=1.4, slope=1.10, pivot_x=0.18, pivot_y=0.18),
    g_curve=CurveParams(toe_power=1.5, shoulder_power=1.45, slope=1.08, pivot_x=0.18, pivot_y=0.18),
    b_curve=CurveParams(toe_power=1.55, shoulder_power=1.5, slope=1.05, pivot_x=0.18, pivot_y=0.17),
    saturation=1.05,
    black_density=0.03,
    description="The cinema standard. Warm midtones, controlled highlights, slightly lifted blacks."
)

KODAK_2393 = PrintStockProfile(
    name="Kodak 2393",
    # Digital intermediate print stock. More neutral than 2383.
    # Designed for DI workflows — cleaner, less warm.
    r_curve=CurveParams(toe_power=1.45, shoulder_power=1.5, slope=1.05, pivot_x=0.18, pivot_y=0.18),
    g_curve=CurveParams(toe_power=1.45, shoulder_power=1.5, slope=1.05, pivot_x=0.18, pivot_y=0.18),
    b_curve=CurveParams(toe_power=1.45, shoulder_power=1.5, slope=1.03, pivot_x=0.18, pivot_y=0.18),
    saturation=1.0,
    black_density=0.02,
    description="DI print stock. Neutral, clean. Modern cinema workflows."
)

FUJI_3513 = PrintStockProfile(
    name="Fuji 3513",
    # High contrast Fuji print stock. Punchier blacks, more saturated.
    # Slightly cooler than Kodak. Japanese cinema aesthetic.
    r_curve=CurveParams(toe_power=1.6, shoulder_power=1.35, slope=1.15, pivot_x=0.18, pivot_y=0.18),
    g_curve=CurveParams(toe_power=1.55, shoulder_power=1.4, slope=1.13, pivot_x=0.18, pivot_y=0.18),
    b_curve=CurveParams(toe_power=1.5, shoulder_power=1.45, slope=1.12, pivot_x=0.18, pivot_y=0.19),
    saturation=1.10,
    black_density=0.015,
    description="High contrast Fuji print. Deep blacks, punchy colors. Japanese cinema look."
)

FUJI_3510 = PrintStockProfile(
    name="Fuji 3510",
    # Standard Fuji print. Slightly cooler than Kodak, moderate contrast.
    r_curve=CurveParams(toe_power=1.5, shoulder_power=1.45, slope=1.08, pivot_x=0.18, pivot_y=0.18),
    g_curve=CurveParams(toe_power=1.48, shoulder_power=1.45, slope=1.07, pivot_x=0.18, pivot_y=0.18),
    b_curve=CurveParams(toe_power=1.45, shoulder_power=1.5, slope=1.06, pivot_x=0.18, pivot_y=0.19),
    saturation=1.03,
    black_density=0.025,
    description="Standard Fuji print. Cooler than Kodak, moderate contrast."
)


PRINT_STOCKS = {
    "Kodak 2383": KODAK_2383,
    "Kodak 2393": KODAK_2393,
    "Fuji 3513": FUJI_3513,
    "Fuji 3510": FUJI_3510,
}

PRINT_STOCK_NAMES = list(PRINT_STOCKS.keys())
