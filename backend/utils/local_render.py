"""Local browser rendering over private child-process pipes.

Desktop workers reuse the installed Electron executable. Docker workers use the
headless browser in the bootstrap image. No frontend connection participates.
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import mimetypes
import posixpath
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import re
import tempfile
import psutil

from app_dirs import get_data_dir

RENDER_VERSION = 'chromium-liberation-1'
RENDER_TIMEOUT_S = 30.0
MAX_PIXELS = 40_000_000
MAX_INPUT_BYTES = 64 * 1024 * 1024
FONT_DIR = Path(__file__).resolve().parent.parent / 'render_fonts'


class LayoutRenderUnavailable(RuntimeError):
    """The local browser worker is not installed or could not start."""


class LayoutRenderBusy(RuntimeError):
    """The local renderer's queue wait expired."""


class LayoutRenderFailed(RuntimeError):
    """A document could not be rendered within its resource/deadline limits."""


def gather_bundle_assets(bundle_dir: Path) -> dict[str, str]:
    root = bundle_dir.resolve()
    assets = {}
    total = 0
    for entry in root.rglob('*'):
        if not entry.is_file() or not entry.resolve().is_relative_to(root):
            continue
        if entry.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg', '.css', '.woff', '.woff2', '.ttf', '.otf'}:
            continue
        total += entry.stat().st_size
        if total > MAX_INPUT_BYTES:
            raise LayoutRenderFailed('Render bundle exceeds 64 MiB')
        assets[entry.relative_to(root).as_posix()] = base64.b64encode(entry.read_bytes()).decode('ascii')
    return assets


@lru_cache(maxsize=1)
def bundled_fonts():
    assets = {}
    css = []
    for font in sorted(FONT_DIR.glob('*.ttf')):
        family, variant = font.stem.split('-')
        name = f'__stimma_fonts/{font.name}'
        assets[name] = base64.b64encode(font.read_bytes()).decode('ascii')
        css.append(f'@font-face{{font-family:"Stimma {family.removeprefix("Liberation")}";src:url("/{name}");font-weight:{700 if "Bold" in variant else 400};font-style:{"italic" if "Italic" in variant else "normal"};}}')
    return assets, css


def prepare_job(html: str, width: int, height: int | None, dpr: float, assets: dict | None) -> dict:
    if not isinstance(width, int) or isinstance(width, bool) or not 1 <= width <= 16384:
        raise LayoutRenderFailed('Render width must be between 1 and 16384')
    if height is not None and (not isinstance(height, int) or isinstance(height, bool) or not 1 <= height <= 32768):
        raise LayoutRenderFailed('Invalid render height')
    if not math.isfinite(dpr) or not 0.1 <= dpr <= 4 or width * (height or width * 5) * dpr ** 2 > MAX_PIXELS:
        raise LayoutRenderFailed('Render exceeds pixel limit')
    assets = dict(assets or {})
    font_assets, css = bundled_fonts()
    assets.update(font_assets)
    css = list(css)
    css.append('html{font-family:"Stimma Sans",sans-serif}pre,code{font-family:"Stimma Mono",monospace}*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}')
    style = '<style>' + ''.join(css) + '</style>'
    # Place defaults before document styles, preserving their normal cascade.
    head = re.search(r'<head\b[^>]*>', html, re.I)
    if head:
        html = html[:head.end()] + style + html[head.end():]
    else:
        html = style + html
    job = dict(html=html, width=width, height=height, dpr=dpr, assets=assets)
    if len(json.dumps(job).encode()) > MAX_INPUT_BYTES * 2:
        raise LayoutRenderFailed('Render request is too large')
    return job


