"""Measured source bounds and explicit platform composition for icon recipes.

Optical occupancy is a default recipe policy, not a claim that vendors prescribe one
percentage for every mark. Android's 66dp circle is a platform constraint.
"""
from dataclasses import dataclass
import math

import numpy as np
from PIL import Image

import icon_spec

# How much of a platform-drawn tile (iOS, macOS badge, legacy Android, Apple
# touch icon) a detected mark fills by default. Apple's own tiles keep the
# subject inside roughly two thirds of the shape; .86 slammed wordmarks into
# the corners.
TILE_FILL = .64
# Bare-mark platforms draw no tile, so the mark is the icon and fills the canvas.
WINDOWS_FILL = .98
BARE_FILL = .92
# Below this share of the master, a mark on a uniform ground is too light to
# ship as-is: canvas fit refuses rather than delivering a tiny icon.
CANVAS_FIT_FLOOR = .5
# Bare-mark platforms (Windows, Linux, web) draw the icon straight onto UI
# chrome that may be light or dark. A mark ships bare only when its ink
# separates from both; otherwise it keeps its ground as a rounded tile, so a
# black wordmark does not vanish in a dark dock or browser tab.
LIGHT_CHROME = (243, 243, 243)
DARK_CHROME = (43, 43, 43)
BARE_PLATFORMS = ('windows', 'linux', 'web')


