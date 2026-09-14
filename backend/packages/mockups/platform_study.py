"""Platform Study: fixed native surroundings, exact delivered icons and local type.

No generation, external programs, network access or demo-tree dependencies.
"""
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops

from packages.mockups.devices import _warp
from packages.mockups.fonts import font
from packages.mockups.draw import rounded_mask

ASSETS = Path(__file__).parent / 'assets' / 'platform-study'


@lru_cache(maxsize=6)
def _asset(name):
    with Image.open(ASSETS / name) as image:
        return image.convert('RGB')


def _text(draw, center, value, size, color, max_width):
    face = font('regular', size)
    value = ' '.join(value.split())
    while draw.textlength(value, font=face) > max_width:
        value = value.rstrip('…')[:-1] + '…'
    draw.text(center, value, font=face, anchor='mm', fill=color)


def _paste(canvas, icon, xy, size, radius=None):
    icon = icon.convert('RGBA').resize((size, size), Image.Resampling.LANCZOS)
    if radius is not None:
        icon.putalpha(ImageChops.multiply(icon.getchannel('A'), rounded_mask(size, size, radius)))
    canvas.paste(icon, xy, icon)


def android_icon(foreground, background):
    # AdaptiveIconDrawable displays the central 72dp of the delivered 108dp
    # layer. Its background is the same color written to the Android resource.
    fg = foreground.convert('RGBA')
    layer = Image.new('RGBA', fg.size, background)
    layer.alpha_composite(fg)
    inset = fg.width / 6
    visible = layer.crop((round(inset), round(inset), round(fg.width-inset), round(fg.height-inset)))
    return visible


def android_screen(foreground, label, background):
    screen = _asset('android-home.png').copy()
    _paste(screen, android_icon(foreground, background), (84, 690), 174, 43)
    _text(ImageDraw.Draw(screen), (171, 912), label, 30, 'white', 225)
    return screen


def android_studio_preview(foreground, label, background):
    screen = android_screen(foreground, label, background)
    # A centered punch-hole camera, rather than the iPhone's optical inset.
    draw = ImageDraw.Draw(screen)
    draw.ellipse((514, 29, 566, 81), fill='#050608')
    draw.ellipse((528, 43, 552, 67), fill='#0c1520')
    with Image.open(ASSETS / 'android-studio.png') as source:
        plate = source.convert('RGBA')
    mapped, mask = _warp(screen, 'android-studio', plate.size, assets=ASSETS, radius=110)
    reflection = np.asarray(plate.convert('RGB')).astype(float)
    mapped = 255 - (255 - mapped.astype(float)) * (1 - reflection / 255)
    display = Image.fromarray(np.uint8(np.clip(mapped, 0, 255))).convert('RGBA')
    phone = Image.composite(display, plate, mask)
    image = Image.new('RGB', (1500, 1000), '#050608')
    image.paste(phone, (500, 0), phone)
    _paste(image, android_icon(foreground, background), (100, 345), 310, 77)
    return image


def android_preview(foreground, label, background):
    screen = android_screen(foreground, label, background)
    plate = _asset('galaxy.jpg')
    w, h = screen.size
    quad = np.array([(757, 97), (1074, 89), (1080, 747), (765, 748)]) * 2.5
    rows, values = [], []
    for (x, y), (u, v) in zip(quad, [(0, 0), (w, 0), (w, h), (0, h)]):
        rows.extend([[x, y, 1, 0, 0, 0, -u*x, -u*y], [0, 0, 0, x, y, 1, -v*x, -v*y]])
        values.extend([u, v])
    coefficients = np.linalg.solve(rows, values)
    mask = Image.new('L', screen.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w-1, h-1), radius=110, fill=255)

    def warp(image):
        return image.transform(plate.size, Image.Transform.PERSPECTIVE, coefficients, Image.Resampling.BICUBIC)

    result = Image.composite(warp(screen), plate, warp(mask))
    hole = Image.new('L', plate.size)
    ImageDraw.Draw(hole).ellipse((2260, 248, 2307, 297), fill=255)
    return Image.composite(plate, result, hole.filter(ImageFilter.GaussianBlur(1)))


