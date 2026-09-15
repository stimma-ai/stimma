"""Standalone worker executed by the Docker image's small Playwright runtime."""
import base64
import json
import mimetypes
from pathlib import Path
import signal
import sys
from urllib.parse import unquote, urlsplit

from playwright.sync_api import sync_playwright

ORIGIN = 'https://render.stimma.invalid'
CSP = "default-src 'none'; img-src 'self' data:; font-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'none'; base-uri 'none'; frame-src 'none'"
READY = Path(__file__).with_name('render_ready.txt').read_text()


def render(browser, job):
    context = browser.new_context(viewport={'width': job['width'], 'height': job['height'] or 1},
                                  device_scale_factor=job['dpr'], service_workers='block',
                                  color_scheme='light', reduced_motion='reduce', locale='en-US', timezone_id='UTC')
    missing = set()
    def route(request):
        url = urlsplit(request.request.url)
        name = unquote(url.path.lstrip('/'))
        if f'{url.scheme}://{url.netloc}' != ORIGIN:
            missing.add('External resource blocked')
            request.abort()
            return
        body = job['html'].encode() if name == 'index.html' else base64.b64decode(job['assets'][name]) if name in job['assets'] else None
        if body is None:
            missing.add(name)
            request.fulfill(status=404, body='')
        else:
            request.fulfill(body=body, headers={'content-type':mimetypes.guess_type(name)[0] or 'application/octet-stream', 'content-security-policy':CSP})
    context.route('**/*', route)
    try:
        page = context.new_page()
        page.goto(ORIGIN + '/index.html')
        measured = page.evaluate(READY)
        limit = job.get('max_auto_height', job['width'] * 5)
        if job.get('max_auto_height') is not None and measured > limit:
            raise ValueError('Complete HTML preview exceeds its height limit; shorten or split the guide')
        height = job['height'] or min(measured, limit)
        page.set_viewport_size({'width':job['width'], 'height':height})
        page.evaluate(READY)
        if missing:
            raise ValueError('Missing or blocked render resources: ' + ', '.join(sorted(missing)))
        return {'png_b64':base64.b64encode(page.screenshot(omit_background=True)).decode(), 'height':height}
    finally:
        context.close()


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, chromium_sandbox=True)
        def stop(*_):
            browser.close()
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, stop)
        try:
            for line in sys.stdin:
                try:
                    result = render(browser, json.loads(line))
                except Exception as exc:
                    result = {'error':str(exc)}
                print(json.dumps(result), flush=True)
        finally:
            browser.close()


if __name__ == '__main__':
    main()
