"""Platform sizing must correct delivered pixels, not only preview scale."""
import numpy as np
from PIL import Image, ImageDraw

import icon_spec
from packages.mockups.icon_artwork import Artwork
from packages.mockups.platform_study import platform_previews


def mark(inset):
    image = Image.new('RGBA', (1024, 1024))
    ImageDraw.Draw(image).ellipse((inset, inset, 1023-inset, 1023-inset), fill='#e96a12')
    return image


def test_source_padding_does_not_shrink_delivered_windows_icon():
    spec = icon_spec.IconImage('icon-256.png', 256)
    outputs = [Artwork.measure(image).compose(image, spec, 'windows', '#ffffff')
               for image in [mark(90), mark(400)]]
    for output in outputs:
        left, top, right, bottom = output.getchannel('A').point(lambda a: 255 if a > 128 else 0).getbbox()
        assert 248 <= right-left <= 252
        assert 248 <= bottom-top <= 252
        assert abs((left+right)/2-128) <= 1
    # Deliberate canvas spacing is retained when explicitly requested...
    image = mark(200)
    preserved = Artwork.measure(image, 'canvas').compose(image, spec, 'windows', '#ffffff')
    bounds = preserved.getchannel('A').getbbox()
    assert 150 <= bounds[2]-bounds[0] <= 162
    # ...but not when it would ship a tiny icon on every platform.
    import pytest
    from packages.recipes import RecipeError
    with pytest.raises(RecipeError, match='undersized'):
        Artwork.measure(mark(400), 'canvas')
    ground = Image.new('RGBA', (1024, 1024), '#ffffff')
    ImageDraw.Draw(ground).rectangle((300, 380, 724, 644), fill='black')
    with pytest.raises(RecipeError, match=r'spans 4[12]%'):
        Artwork.measure(ground, 'canvas')


def test_tile_platforms_fit_the_mark_to_about_two_thirds():
    image = mark(90)
    plan = Artwork.measure(image)
    ios = plan.compose(image, icon_spec.ios_images()[-1], 'ios', '#ffffff')
    orange = np.asarray(ios)[:, :, 2] < 128
    ys, xs = np.where(orange)
    assert 0.62 <= (xs.max()-xs.min()+1)/1024 <= 0.66
    mac = np.asarray(plan.compose(image, icon_spec.macos_images()[-1], 'macos', '#ffffff'))
    orange = (mac[:, :, 3] > 128) & (mac[:, :, 2] < 128)
    ys, xs = np.where(orange)
    assert 0.62 <= (xs.max()-xs.min()+1)/824 <= 0.66


def test_adaptive_square_corners_fit_guaranteed_circle():
    image = Image.new('RGBA', (1024, 1024))
    ImageDraw.Draw(image).rectangle((400, 400, 624, 624), fill='red')
    spec = icon_spec.IconImage('ic_launcher_foreground.png', 432)
    output = Artwork.measure(image).compose(image, spec, 'android', '#ffffff')
    y, x = np.where(np.array(output.getchannel('A')) > 32)
    radius = np.hypot(x-215.5, y-215.5).max()
    assert radius <= 133  # 33dp at 4x, plus antialiasing tolerance.
    assert radius >= 129


def test_ios_opaque_canvas_and_macos_margin_are_applied_once():
    image = mark(400)
    plan = Artwork.measure(image)
    ios = plan.compose(image, icon_spec.ios_images()[-1], 'ios', '#FFF8F0')
    assert ios.mode == 'RGB'
    assert ios.getpixel((0, 0)) == (255, 248, 240)
    mac = plan.compose(image, icon_spec.macos_images()[-1], 'macos', '#FFF8F0')
    bounds = mac.getchannel('A').point(lambda a: 255 if a > 128 else 0).getbbox()
    assert bounds == (100, 100, 924, 924)


def test_macos_bakes_rounded_tile_corners_for_full_bleed_art():
    image = Image.new('RGBA', (1024, 1024), '#FFFFFF')
    spec = icon_spec.macos_images()[-1]
    mac = Artwork.measure(image, 'canvas').compose(image, spec, 'macos', '#FFFFFF')
    alpha = mac.getchannel('A')
    assert alpha.getpixel((100, 100)) == 0, 'tile corner must be clipped'
    assert alpha.getpixel((100, 512)) == 255, 'tile edge midpoint stays opaque'
    assert alpha.getpixel((512, 512)) == 255
    assert alpha.point(lambda a: 255 if a > 128 else 0).getbbox() == (100, 100, 924, 924)


