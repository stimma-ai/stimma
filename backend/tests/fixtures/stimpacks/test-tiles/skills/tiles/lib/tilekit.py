"""Tiny fixture helper imported by the test stimpack recipe."""

from PIL import Image


def tile(image: Image.Image, size: int, background: str) -> Image.Image:
    """Center an image on a deterministic square RGBA tile."""
    artwork = image.convert("RGBA").copy()
    artwork.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), background)
    canvas.alpha_composite(
        artwork,
        ((size - artwork.width) // 2, (size - artwork.height) // 2),
    )
    return canvas
