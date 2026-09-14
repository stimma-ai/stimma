"""Rendered device and OS-surface mockups.

What a designer would build in a mockup kit — a phone with a believable home
screen, the store listing, a settings row, a notification — produced
deterministically from shipped assets and the artwork in the package, so the
package carries real presentation images the recipient can drop into a deck.

Everything here is drawn: the frame, the wallpaper, the neighbouring apps and
the OS chrome are original renderings, not screenshots of anyone's product.
"""

from packages.mockups.springboard import render_iphone  # noqa: F401
from packages.mockups.surfaces import (  # noqa: F401
    render_app_store_row,
    render_notification,
    render_settings_row,
    render_spotlight_row,
)