@dataclass(frozen=True)
class Artwork:
    bounds: tuple[float, float, float, float]
    mark: bool
    backdrop: str | None = None

    @classmethod
    def measure(cls, image: Image.Image, fit: str = 'auto') -> 'Artwork':
        if fit == 'canvas':
            measured = cls.measure(image, 'auto')
            if measured.mark:
                x0, y0, x1, y1 = measured.bounds
                extent = max(x1-x0, y1-y0)
                if extent < CANVAS_FIT_FLOOR:
                    from packages.recipes import RecipeError
                    raise RecipeError(
                        f"artwork_fit='canvas' would ship an undersized icon: the visible mark "
                        f"spans {extent:.0%} of the master, and every platform would inherit that "
                        f"padding. Use the default artwork_fit='auto', which fits the mark for each "
                        f"platform; for a deliberately lighter look, keep 'auto' and lower a "
                        f"platform's *_scale instead.")
            return cls((0, 0, 1, 1), False)
        sample = image.convert('RGBA')
        sample.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        pixels = np.asarray(sample)
        alpha = pixels[:, :, 3]
        backdrop = None
        visible = alpha > 8
        if alpha.min() == 255:
            edge = np.concatenate((pixels[0, :, :3], pixels[-1, :, :3],
                                   pixels[:, 0, :3], pixels[:, -1, :3])).astype(int)
            color = np.median(edge, axis=0).astype(int)
            if np.max(np.abs(edge - color)) > 8:
                return cls((0, 0, 1, 1), False)
            visible = np.max(np.abs(pixels[:, :, :3].astype(int) - color), axis=2) > 8
            backdrop = '#%02X%02X%02X' % tuple(color)
        ys, xs = np.where(visible)
        if not len(xs):
            return cls((0, 0, 1, 1), False)
        h, w = alpha.shape
        return cls((xs.min()/w, ys.min()/h, (xs.max()+1)/w, (ys.max()+1)/h), True, backdrop)

    def crop(self, image: Image.Image) -> Image.Image:
        image = image.convert('RGBA')
        if self.backdrop and self.mark:
            pixels = np.array(image)
            bg = np.array(icon_spec.parse_hex(self.backdrop))
            outside = np.max(np.abs(pixels[:, :, :3].astype(int) - bg), axis=2) <= 8
            pixels[outside, 3] = 0
            image = Image.fromarray(pixels)
        x0, y0, x1, y1 = self.bounds
        return image.crop((round(x0*image.width), round(y0*image.height),
                           max(round(x0*image.width)+1, round(x1*image.width)),
                           max(round(y0*image.height)+1, round(y1*image.height))))

    def keeps_ground(self, art: Image.Image) -> bool:
        """Whether a bare-mark platform should keep the ground under ``art``."""
        if not self.mark:
            return False
        ink = icon_spec.ink_color(art)
        if ink is None:
            return False
        return min(icon_spec.contrast_ratio(ink, LIGHT_CHROME),
                   icon_spec.contrast_ratio(ink, DARK_CHROME)) < icon_spec.MIN_ICON_CONTRAST

    def render_size(self, px: int) -> int:
        fraction = max(self.bounds[2]-self.bounds[0], self.bounds[3]-self.bounds[1])
        return min(8192, max(px, math.ceil(px/max(fraction, .01)))) if self.mark else px

    def compose(self, image: Image.Image, spec: icon_spec.IconImage,
                platform: str, background: str, *, scale: float = 1.0) -> Image.Image:
        art = self.crop(image)
        bg = self.backdrop or background
        ground = False
        adaptive = platform == 'android' and 'foreground' in spec.path
        if adaptive:
            # Fit actual visible pixels inside the guaranteed circle, not a
            # square whose corners would still be clipped by a round launcher.
            a = np.array(art.getchannel('A'))
            ys, xs = np.where(a > 8)
            radius = np.max(np.hypot(xs-(art.width-1)/2, ys-(art.height-1)/2)) if len(xs) else 1
            fit = (spec.px * 66/108 / 2) / max(radius, 1)
            inner = max(1, round(max(art.size)*fit))
        elif platform == 'macos':
            inner = max(1, round(spec.px * icon_spec.MACOS_SAFE_AREA * (TILE_FILL if self.mark else 1)))
        else:
            occupancy = TILE_FILL if spec.opaque else (WINDOWS_FILL if platform == 'windows' else BARE_FILL)
            ground = platform in BARE_PLATFORMS and not spec.opaque and self.keeps_ground(art)
            if ground:
                tile_px = max(1, round(spec.px * occupancy))
                occupancy *= TILE_FILL
            inner = max(1, round(spec.px * (occupancy if self.mark else 1)))
        from packages.recipes import RecipeError

        limit = spec.px * (icon_spec.MACOS_SAFE_AREA if platform == 'macos' else 1)
        if not math.isfinite(scale) or scale <= 0:
            raise RecipeError(f"{platform}_scale must be a finite positive number")
        if (adaptive and scale > 1) or inner * scale > limit + .5:
            constraint = "adaptive safe zone" if adaptive else "platform canvas"
            raise RecipeError(f"{platform}_scale={scale:g} exceeds the {constraint}; use a smaller scale")
        inner = max(1, round(inner * scale))
        factor = inner/max(art.size)
        art = art.resize((max(1, round(art.width*factor)), max(1, round(art.height*factor))), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (spec.px, spec.px))
        if platform in BARE_PLATFORMS and ground:
            tile = Image.new('RGBA', (tile_px, tile_px), bg)
            tile.putalpha(icon_spec.rounded_mask(tile_px))
            canvas.alpha_composite(tile, ((spec.px-tile_px)//2, (spec.px-tile_px)//2))
        if platform == 'macos':
            badge_size = max(1, round(spec.px * icon_spec.MACOS_SAFE_AREA))
            badge = Image.new('RGBA', (badge_size, badge_size), bg)
            badge.putalpha(icon_spec.rounded_mask(badge_size))
            canvas.alpha_composite(badge, ((spec.px-badge_size)//2, (spec.px-badge_size)//2))
        canvas.alpha_composite(art, ((spec.px-art.width)//2, (spec.px-art.height)//2))
        if platform == 'macos':
            # The Dock draws an .icns as-is: clip canvas-fit art to the tile's
            # rounded corners rather than letting it cover the badge.
            canvas = icon_spec.clip_macos_tile(canvas)
        if spec.opaque:
            flat = Image.new('RGBA', canvas.size, bg)
            flat.alpha_composite(canvas)
            return flat.convert('RGB')
        return canvas
