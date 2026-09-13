"""Real browser captures; run through `stimma render-test`."""
import asyncio
import base64
import io
import json
import os
from pathlib import Path

from PIL import Image
import pytest
import pytest_asyncio

from utils.local_render import (LocalRenderer, LayoutRenderBusy, LayoutRenderFailed,
                                prepare_job, gather_bundle_assets, FONT_DIR)


def test_limits_and_bundle_escape(tmp_path):
    with pytest.raises(LayoutRenderFailed):
        prepare_job('', 16384, 32768, 4, {})
    with pytest.raises(LayoutRenderFailed):
        prepare_job('', 0, 10, 1, {})
    outside = tmp_path / 'secret.png'
    outside.write_bytes(b'secret')
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    try:
        (bundle / 'escape.png').symlink_to(outside)
    except OSError:
        pytest.skip('Symlinks unavailable')
    assert gather_bundle_assets(bundle) == {}


@pytest_asyncio.fixture(loop_scope="function")
async def browser():
    command = os.environ.get('STIMMA_TEST_RENDER_COMMAND')
    if not command:
        pytest.skip('Use stimma render-test for browser integration')
    worker = LocalRenderer()
    worker.command = lambda: json.loads(command)
    try:
        yield worker
    finally:
        await worker.close()


async def capture(worker, html, width=100, height=80, dpr=1, assets=None):
    png = await worker.render(prepare_job(html, width, height, dpr, assets), 30, 5)
    return Image.open(io.BytesIO(png)).convert('RGBA')


@pytest.mark.asyncio
async def test_transparency_scale_and_worker_reuse(browser):
    html = '<html><head><style>body{margin:0}</style></head><body><div style="width:40px;height:30px;background:red"></div></body></html>'
    image = await capture(browser, html, dpr=2)
    assert image.size == (200, 160)
    assert image.getpixel((10, 10)) == (255, 0, 0, 255)
    assert image.getpixel((180, 140))[3] == 0
    pid = browser.process.pid
    other = await capture(browser, html, dpr=0.5)
    assert other.size == (50, 40)
    assert browser.process.pid == pid


@pytest.mark.asyncio
async def test_auto_height_css_fonts_and_nested_assets(browser):
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="lime"/></svg>'
    assets = {'nested/picture.svg':base64.b64encode(svg.encode()).decode(),
              'nested/font.ttf':base64.b64encode((FONT_DIR / 'LiberationMono-Regular.ttf').read_bytes()).decode(),
              'nested/style.css':base64.b64encode(b'@font-face{font-family:Bundle;src:url(font.ttf)}body{margin:0;font-family:Bundle}').decode()}
    html = '<html><head><link rel="stylesheet" href="nested/style.css"></head><body><div style="height:120px;display:flex"><img src="nested/picture.svg" width="20" height="20"><span>Typography</span></div></body></html>'
    image = await capture(browser, html, height=None, assets=assets)
    assert image.size == (100,120)
    assert image.getpixel((5,5)) == (0,255,0,255)
    assert image.crop((20,0,100,30)).getbbox() is not None


@pytest.mark.asyncio
async def test_svg_filter(browser):
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80"><defs><filter id="b"><feGaussianBlur stdDeviation="3"/></filter></defs><rect x="30" y="20" width="40" height="40" fill="blue" filter="url(#b)"/></svg>'
    image = await capture(browser, '<body style="margin:0"><img src="art.svg"></body>', assets={'art.svg':base64.b64encode(svg.encode()).decode()})
    assert image.getpixel((50,40))[2] == 255
    assert 0 < image.getpixel((28,40))[3] < 255
    assert image.getpixel((0,0))[3] == 0


@pytest.mark.asyncio
async def test_missing_resource_and_script_isolation(browser):
    for source in ['missing.png', 'file:///etc/passwd', 'http://127.0.0.1:9/private']:
        with pytest.raises(LayoutRenderFailed):
            await capture(browser, f'<img src="{source}">')
    image = await capture(browser, '<body style="margin:0"><script>document.body.style.background="red"</script></body>')
    assert image.getbbox() is None
    await capture(browser, '<body>Recovered</body>')


@pytest.mark.asyncio
async def test_deadline_and_queue_recovery(browser):
    await browser.slot.acquire()
    try:
        with pytest.raises(LayoutRenderBusy):
            await browser.render(prepare_job('',100,80,1,{}),30,0)
    finally:
        browser.slot.release()
    with pytest.raises(LayoutRenderFailed):
        await browser.render(prepare_job('<body>Timeout</body>',100,80,1,{}),0.00001,5)
    await capture(browser, '<body>Recovered</body>')


def test_preview_embeds_shared_fonts_and_nested_css(tmp_path):
    from utils.local_render import inline_bundle_html
    (tmp_path / 'nested').mkdir()
    (tmp_path / 'index.html').write_text('<html><head><link rel="stylesheet" href="nested/style.css"></head><body>Text</body></html>')
    (tmp_path / 'nested/style.css').write_text('@font-face{font-family:Test;src:url(font.ttf)}')
    (tmp_path / 'nested/font.ttf').write_bytes(b'font-fixture')
    html = inline_bundle_html(tmp_path)
    assert 'data:font/ttf;base64,' in html
    assert 'href="data:text/css;base64,' in html
    assert 'Stimma Sans' in html


@pytest.mark.asyncio
async def test_failed_font_is_reported(browser):
    with pytest.raises(LayoutRenderFailed):
        await capture(browser, '<style>@font-face{font-family:Broken;src:url(missing.woff2)}body{font-family:Broken}</style><body>Text</body>')


@pytest.mark.asyncio
async def test_cancellation_releases_worker(browser):
    # Pause after the real child starts so cancellation cannot race a completed
    # tiny capture on fast hosts or Windows' coarser event-loop timer.
    started = asyncio.Event()
    hold = asyncio.Event()
    original_start = browser.start
    async def pause_after_start():
        await original_start()
        started.set()
        await hold.wait()
    browser.start = pause_after_start
    job = prepare_job('<body>Cancelled</body>',100,80,1,{})
    task = asyncio.create_task(browser.render(job,30,5))
    await asyncio.wait_for(started.wait(), 30)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert browser.process is None
    browser.start = original_start
    await capture(browser, '<body>Recovered</body>')