def macos_preview(icon, label):
    canvas = _asset('macos.png').copy()
    # macOS's complete 1024px canvas includes the platform's outer margin.
    # A 192px canvas gives the 824px tile a visible width of about 154px.
    _paste(canvas, icon, (599, 649), 192)
    face = font('regular', 58)
    label = ' '.join(label.split())
    draw = ImageDraw.Draw(canvas)
    while draw.textlength(label, font=face) > 650:
        label = label.rstrip('…')[:-1] + '…'
    cx, width = 695, round(draw.textlength(label, font=face)) + 104
    mask = Image.new('L', canvas.size)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((cx-width//2, 450, cx+width//2, 550), radius=50, fill=255)

    def cubic(p0, p1, p2, p3):
        return [tuple((1-t)**3*p0[j]+3*(1-t)**2*t*p1[j]+3*(1-t)*t*t*p2[j]+t**3*p3[j]
                      for j in [0, 1]) for t in np.linspace(0, 1, 20)]

    points = [(cx-44, 538)]
    points += cubic((cx-44, 550), (cx-24, 550), (cx-16, 573), (cx, 574))
    points += cubic((cx, 574), (cx+16, 573), (cx+24, 550), (cx+44, 550))
    points.append((cx+44, 538))
    md.polygon(points, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(.65))
    tip = Image.alpha_composite(canvas.filter(ImageFilter.GaussianBlur(12)).convert('RGBA'),
                               Image.new('RGBA', canvas.size, (8, 22, 38, 155)))
    canvas.paste(tip, (0, 0), mask)
    edge = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(3)))
    rim = Image.new('RGBA', canvas.size, (130, 194, 238, 0))
    rim.putalpha(edge.point(lambda v: int(v*.22)))
    canvas.paste(rim, (0, 0), rim)
    ImageDraw.Draw(canvas).text((cx, 501), label, font=face, anchor='mm', fill='#f4f5f7')
    return canvas


def windows_start_preview(icon, label):
    canvas = _asset('windows-start.png').copy()
    scale = 1748/1554
    _paste(canvas, icon, (round(560*scale), round(122*scale)), round(52*scale))
    _text(ImageDraw.Draw(canvas), (round(586*scale), round(199*scale)), label,
          round(22*scale), '#242424', 155)
    return canvas


def windows_taskbar_preview(icon, label):
    canvas = _asset('windows-taskbar.png').copy()
    _paste(canvas, icon, (1042, 397), 48)
    draw = ImageDraw.Draw(canvas)
    face = font('regular', 25)
    width = min(380, draw.textlength(label, font=face)+48)
    draw.rounded_rectangle((1066-width/2, 286, 1066+width/2, 343), radius=9, fill='#f7f7f7')
    _text(draw, (1066, 314), label, 25, '#202020', width-32)
    return canvas


def linux_preview(icon, label):
    canvas = _asset('ubuntu.png').copy()
    _paste(canvas, icon, (14, 397), 92)
    draw = ImageDraw.Draw(canvas)
    face = font('regular', 30)
    width = min(450, draw.textlength(label, font=face)+56)
    draw.rounded_rectangle((140, 418, 140+width, 482), radius=12, fill='#323034')
    _text(draw, (140+width/2, 450), label, 30, 'white', width-32)
    return canvas


def platform_previews(icons, label, background):
    """Yield only the requested platforms; every image uses its delivered PNG."""
    if 'android' in icons:
        yield 'platform-android-studio.png', android_studio_preview(icons['android'], label, background)
        yield 'platform-android.png', android_preview(icons['android'], label, background)
    if 'macos' in icons:
        yield 'platform-macos.png', macos_preview(icons['macos'], label)
    if 'windows' in icons:
        yield 'platform-windows-start.png', windows_start_preview(icons['windows'], label)
        yield 'platform-windows-taskbar.png', windows_taskbar_preview(icons['windows'], label)
    if 'linux' in icons:
        yield 'platform-linux.png', linux_preview(icons['linux'], label)
