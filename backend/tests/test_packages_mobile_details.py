"""Mobile details stay local, bounded and faithful to the delivered artwork."""
import pytest
from PIL import Image, ImageDraw

from packages.mockups.mobile_details import render_store, render_notification


@pytest.mark.parametrize('platform', ['ios', 'android'])
@pytest.mark.parametrize('mode', ['light', 'dark'])
def test_mobile_details_use_delivered_pixels_and_bounded_neutral_text(platform, mode, monkeypatch):
    text_runs = []
    original = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        text_runs.append(text)
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', capture)
    art = Image.new('RGB', (512, 512), '#e96a12')
    store = render_store(art, 'An exceptionally long application name ' * 10, platform, mode=mode)
    notification = render_notification(art, 'Example', platform, mode=mode)
    assert store.size == notification.size == (1440, 300)
    assert store.getpixel((50*3, 50*3))[:3] == (233, 106, 18)
    assert any(text.endswith('…') for text in text_runs)
    assert 'Example' in text_runs and 'Notification preview' in text_runs
    assert ('GET' if platform == 'ios' else 'Install') in text_runs
    assert all('Productivity' not in text and 'weekly' not in text for text in text_runs)
