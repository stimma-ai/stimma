"""Integration boundaries for the local, reusable device scenes."""
import base64
import io
import re
import socket

import numpy as np
from PIL import Image

from packages.mockups.devices import device_previews, home_screen
from packages.export import export_single_html


def test_new_icon_and_name_are_local_and_do_not_replace_neighboring_apps(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Device scenes must not call a server")
    monkeypatch.setattr(socket, "socket", no_network)
    red = Image.new("RGB", (1024, 1024), "red")
    blue = Image.new("RGB", (1024, 1024), "blue")
    # An app named Calendar must not replace the real neighboring Calendar icon.
    a = np.asarray(home_screen(red, "Calendar"))
    b = np.asarray(home_screen(blue, "An exceptionally long application name " * 8))
    changed = np.any(a != b, axis=2)
    changed[255:525, 15:375] = False
    assert not changed.any()
    assert tuple(a[360,195]) == (255,0,0)
    assert tuple(b[360,195]) == (0,0,255)
    sizes = {name: image.size for name, image in device_previews(blue, "Calendar")}
    assert sizes == {"device-studio.png": (1500,1000), "device-lifestyle.png": (3840,2560)}


def test_single_file_cover_preserves_4k_context_image(tmp_path):
    Image.new("RGB", (3840,2560), "white").save(tmp_path / "context.png")
    (tmp_path / "index.html").write_text('<html><body><img src="context.png"></body></html>')
    html = export_single_html(tmp_path)
    encoded = re.search(r'data:image/png;base64,([^"\s]+)', html).group(1)
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
        assert image.size == (3840,2560)
