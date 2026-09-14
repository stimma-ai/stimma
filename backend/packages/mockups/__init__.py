"""Rendered device and OS-surface mockups.

What a designer would build in a mockup kit — a phone with a believable home
screen, the store listing, a settings row, a notification — produced
deterministically from shipped assets and the artwork in the package, so the
package carries real context images the recipient can drop into a deck.

The flat previews use original drawn chrome and neighboring glyphs. The
device scenes use original scene assets and genuine Apple icons captured
from iOS; see assets/devices/README.md for their sources.
"""

from packages.mockups.springboard import render_iphone  # noqa: F401
from packages.mockups.surfaces import (  # noqa: F401
    render_app_store_row,
    render_notification,
    render_settings_row,
    render_spotlight_row,
)
