"""Measured source bounds and explicit platform composition for icon recipes.

Optical occupancy is a kit policy, not a claim that vendors prescribe one
percentage for every mark. Android's 66dp circle is a platform constraint.
"""
from dataclasses import dataclass
import math

import numpy as np
from PIL import Image

import icon_spec


@dataclass(frozen=True)
class Artwork:
    bounds: tuple[float, float, float, float]
    mark: bool
    backdrop: str | None = None

    @classmethod
    def measure(cls, image: Image.Image, fit: str = 'auto') -> 'Artwork':
        if fit == 'canvas':
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

    def render_size(self, px: int) -> int:
        fraction = max(self.bounds[2]-self.bounds[0], self.bounds[3]-self.bounds[1])
        return min(8192, max(px, math.ceil(px/max(fraction, .01)))) if self.mark else px

    def compose(self, image: Image.Image, spec: icon_spec.IconImage,
                platform: str, background: str) -> Image.Image:
        art = self.crop(image)
        bg = self.backdrop or background
        adaptive = platform == 'android' and 'foreground' in spec.path
        if adaptive:
            # Fit actual visible pixels inside the guaranteed circle, not a
            # square whose corners would still be clipped by a round launcher.
            a = np.array(art.getchannel('A'))
            ys, xs = np.where(a > 8)
            radius = np.max(np.hypot(xs-(art.width-1)/2, ys-(art.height-1)/2)) if len(xs) else 1
            scale = (spec.px * 66/108 / 2) / max(radius, 1)
            inner = max(1, round(max(art.size)*scale))
        elif platform == 'macos':
            inner = max(1, round(spec.px * icon_spec.MACOS_SAFE_AREA * (.86 if self.mark else 1)))
        else:
            occupancy = .86 if spec.opaque else (.98 if platform == 'windows' else .92)
            inner = max(1, round(spec.px * (occupancy if self.mark else 1)))
        factor = inner/max(art.size)
        art = art.resize((max(1, round(art.width*factor)), max(1, round(art.height*factor))), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (spec.px, spec.px))
        if platform == 'macos':
            badge_size = max(1, round(spec.px * icon_spec.MACOS_SAFE_AREA))
            badge = Image.new('RGBA', (badge_size, badge_size), bg)
            badge.putalpha(icon_spec.rounded_mask(badge_size))
            canvas.alpha_composite(badge, ((spec.px-badge_size)//2, (spec.px-badge_size)//2))
        canvas.alpha_composite(art, ((spec.px-art.width)//2, (spec.px-art.height)//2))
        if spec.opaque:
            flat = Image.new('RGBA', canvas.size, bg)
            flat.alpha_composite(canvas)
            return flat.convert('RGB')
        return canvas
