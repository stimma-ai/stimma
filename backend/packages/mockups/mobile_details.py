"""Compact store and notification studies, drawn locally from delivered icons.

Illustrative platform chrome, with neutral sample text and no invented ratings,
category, publisher or product claims. Galaxy notifications use app-icon mode:
https://www.samsung.com/us/support/answer/ANS10002524/
Store action anatomy: https://developer.android.com/distribute/marketing-tools/linking-to-google-play.html
"""
from PIL import Image, ImageDraw

from packages.mockups.draw import ellipsize, rounded_mask
from packages.mockups.fonts import font
from packages.mockups.surfaces import _masked

SCALE = 3
WIDTH = 480


def _canvas(height):
    return Image.new('RGBA', (WIDTH * SCALE, height * SCALE), (0, 0, 0, 0))


def _text(draw, xy, text, size, color, width, weight='regular'):
    face = font(weight, size * SCALE)
    text = ' '.join(text.split())
    draw.text(tuple(v * SCALE for v in xy), ellipsize(draw, text, face, width * SCALE), font=face, fill=color)


def _icon(image, size, platform, mode):
    if platform == 'ios':
        return _masked(image, size * SCALE, mode=mode)
    icon = image.convert('RGBA').resize((size * SCALE, size * SCALE), Image.Resampling.LANCZOS)
    icon.putalpha(rounded_mask(icon.width, icon.height, size * SCALE * .25))
    return icon


def render_store(icon, name, platform, *, mode='light'):
    image = _canvas(100)
    draw = ImageDraw.Draw(image)
    dark = mode == 'dark'
    fg = '#f5f5f7' if dark else '#171719'
    background = '#19191c' if dark else '#ffffff'
    draw.rounded_rectangle((0, 0, image.width-1, image.height-1), radius=12*SCALE, fill=background)
    image.alpha_composite(_icon(icon, 64, platform, mode), (18*SCALE, 18*SCALE))
    _text(draw, (98, 36), name, 18, fg, 246, 'medium')
    # A visual listing example, not a claim that the app has been published.
    action = 'GET' if platform == 'ios' else 'Install'
    pill = '#303034' if dark else ('#edf3ff' if platform == 'ios' else '#d8e9ff')
    ink = '#b4ceff' if dark else ('#007aff' if platform == 'ios' else '#174ea6')
    draw.rounded_rectangle((366*SCALE, 33*SCALE, 460*SCALE, 67*SCALE), radius=17*SCALE, fill=pill)
    face = font('medium', 15*SCALE)
    draw.text((413*SCALE, 50*SCALE), action, font=face, fill=ink, anchor='mm')
    return image


def render_notification(icon, name, platform, *, mode='light'):
    image = _canvas(100)
    draw = ImageDraw.Draw(image)
    dark = mode == 'dark'
    fg, muted = ('#f5f5f7', '#b0b0b8') if dark else ('#171719', '#6b6b73')
    fill = ('#29292d' if platform == 'ios' else '#262930') if dark else ('#f0f0f4' if platform == 'ios' else '#f0f3fa')
    draw.rounded_rectangle((0, 0, image.width-1, image.height-1), radius=(24 if platform == 'ios' else 20)*SCALE, fill=fill)
    if platform == 'ios':
        image.alpha_composite(_icon(icon, 42, platform, mode), (18*SCALE, 29*SCALE))
        _text(draw, (76, 23), name, 16, fg, 318, 'medium')
        _text(draw, (76, 49), 'Notification preview', 16, fg, 365)
    else:
        # Galaxy card with the actual app icon, not a fabricated status glyph.
        image.alpha_composite(_icon(icon, 24, platform, mode), (18*SCALE, 16*SCALE))
        _text(draw, (52, 18), name, 14, muted, 330, 'medium')
        _text(draw, (18, 55), 'Notification preview', 17, fg, 425)
    _text(draw, (422, 20), 'now', 12, muted, 40)
    return image
