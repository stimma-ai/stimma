"""Localized browser context, using the exact delivered 16px favicon."""
from PIL import Image, ImageDraw

from packages.mockups.fonts import font
from packages.mockups.draw import ellipsize


class _BrowserDraw:
    """Logical coordinates with native 2x text and chrome rasterization."""
    def __init__(self, image):
        self.draw = ImageDraw.Draw(image)

    def textlength(self, text, *, font):
        return self.draw.textlength(text, font=font.font_variant(size=font.size * 2)) / 2

    def __getattr__(self, name):
        def draw(xy, *args, **kwargs):
            xy = tuple(value * 2 for value in xy)
            for key in ('radius', 'width'):
                if key in kwargs:
                    kwargs[key] *= 2
            if 'font' in kwargs:
                face = kwargs['font']
                kwargs['font'] = face.font_variant(size=face.size * 2)
            return getattr(self.draw, name)(xy, *args, **kwargs)
        return draw


def browser_preview(favicon: Image.Image, label: str, *, mode: str = 'light') -> Image.Image:
    # Draw at logical browser pixels, then expose a crisp 2x study image.
    # The favicon is never refitted, recolored or masked here.
    dark = mode == 'dark'
    surround, surface, field, ink, muted = (
        ('#202124', '#35363a', '#202124', '#e8eaed', '#9aa0a6') if dark else
        ('#dee1e6', '#ffffff', '#f1f3f4', '#202124', '#5f6368')
    )
    image = Image.new('RGB', (1440, 320), surround)
    draw = _BrowserDraw(image)
    draw.rounded_rectangle((12, 8, 268, 47), radius=12, fill=surface)
    draw.rectangle((12, 31, 268, 47), fill=surface)
    favicon = favicon.resize((32, 32), Image.Resampling.NEAREST)
    image.paste(favicon, (56, 38), favicon.getchannel('A') if favicon.mode == 'RGBA' else None)
    title = ellipsize(draw, ' '.join(label.split()), font('regular', 13), 178)
    draw.text((54, 19), title, font=font('regular', 13), fill=ink)
    draw.line((246, 23, 252, 29), fill=muted, width=1)
    draw.line((252, 23, 246, 29), fill=muted, width=1)
    draw.line((287, 22, 287, 34), fill=muted, width=1)
    draw.line((281, 28, 293, 28), fill=muted, width=1)
    draw.rectangle((0, 46, 720, 160), fill=surface)
    draw.line((27, 63, 21, 69, 27, 75), fill=muted, width=2)
    draw.line((21, 69, 34, 69), fill=muted, width=2)
    draw.line((53, 63, 59, 69, 53, 75), fill=muted, width=2)
    draw.line((47, 69, 59, 69), fill=muted, width=2)
    draw.arc((77, 62, 91, 76), 35, 320, fill=muted, width=2)
    draw.rounded_rectangle((108, 53, 658, 85), radius=16, fill=field)
    draw.text((126, 61), 'Search or enter address', font=font('regular', 13), fill=muted)
    for y in (64, 69, 74):
        draw.ellipse((686, y, 688, y+2), fill=muted)
    # A quiet page edge keeps the focus on the tab, without inventing a site.
    draw.line((0, 94, 720, 94), fill=field)
    return image