def test_platform_previews_only_emit_selected_targets_without_network(monkeypatch):
    import socket

    def denied(*args, **kwargs):
        raise AssertionError('Platform Study must not access the network')

    monkeypatch.setattr(socket, 'socket', denied)
    icons = {'windows': Image.new('RGBA', (256, 256), '#e96a12')}
    previews = dict(platform_previews(icons, 'Example', '#ffffff'))
    assert set(previews) == {'platform-windows-start.png', 'platform-windows-taskbar.png'}
    # No second mask or margin is applied to the delivered Windows pixels.
    assert previews['platform-windows-taskbar.png'].getpixel((1042, 397)) == (233, 106, 18)
    assert previews['platform-windows-taskbar.png'].getpixel((1089, 444)) == (233, 106, 18)


def test_android_studio_and_lifestyle_share_delivered_adaptive_artwork(monkeypatch):
    import socket
    from packages.mockups.platform_study import android_screen

    def denied(*args, **kwargs):
        raise AssertionError('Android scenes must not access the network')

    monkeypatch.setattr(socket, 'socket', denied)
    red = Image.new('RGBA', (432, 432), 'red')
    blue = Image.new('RGBA', (432, 432), 'blue')
    a = np.asarray(android_screen(red, 'Calendar', '#ffffff'))
    b = np.asarray(android_screen(blue, 'A very long application name ' * 6, '#ffffff'))
    changed = np.any(a != b, axis=2)
    changed[685:940, 45:300] = False
    assert not changed.any(), 'Native neighboring apps must remain unchanged'
    previews = dict(platform_previews({'android': red}, 'Calendar', '#ffffff'))
    assert {name: image.size for name, image in previews.items()} == {
        'platform-android-studio.png': (1500, 1000),
        'platform-android.png': (3840, 2560),
    }
    assert previews['platform-android-studio.png'].getpixel((255, 500)) == (255, 0, 0)


def test_linux_renders_ubuntu_and_kde_from_the_same_delivered_icon(monkeypatch):
    import socket

    def denied(*args, **kwargs):
        raise AssertionError('Linux scenes must not access the network')

    monkeypatch.setattr(socket, 'socket', denied)
    icon = Image.new('RGBA', (256, 256), '#e96a12')
    previews = dict(platform_previews({'linux': icon}, 'Example', '#ffffff'))
    assert {name: image.size for name, image in previews.items()} == {
        'platform-linux.png': (1600, 1000),
        'platform-linux-kde.png': (1600, 1000),
    }
    assert previews['platform-linux.png'].getpixel((60, 443)) == (233, 106, 18)
    assert previews['platform-linux-kde.png'].getpixel((532, 840)) == (233, 106, 18)
    # A different app may only alter its slot and bounded tooltip.
    other = dict(platform_previews({'linux': Image.new('RGBA', (256, 256), 'blue')},
                                   'A very long application name ' * 10, '#ffffff'))
    changed = np.any(np.asarray(previews['platform-linux-kde.png']) !=
                     np.asarray(other['platform-linux-kde.png']), axis=2)
    changed[792:888, 484:580] = False
    changed[650:723, 272:793] = False
    assert not changed.any(), 'Native neighboring apps must remain unchanged'


def test_scale_changes_artwork_without_changing_platform_canvas():
    import pytest
    from packages.recipes import RecipeError

    image = mark(90)
    plan = Artwork.measure(image)
    spec = icon_spec.IconImage('icon-256.png', 256)
    small = plan.compose(image, spec, 'windows', '#ffffff', scale=.8)
    large = plan.compose(image, spec, 'windows', '#ffffff', scale=.9)
    assert small.size == large.size == (256, 256)
    assert small.getbbox()[2]-small.getbbox()[0] < large.getbbox()[2]-large.getbbox()[0]
    with pytest.raises(RecipeError, match='platform canvas'):
        plan.compose(image, spec, 'windows', '#ffffff', scale=1.2)
    ios_spec = icon_spec.ios_images()[-1]
    normal_ios = plan.compose(image, ios_spec, 'ios', '#ffffff')
    larger_ios = plan.compose(image, ios_spec, 'ios', '#ffffff', scale=1.1)
    assert normal_ios.size == larger_ios.size
    assert np.count_nonzero(np.asarray(larger_ios)[:, :, 1] < 200) > np.count_nonzero(np.asarray(normal_ios)[:, :, 1] < 200)
    adaptive = icon_spec.IconImage('ic_launcher_foreground.png', 432)
    with pytest.raises(RecipeError, match='adaptive safe zone'):
        plan.compose(image, adaptive, 'android', '#ffffff', scale=1.1)
    for invalid in [float('nan'), float('inf'), 0]:
        with pytest.raises(RecipeError, match='finite positive'):
            plan.compose(image, spec, 'windows', '#ffffff', scale=invalid)