class LocalRenderer:
    def __init__(self):
        self.slot = asyncio.Semaphore(1)
        self.process = None
        self.profile = None
        self.stderr_task = None
        self.stderr_tail = b''
        self.waiting = 0

    def command(self):
        if os.environ.get('STIMMA_HEADLESS') == '1':
            python = os.environ.get('STIMMA_RENDER_PYTHON', '/opt/stimma/render-python/bin/python')
            if not Path(python).is_file():
                raise LayoutRenderUnavailable('Headless rendering runtime is missing; update the server image')
            return [python, str(Path(__file__).with_name('headless_render_worker.py'))]
        try:
            command = json.loads((get_data_dir() / 'render-worker.json').read_text())['command']
            if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
                raise ValueError('Invalid worker command')
            return command
        except (OSError, ValueError, KeyError) as exc:
            raise LayoutRenderUnavailable('Local Electron renderer is not registered; start the desktop shell once') from exc

    async def start(self):
        if self.process and self.process.returncode is None:
            return
        await self.close()
        command = self.command()
        self.profile = tempfile.TemporaryDirectory(prefix='stimma-render-')
        env = dict(os.environ, STIMMA_RENDER_PROFILE=self.profile.name)
        env.pop('ELECTRON_RUN_AS_NODE', None)
        env.pop('NODE_OPTIONS', None)
        try:
            self.process = await asyncio.create_subprocess_exec(
                *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env, limit=MAX_INPUT_BYTES * 4,
                **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
            self.stderr_tail = b''
            stderr = self.process.stderr
            async def drain_errors():
                while chunk := await stderr.read(4096):
                    self.stderr_tail = (self.stderr_tail + chunk)[-8192:]
            self.stderr_task = asyncio.create_task(drain_errors())
        except OSError as exc:
            await self.close()
            raise LayoutRenderUnavailable('Could not launch the local rendering worker') from exc

    async def close(self):
        process, self.process = self.process, None
        children = []
        if process and process.returncode is None:
            try:
                children = psutil.Process(process.pid).children(recursive=True)
            except psutil.Error:
                pass
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except asyncio.TimeoutError:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except asyncio.TimeoutError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()
        for child in children:
            try:
                child.kill()
            except psutil.Error:
                pass
        if self.stderr_task:
            self.stderr_task.cancel()
            await asyncio.gather(self.stderr_task, return_exceptions=True)
            self.stderr_task = None
        if self.profile:
            self.profile.cleanup()
            self.profile = None

    async def render(self, job, timeout, queue_timeout):
        if self.waiting >= 32:
            raise LayoutRenderBusy('Local render queue is full')
        self.waiting += 1
        acquired = False
        try:
            if queue_timeout is not None and queue_timeout <= 0:
                if self.slot.locked():
                    raise LayoutRenderBusy('Local renderer is busy')
                await self.slot.acquire()
            elif queue_timeout is None:
                await self.slot.acquire()
            else:
                try:
                    await asyncio.wait_for(self.slot.acquire(), queue_timeout)
                except asyncio.TimeoutError as exc:
                    raise LayoutRenderBusy('Local renderer queue wait expired') from exc
            acquired = True
            async def exchange():
                await self.start()
                self.process.stdin.write(json.dumps(job).encode() + b'\n')
                await self.process.stdin.drain()
                line = await self.process.stdout.readline()
                if not line:
                    raise LayoutRenderFailed('Local rendering worker exited: ' + self.stderr_tail.decode(errors='replace')[-2000:])
                result = json.loads(line)
                if result.get('error'):
                    raise LayoutRenderFailed(result['error'])
                png = base64.b64decode(result['png_b64'], validate=True)
                if not png.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise LayoutRenderFailed('Renderer returned invalid PNG')
                return png
            try:
                return await asyncio.wait_for(exchange(), timeout)
            except BaseException as exc:
                await self.close()
                if isinstance(exc, (asyncio.CancelledError, LayoutRenderUnavailable, LayoutRenderFailed)):
                    raise
                raise LayoutRenderFailed('Local rendering failed or exceeded its deadline') from exc
        finally:
            self.waiting -= 1
            if acquired:
                self.slot.release()


renderer = LocalRenderer()


async def render_html(html, width, height, dpr=2.0, assets=None, render_timeout_s=RENDER_TIMEOUT_S, queue_timeout_s=None):
    return await renderer.render(prepare_job(html, width, height, dpr, assets), render_timeout_s, queue_timeout_s)


def renderer_version():
    """Cache identity changes when either runtime or the bundled fonts changes."""
    try:
        if os.environ.get('STIMMA_HEADLESS') == '1':
            version = Path('/opt/stimma/render-version').read_text().strip()
        else:
            version = json.loads((get_data_dir() / 'render-worker.json').read_text()).get('chromium', 'unknown')
    except (OSError, ValueError):
        version = 'unavailable'
    return f'{RENDER_VERSION}-{version}-{font_digest()}'


@lru_cache(maxsize=1)
def font_digest():
    digest = hashlib.sha256()
    for font in sorted(FONT_DIR.glob('*.ttf')):
        digest.update(font.read_bytes())
    return digest.hexdigest()[:12]


def inline_bundle_html(bundle_dir):
    """Use the same fonts/resources for browser previews and HTML exports."""
    html = (bundle_dir / 'index.html').read_text(encoding='utf-8')
    job = prepare_job(html, 800, 800, 1, gather_bundle_assets(bundle_dir))
    assets = job['assets']
    def inline(name, parent='', seen=frozenset()):
        if name.startswith(('data:', 'http:', 'https:', '//', '#')):
            return name
        key = posixpath.normpath(posixpath.join(parent, name.lstrip('/')))
        if key not in assets or key in seen:
            return name
        mime = mimetypes.guess_type(key)[0] or 'application/octet-stream'
        data = assets[key]
        if key.endswith('.css'):
            css = base64.b64decode(data).decode('utf-8')
            css = rewrite_css(css, posixpath.dirname(key), seen | {key})
            data = base64.b64encode(css.encode()).decode()
        return f'data:{mime};base64,{data}'
    def rewrite_css(text, parent='', seen=frozenset()):
        return re.sub(r"url\(\s*([\"']?)([^\"')]+)\1\s*\)",
                      lambda m: 'url("' + inline(m[2].strip(), parent, seen) + '")', text)
    html = rewrite_css(job['html'])
    return re.sub(r"(src|href)\s*=\s*([\"'])([^\"']+)\2",
                  lambda m: f'{m[1]}={m[2]}{inline(m[3])}{m[2]}', html, flags=re.I)
