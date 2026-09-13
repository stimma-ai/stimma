"""The cover component kit.

One vocabulary every cover uses — the auto cover, a recipe presenting its own
output, and anything an agent writes by hand. Components carry the look, so a
cover is a choice of components and words rather than a fresh design each time,
and two packages made a year apart still read as coming from the same studio.

Components, all usable in authored HTML:

    <stimma-section label="At actual size">…</stimma-section>
    <stimma-media ref="m1" caption="Primary mark" plate>
    <stimma-grid>…<stimma-media>…</stimma-grid>
    <stimma-sizes>       real-size row; children are <stimma-media ref size="40">
    <stimma-device kind="iphone" ref="…" label="Sunburst">
    <stimma-columns>…<stimma-column title="…">…</stimma-columns>
    <stimma-files ref="r1">    the shared file tree
    <stimma-compare a="…" b="…" mode="slider">

Every one expands to plain HTML when the bundle is written, so a cover reads
correctly with scripts disabled, from a double-clicked file, and in a frame.
The script only enhances what needs behaviour.
"""

from __future__ import annotations

import html as htmllib
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from packages.manifest import member_by_id, resolve_ref, run_by_id

KIT_VERSION = 2

# The elements a cover may use. Anything else is the author's own markup.
COMPONENTS = (
    "stimma-section", "stimma-media", "stimma-grid", "stimma-sizes",
    "stimma-device", "stimma-columns", "stimma-column", "stimma-files",
    "stimma-compare",
)
# Registered but inert: feedback is a later design pass. An authored cover
# using one renders its children instead of breaking.
RESERVED_COMPONENTS = ("stimma-pick", "stimma-approve", "stimma-comments")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"}
VIDEO_EXTS = {".mp4", ".webm", ".mov"}

# The Stimma mark, embedded so a cover carries its maker with it offline.
LOGO_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" role="img" aria-label="Stimma"><g transform="translate(512 512)"><path fill="#F38724" transform="rotate(266.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/><path fill="#E73B31" transform="rotate(311.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/><path fill="#BC2073" transform="rotate(356.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/><path fill="#62B253" transform="rotate(41.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/><path fill="#039E96" transform="rotate(86.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/><path fill="#2376BC" transform="rotate(131.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/><path fill="#6C3A91" transform="rotate(176.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/><path fill="#F8CF11" transform="rotate(221.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/></g></svg>'''


def escape(text: Any) -> str:
    return htmllib.escape("" if text is None else str(text), quote=True)


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


# Builders — for Python callers (recipe presenters, the auto cover) so they
# emit components instead of hand-written markup that drifts.

def section(body: str, *, label: str = "") -> str:
    attr = f' label="{escape(label)}"' if label else ""
    return f"<stimma-section{attr}>{body}</stimma-section>"


def media(ref: str, *, caption: str = "", size: Optional[int] = None, plate: bool = False) -> str:
    attrs = f' ref="{escape(ref)}"'
    if caption:
        attrs += f' caption="{escape(caption)}"'
    if size:
        attrs += f' size="{int(size)}"'
    if plate:
        attrs += " plate"
    return f"<stimma-media{attrs}></stimma-media>"


def grid(items: Iterable[str], *, cell: int = 0) -> str:
    style = f' style="--sp-cell:{int(cell)}px"' if cell else ""
    return f"<stimma-grid{style}>{''.join(items)}</stimma-grid>"


def sizes(items: Iterable[str]) -> str:
    return f"<stimma-sizes>{''.join(items)}</stimma-sizes>"


def device(ref: str, *, kind: str = "iphone", label: str = "") -> str:
    attr = f' label="{escape(label)}"' if label else ""
    return f'<stimma-device kind="{escape(kind)}" ref="{escape(ref)}"{attr}></stimma-device>'


def columns(entries: Iterable[tuple[str, str]]) -> str:
    body = "".join(
        f'<stimma-column title="{escape(title)}">{escape(text)}</stimma-column>'
        for title, text in entries
    )
    return f"<stimma-columns>{body}</stimma-columns>"


def files(ref: str = "") -> str:
    attr = f' ref="{escape(ref)}"' if ref else ""
    return f"<stimma-files{attr}></stimma-files>"


def hero(*parts: str) -> str:
    return f'<div class="sp-hero">{"".join(parts)}</div>'


KIT_CSS = """
:root{
  --sp-bg:#0d0d0e; --sp-fg:#ededee; --sp-muted:#8b8b8f; --sp-faint:#5c5c60;
  --sp-line:#232325; --sp-accent:#2dd4bf; --sp-plate:#151517;
}
@media (prefers-color-scheme: light){
  :root{--sp-bg:#faf9f7; --sp-fg:#17171a; --sp-muted:#6b6b70; --sp-faint:#97979c;
        --sp-line:#e5e2dd; --sp-accent:#0d9488; --sp-plate:#f1efec;}
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--sp-bg);color:var(--sp-fg);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
img{display:block}
.sp-page{max-width:880px;margin:0 auto;padding:56px 28px 88px}
.sp-title{font-size:clamp(28px,4vw,42px);line-height:1.05;letter-spacing:-0.022em;margin:0;font-weight:600}
.sp-sub{color:var(--sp-muted);margin:8px 0 0;font-size:14px}
.sp-sub b{color:var(--sp-fg);font-weight:500}
.sp-section{margin-top:56px}
.sp-label{font-size:12px;letter-spacing:.02em;color:var(--sp-muted);margin:0 0 18px;font-weight:500}
.sp-note{color:var(--sp-muted);font-size:13px;margin:12px 0 0}
.sp-num{font-variant-numeric:tabular-nums}
.sp-hr{border:0;border-top:1px solid var(--sp-line);margin:0}

/* Media: artwork sits on a matte, never in a bordered card. */
stimma-media{display:block}
stimma-media img,stimma-media video{max-width:100%;height:auto;border-radius:2px}
stimma-media[plate] img{background:var(--sp-plate);padding:24px;border-radius:10px}
stimma-media .sp-caption{font-size:12px;color:var(--sp-muted);padding-top:8px}
stimma-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--sp-cell,200px),1fr));gap:28px}

/* Files: a quiet list. One icon button per row, no repeated link text. */
stimma-files{display:block}
.sp-files-top{display:flex;align-items:center;justify-content:space-between;gap:16px;
  padding-bottom:14px;margin-bottom:4px}
.sp-files-what{font-size:13px;color:var(--sp-muted)}
stimma-files ul{list-style:none;margin:0;padding:0}
stimma-files li{position:relative}
stimma-files .sp-row{display:flex;align-items:center;gap:10px;padding:6px 10px;min-height:34px;
  border-radius:7px;transition:background-color .12s}
stimma-files .sp-row:hover{background:var(--sp-plate)}
stimma-files li.sp-dir>.sp-row{cursor:pointer;user-select:none}
stimma-files li.sp-dir>ul{margin-left:19px;padding-left:14px;border-left:1px solid var(--sp-line)}
stimma-files li.sp-dir.sp-collapsed>ul{display:none}
stimma-files .sp-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-size:13.5px;color:var(--sp-fg)}
stimma-files li.sp-dir>.sp-row .sp-name{color:var(--sp-muted)}
stimma-files .sp-meta{color:var(--sp-faint);font-size:12px;font-variant-numeric:tabular-nums;flex:none}
stimma-files .sp-caret{width:14px;height:14px;flex:none;color:var(--sp-faint);
  display:inline-flex;align-items:center;justify-content:center;transition:transform .15s}
stimma-files li.sp-dir.sp-collapsed>.sp-row .sp-caret{transform:rotate(-90deg)}
stimma-files .sp-caret svg{width:11px;height:11px;stroke:currentColor;fill:none;stroke-width:2.2;
  stroke-linecap:round;stroke-linejoin:round}
stimma-files .sp-thumb{width:22px;height:22px;flex:none;border-radius:4px;object-fit:contain;
  background:var(--sp-plate)}
stimma-files .sp-glyph{width:22px;height:22px;flex:none;display:inline-flex;align-items:center;
  justify-content:center;color:var(--sp-faint)}
stimma-files .sp-glyph svg{width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:1.6;
  stroke-linecap:round;stroke-linejoin:round}
stimma-files li.sp-previewable>.sp-row{cursor:zoom-in}
.sp-dl{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;
  border-radius:6px;color:var(--sp-faint);flex:none;opacity:0;
  transition:color .15s,background-color .15s,opacity .15s}
stimma-files .sp-row:hover .sp-dl,.sp-dl:focus-visible{opacity:1}
.sp-dl:hover{color:var(--sp-fg);background:var(--sp-line)}
.sp-dl svg{width:15px;height:15px;stroke:currentColor;fill:none;stroke-width:1.75;
  stroke-linecap:round;stroke-linejoin:round}
.sp-zip{display:inline-flex;align-items:center;gap:8px;font-size:13px;color:var(--sp-fg);
  padding:7px 12px;border-radius:7px;background:var(--sp-plate);flex:none;
  transition:background-color .15s}
.sp-zip:hover{background:var(--sp-line)}
.sp-zip svg{width:15px;height:15px;stroke:currentColor;fill:none;stroke-width:1.75;
  stroke-linecap:round;stroke-linejoin:round;color:var(--sp-accent)}
.sp-zip b{font-weight:500}
.sp-zip em{font-style:normal;color:var(--sp-faint);font-variant-numeric:tabular-nums}

/* File preview overlay */
.sp-lightbox{position:fixed;inset:0;z-index:50;display:none;align-items:center;
  justify-content:center;padding:48px;background:rgba(0,0,0,.82);cursor:zoom-out}
.sp-lightbox.sp-open{display:flex}
.sp-lightbox figure{margin:0;display:grid;justify-items:center;gap:14px;max-width:100%;max-height:100%}
.sp-lightbox img{max-width:min(720px,80vw);max-height:70vh;border-radius:6px;
  background:repeating-conic-gradient(#8883 0% 25%,transparent 0% 50%) 50%/18px 18px}
.sp-lightbox figcaption{font-size:12px;color:#d8d8d8;font-variant-numeric:tabular-nums}

/* Compare */
stimma-compare{display:block}
stimma-compare .sp-cmp{display:grid;grid-template-columns:1fr 1fr;gap:20px}
stimma-compare figure{margin:0}
stimma-compare figcaption{font-size:12px;color:var(--sp-muted);padding-top:8px}
stimma-compare.sp-slider .sp-cmp{display:block;position:relative}
stimma-compare.sp-slider figure:first-child{position:absolute;inset:0;overflow:hidden;width:var(--sp-split,50%)}
stimma-compare.sp-slider figure:first-child img{width:var(--sp-w,100%);max-width:none}
stimma-compare.sp-slider input[type=range]{position:absolute;left:0;right:0;bottom:10px;width:100%;margin:0}

/* Reserved widgets render their children and nothing else for now. */
stimma-pick,stimma-approve,stimma-comments{display:block}

.sp-footer{margin-top:72px;padding-top:20px;border-top:1px solid var(--sp-line);
  display:flex;align-items:center;gap:9px;color:var(--sp-faint);font-size:12px}
.sp-footer svg{width:17px;height:17px;flex:none}
.sp-footer .sp-brand{display:inline-flex;align-items:baseline;gap:7px;color:var(--sp-muted)}
.sp-footer .sp-wordmark{font-family:"General Sans",system-ui,sans-serif;
  text-transform:lowercase;letter-spacing:.12em;font-size:13px;color:var(--sp-fg)}

/* Section, sizes, device, columns ----------------------------------------- */
stimma-section{display:block;margin-top:56px}
stimma-section:first-child{margin-top:0}
stimma-sizes{display:flex;align-items:flex-end;gap:30px;flex-wrap:wrap}
stimma-sizes stimma-media{display:grid;justify-items:center;gap:9px}
stimma-sizes stimma-media img{border-radius:22.37%}
stimma-sizes .sp-caption{padding:0;font-size:11px;color:var(--sp-faint);
  font-variant-numeric:tabular-nums}
stimma-columns{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:28px}
stimma-column{display:block}
stimma-column h3{margin:0 0 5px;font-size:13.5px;font-weight:500}
stimma-column p{margin:0;font-size:13px;color:var(--sp-muted);line-height:1.5}
stimma-device{display:block;flex:none}
stimma-devices{display:flex;align-items:flex-start;justify-content:center;gap:44px;flex-wrap:wrap}
.sp-devicecase{display:grid;justify-items:center;gap:12px}
.sp-devicecase>span{font-size:11px;color:var(--sp-faint);letter-spacing:.04em}

/* Phone: proportions, bezel, wallpaper, glare. Rendered rather than mocked up
   in a photo, so it stays truthful to the pixels the package actually holds. */
.sp-phone{position:relative;width:232px;aspect-ratio:1170/2532;border-radius:13.5%/6.2%;
  padding:4px;box-shadow:0 30px 64px rgba(0,0,0,.55),0 2px 4px rgba(0,0,0,.4)}
/* Two finishes, deliberately: the pair reads as two devices rather than one
   device photographed twice, and each frame suits the wallpaper inside it. */
.sp-phone.sp-dark{background:linear-gradient(150deg,#55555c,#212125 22%,#141417 55%,#3a3a41 100%)}
.sp-phone.sp-light{background:linear-gradient(150deg,#f2f1ee,#c9c8c5 24%,#a9a8a6 58%,#e7e6e3 100%)}
.sp-screen{position:relative;width:100%;height:100%;border-radius:12.4%/5.7%;overflow:hidden;
  display:flex;flex-direction:column}
.sp-screen::after{content:"";position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(128deg,rgba(255,255,255,.16) 0%,rgba(255,255,255,.04) 18%,
    transparent 38%,transparent 100%)}
.sp-island{position:absolute;top:1.5%;left:50%;transform:translateX(-50%);
  width:25%;height:2.1%;border-radius:999px;background:#050506;z-index:3}
.sp-phone.sp-dark .sp-screen{background:
  radial-gradient(120% 70% at 78% 4%,#4a3d75 0%,transparent 55%),
  radial-gradient(100% 60% at 10% 30%,#1d3b63 0%,transparent 60%),
  linear-gradient(178deg,#141826 0%,#0a0b12 100%)}
.sp-phone.sp-light .sp-screen{background:
  radial-gradient(120% 70% at 80% 2%,#ffd9a8 0%,transparent 55%),
  radial-gradient(110% 65% at 6% 26%,#bcd7f5 0%,transparent 62%),
  linear-gradient(178deg,#f4efe8 0%,#dfe3ee 100%)}
.sp-statusbar{display:flex;align-items:center;justify-content:space-between;
  padding:4.2% 7% 0;font-size:8px;font-weight:600;letter-spacing:.01em}
.sp-phone.sp-dark .sp-statusbar{color:#fff}
.sp-phone.sp-light .sp-statusbar{color:#15151a}
.sp-statusbar .sp-bars{display:flex;align-items:flex-end;gap:1.4px}
.sp-statusbar .sp-bars i{display:block;width:2px;background:currentColor;border-radius:1px}
.sp-statusbar .sp-batt{width:14px;height:7px;border:1px solid currentColor;border-radius:2px;
  position:relative;opacity:.9}
.sp-statusbar .sp-batt::after{content:"";position:absolute;inset:1.5px;right:4px;
  background:currentColor;border-radius:1px}
.sp-apps{flex:1;display:grid;grid-template-columns:repeat(4,1fr);align-content:start;
  gap:4.4% 3%;padding:6% 6% 0}
.sp-app{display:grid;justify-items:center;gap:4px}
.sp-app img,.sp-app i{display:block;width:100%;aspect-ratio:1;border-radius:22.37%}
.sp-app i{box-shadow:inset 0 1px 0 rgba(255,255,255,.14)}
.sp-app em{font-style:normal;font-size:6.5px;line-height:1;max-width:100%;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.sp-phone.sp-dark .sp-app em{color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.55)}
.sp-phone.sp-light .sp-app em{color:#1b1b20;text-shadow:0 1px 2px rgba(255,255,255,.5)}
.sp-app.sp-mine img{box-shadow:0 5px 14px rgba(0,0,0,.45)}
.sp-dock{margin:0 5% 5%;padding:4.5%;border-radius:26px;
  display:grid;grid-template-columns:repeat(4,1fr);gap:4%;backdrop-filter:blur(8px)}
.sp-phone.sp-dark .sp-dock{background:rgba(255,255,255,.13)}
.sp-phone.sp-light .sp-dock{background:rgba(255,255,255,.45)}
.sp-dock i,.sp-dock img{display:block;width:100%;aspect-ratio:1;border-radius:22.37%}
.sp-phone.sp-dark .sp-dock i{background:rgba(255,255,255,.2)}
.sp-phone.sp-light .sp-dock i{background:rgba(120,120,140,.22)}
.sp-homebar{height:3px;width:34%;margin:0 auto 6px;border-radius:999px;opacity:.5}
.sp-phone.sp-dark .sp-homebar{background:#fff}
.sp-phone.sp-light .sp-homebar{background:#15151a}

/* The other places an icon shows up. Designers show these because this is
   where an icon actually has to survive. */
stimma-contexts{display:grid;gap:14px}
.sp-ctx{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:11px;
  background:var(--sp-plate)}
.sp-ctx img{flex:none;border-radius:22.37%}
.sp-ctx .sp-ctx-body{flex:1;min-width:0}
.sp-ctx b{display:block;font-size:13.5px;font-weight:500}
.sp-ctx span{display:block;font-size:12px;color:var(--sp-muted);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.sp-ctx .sp-get{flex:none;font-size:11.5px;font-weight:600;letter-spacing:.04em;
  padding:5px 15px;border-radius:999px;background:var(--sp-line);color:var(--sp-fg)}
.sp-ctx .sp-chev{flex:none;color:var(--sp-faint);font-size:15px;line-height:1}
.sp-ctx.sp-notify{background:var(--sp-plate);box-shadow:0 8px 22px rgba(0,0,0,.28)}
.sp-ctx.sp-notify .sp-when{flex:none;font-size:11px;color:var(--sp-faint)}
"""

KIT_JS = r"""
(function(){
  if (window.__stimmaKit) return; window.__stimmaKit = true;

  var manifestEl = document.getElementById('stimma-package-manifest');
  var manifest = null;
  try { manifest = manifestEl ? JSON.parse(manifestEl.textContent) : null; } catch (e) { manifest = null; }
  window.stimmaPackage = {
    manifest: manifest,
    kitVersion: %(kit_version)d,
    host: document.documentElement.getAttribute('data-stimma-host') || null
  };

  // Components are registered so the page has stable element names, but none
  // of them wire themselves up. A custom element's connectedCallback runs when
  // its opening tag is parsed, before any of its children exist, so anything
  // that queries inside itself there finds an empty element — which is exactly
  // how the file tree ended up inert. Behaviour is attached once the document
  // is parsed, by delegation from the document, which also survives content
  // arriving later.
  function define(name){
    if (window.customElements && !customElements.get(name)) {
      customElements.define(name, class extends HTMLElement {});
    }
  }
  ['stimma-section','stimma-media','stimma-grid','stimma-sizes','stimma-device',
   'stimma-columns','stimma-column','stimma-files','stimma-compare',
   'stimma-pick','stimma-approve','stimma-comments'].forEach(define);

  function ready(fn){
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  function closest(el, sel){
    return (el && el.closest) ? el.closest(sel) : null;
  }

  function setupFiles(){
    document.querySelectorAll('stimma-files .sp-lightbox').forEach(function(box){
      box.hidden = false;
    });

    function fold(head){
      var li = head.parentElement;
      var folded = li.classList.toggle('sp-collapsed');
      head.setAttribute('aria-expanded', folded ? 'false' : 'true');
    }

    function openPreview(row){
      var li = row.parentElement;
      var src = li.getAttribute('data-preview');
      var files = closest(row, 'stimma-files');
      var box = files ? files.querySelector('.sp-lightbox') : null;
      if (!src || !box) return;
      var img = box.querySelector('img');
      var cap = box.querySelector('figcaption');
      var name = row.querySelector('.sp-name');
      var size = row.querySelector('.sp-meta');
      var label = (name ? name.textContent : '') + (size ? '  ·  ' + size.textContent : '');
      // Name it straight away; the pixel dimensions arrive with the image.
      cap.textContent = label;
      img.onload = function(){
        cap.textContent = (name ? name.textContent : '') +
          '  ·  ' + img.naturalWidth + ' × ' + img.naturalHeight +
          (size ? '  ·  ' + size.textContent : '');
      };
      img.setAttribute('src', src);
      box.classList.add('sp-open');
    }

    function closePreview(){
      document.querySelectorAll('.sp-lightbox.sp-open').forEach(function(box){
        box.classList.remove('sp-open');
        var img = box.querySelector('img');
        if (img) img.removeAttribute('src');
      });
    }

    document.addEventListener('click', function(ev){
      var target = ev.target;
      if (closest(target, '.sp-lightbox')) { closePreview(); return; }
      if (closest(target, 'a')) return;
      var head = closest(target, 'li.sp-dir > .sp-row');
      if (head) { fold(head); return; }
      var row = closest(target, 'li.sp-previewable > .sp-row');
      if (row) openPreview(row);
    });

    document.addEventListener('keydown', function(ev){
      if (ev.key === 'Escape') { closePreview(); return; }
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      var head = closest(document.activeElement, 'li.sp-dir > .sp-row');
      if (head) { ev.preventDefault(); fold(head); }
    });
  }

  function setupCompare(){
    document.querySelectorAll('stimma-compare[mode="slider"]').forEach(function(el){
      var wrap = el.querySelector('.sp-cmp');
      if (!wrap) return;
      var imgs = wrap.querySelectorAll('img');
      if (imgs.length < 2) return;
      el.classList.add('sp-slider');
      var range = document.createElement('input');
      range.type = 'range'; range.min = 0; range.max = 100; range.value = 50;
      range.setAttribute('aria-label', 'Compare');
      function apply(){ el.style.setProperty('--sp-split', range.value + '%'); }
      function size(){ el.style.setProperty('--sp-w', wrap.clientWidth + 'px'); }
      range.addEventListener('input', apply);
      window.addEventListener('resize', size);
      imgs[1].addEventListener('load', size);
      el.appendChild(range); size(); apply();
    });
  }

  ready(function(){ setupFiles(); setupCompare(); });
})();
"""


def footer(text: str = "Made with Stimma") -> str:
    """The maker's mark. Embedded, so it survives a zip on a plane."""
    label = escape(text).replace("Stimma", '</span><span class="sp-wordmark">stimma</span><span>')
    return (
        f'<p class="sp-footer">{LOGO_SVG}'
        f'<span class="sp-brand"><span>{label}</span></span></p>'
    )


# Expansion ------------------------------------------------------------------

_TAG_RE_TEMPLATE = r"<{tag}\b(?P<attrs>[^>]*?)(?:/>|>(?P<inner>.*?)</{tag}>)"
_ATTR_RE = re.compile(r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'=<>`]+)))?')


def _parse_attrs(text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for m in _ATTR_RE.finditer(text or ""):
        name = m.group(1)
        value = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
        attrs[name.lower()] = "" if value is None else value
    return attrs


def _attr_str(attrs: dict[str, str]) -> str:
    return "".join(f' {k}="{htmllib.escape(v, quote=True)}"' for k, v in attrs.items())


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _media_markup(path: str, *, alt: str = "", caption: str = "") -> str:
    ext = Path(path).suffix.lower()
    src = htmllib.escape(path, quote=True)
    if ext in VIDEO_EXTS:
        body = f'<video controls preload="metadata" src="{src}"></video>'
    elif ext in IMAGE_EXTS:
        body = f'<img src="{src}" alt="{htmllib.escape(alt, quote=True)}" loading="lazy">'
    else:
        body = f'<a href="{src}" download>{htmllib.escape(Path(path).name)}</a>'
    if caption:
        body += f'<div class="sp-caption">{htmllib.escape(caption)}</div>'
    return body


def _tree(entries: list[dict[str, Any]], root: str) -> dict[str, Any]:
    """Nest flat file entries under ``root`` into {name: {..}} folders."""
    tree: dict[str, Any] = {}
    for entry in entries:
        rel = entry["path"][len(root):] if root and entry["path"].startswith(root) else entry["path"]
        parts = rel.split("/")
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {"__dir__": True})
        node[parts[-1]] = {"__file__": entry}
    return tree


_ICON_DOWNLOAD = (
    '<svg viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M12 3v12m0 0 4-4m-4 4-4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>'
)
_ICON_ARCHIVE = (
    '<svg viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M3 7h18M4 7v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7M3 7l1.6-3h14.8L21 7M10 12h4"/></svg>'
)


_CARET = '<span class="sp-caret"><svg viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg></span>'
_GLYPH_FOLDER = ('<span class="sp-glyph"><svg viewBox="0 0 24 24">'
                 '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
                 '</svg></span>')
_GLYPH_FILE = ('<span class="sp-glyph"><svg viewBox="0 0 24 24">'
               '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
               '<path d="M14 3v5h5"/></svg></span>')
_PREVIEWABLE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
_LIGHTBOX = ('<div class="sp-lightbox" hidden><figure><img src="" alt="">'
             '<figcaption></figcaption></figure></div>')


def _download_href(path: str) -> str:
    sep = "&" if "?" in path else "?"
    return htmllib.escape(f"{path}{sep}download=1", quote=True)


def _render_tree(node: dict[str, Any], prefix: str, depth: int = 0) -> str:
    items = sorted(node.items(), key=lambda kv: (not isinstance(kv[1], dict) or "__file__" in kv[1], kv[0].lower()))
    out = ["<ul>"]
    for name, child in items:
        if name in ("__dir__", "__file__"):
            continue
        safe = htmllib.escape(name)
        if "__file__" in child:
            entry = child["__file__"]
            path = entry["path"]
            ext = Path(path).suffix.lower()
            previewable = ext in _PREVIEWABLE
            lead = (
                f'<img class="sp-thumb" src="{htmllib.escape(path, quote=True)}" alt="" loading="lazy">'
                if previewable else _GLYPH_FILE
            )
            cls = ' class="sp-previewable"' if previewable else ""
            data = f' data-preview="{htmllib.escape(path, quote=True)}"' if previewable else ""
            out.append(
                f'<li{cls}{data}><div class="sp-row">{lead}<span class="sp-name">{safe}</span>'
                f'<span class="sp-meta">{human_size(int(entry.get("size") or 0))}</span>'
                f'<a class="sp-dl" href="{_download_href(path)}" download'
                f' aria-label="Download {htmllib.escape(name, quote=True)}">{_ICON_DOWNLOAD}</a></div></li>'
            )
        else:
            count = _count_files(child)
            # Open by default: the point of showing files is showing them. Only a
            # folder big enough to bury the rest of the page arrives folded, and
            # every folder can be folded by the reader.
            collapsed = " sp-collapsed" if count > 20 else ""
            out.append(
                f'<li class="sp-dir{collapsed}"><div class="sp-row" role="button" tabindex="0"'
                f' aria-expanded="{"false" if collapsed else "true"}">{_CARET}{_GLYPH_FOLDER}'
                f'<span class="sp-name">{safe}</span>'
                f'<span class="sp-meta">{count}</span></div>'
                f'{_render_tree(child, prefix + name + "/", depth + 1)}</li>'
            )
    out.append("</ul>")
    return "".join(out)


def _count_files(node: dict[str, Any]) -> int:
    total = 0
    for name, child in node.items():
        if name in ("__dir__", "__file__") or not isinstance(child, dict):
            continue
        total += 1 if "__file__" in child else _count_files(child)
    return total


def _files_markup(manifest: dict[str, Any], ref: str) -> str:
    run = run_by_id(manifest, ref)
    if run is not None:
        root = (run.get("root") or "").rstrip("/")
        entries = run.get("files") or []
        total = sum(int(e.get("size") or 0) for e in entries)
        zip_href = _download_href(f"{root}.zip")
        head = (
            f'<div class="sp-files-top">'
            f'<span class="sp-files-what">{len(entries)} files</span>'
            f'<a class="sp-zip" href="{zip_href}" download>{_ICON_ARCHIVE}'
            f'<b>Download {htmllib.escape(root)}.zip</b> <em>{_human_size(total)}</em></a></div>'
        )
        return head + _render_tree(_tree(entries, root + "/"), root + "/") + _LIGHTBOX

    sections = [{"path": m["path"], "size": m.get("size", 0)} for m in manifest.get("members") or []]
    for run in manifest.get("runs") or []:
        sections.extend(run.get("files") or [])
    for extra in manifest.get("extras") or []:
        sections.append({"path": extra["path"], "size": extra.get("size", 0)})
    total = sum(int(e.get("size") or 0) for e in sections)
    head = (
        f'<div class="sp-files-top"><span class="sp-files-what">{len(sections)} files</span>'
        f'<span class="sp-meta">{_human_size(total)}</span></div>'
    )
    return head + _render_tree(_tree(sections, ""), "") + _LIGHTBOX


def _resolve_path(manifest: dict[str, Any], ref: str) -> Optional[str]:
    resolved = resolve_ref(manifest, ref)
    if resolved is None or resolved["kind"] == "run":
        return None
    return resolved["path"]


# Tinted neighbours, so a home screen reads as somebody's phone rather than a
# wireframe of grey boxes. Separate ramps per mode: the same tints that look
# like apps on a dark wallpaper look like smudges on a light one.
_NEIGHBOURS_DARK = (
    "linear-gradient(160deg,#6f8bd6,#3c56a8)", "linear-gradient(160deg,#e59b5a,#c2632c)",
    "linear-gradient(160deg,#63c49a,#2f8b68)", "linear-gradient(160deg,#b478d6,#6f3fa8)",
    "linear-gradient(160deg,#e06f7a,#a83c50)", "linear-gradient(160deg,#8a93a8,#555d70)",
    "linear-gradient(160deg,#e3c65c,#b3902a)", "linear-gradient(160deg,#5fb6cc,#2b7d96)",
    "linear-gradient(160deg,#9aa4b8,#606a80)", "linear-gradient(160deg,#7fb45e,#4a7f34)",
    "linear-gradient(160deg,#d67fa8,#a03f72)", "linear-gradient(160deg,#5c7fd0,#31479a)",
    "linear-gradient(160deg,#d9a15f,#a86c2e)", "linear-gradient(160deg,#72c7b4,#358c7e)",
    "linear-gradient(160deg,#a88ede,#6a4bb0)", "linear-gradient(160deg,#cf8f6d,#96543a)",
    "linear-gradient(160deg,#7d8ea6,#4c5a6e)", "linear-gradient(160deg,#c9d36a,#939b32)",
    "linear-gradient(160deg,#68a8d6,#35688f)", "linear-gradient(160deg,#b0b6c4,#71788a)",
    "linear-gradient(160deg,#8fc06e,#578c3d)", "linear-gradient(160deg,#d67f92,#a04360)",
    "linear-gradient(160deg,#6fbfae,#337f75)",
)
_NEIGHBOURS_LIGHT = (
    "linear-gradient(160deg,#89a3e8,#5570c4)", "linear-gradient(160deg,#f3ad69,#d9793f)",
    "linear-gradient(160deg,#78d9ad,#3f9f78)", "linear-gradient(160deg,#c78ce8,#8452bd)",
    "linear-gradient(160deg,#f0838f,#c45164)", "linear-gradient(160deg,#a6afc4,#6c7588)",
    "linear-gradient(160deg,#f2d871,#c7a43a)", "linear-gradient(160deg,#74cbe0,#3b93ad)",
    "linear-gradient(160deg,#b3bccf,#788298)", "linear-gradient(160deg,#94c973,#5d9442)",
    "linear-gradient(160deg,#e895bd,#b45286)", "linear-gradient(160deg,#7e9be0,#4a67bb)",
    "linear-gradient(160deg,#eeb27f,#cc7f47)", "linear-gradient(160deg,#88ddc6,#45a692)",
    "linear-gradient(160deg,#bb9ae8,#7d5cc0)", "linear-gradient(160deg,#e0a087,#ad6849)",
    "linear-gradient(160deg,#9aa8bd,#68738a)", "linear-gradient(160deg,#dde386,#a9b046)",
    "linear-gradient(160deg,#82bde8,#4a83ab)", "linear-gradient(160deg,#c6cddb,#8a93a6)",
    "linear-gradient(160deg,#a6d78c,#6aa352)", "linear-gradient(160deg,#e8a3bd,#b5637f)",
    "linear-gradient(160deg,#85cfc0,#48968a)",
)

_STATUS_BAR = (
    '<div class="sp-statusbar"><span>9:41</span>'
    '<span style="display:flex;align-items:center;gap:4px">'
    '<span class="sp-bars"><i style="height:3px"></i><i style="height:5px"></i>'
    '<i style="height:7px"></i><i style="height:9px"></i></span>'
    '<span class="sp-batt"></span></span></div>'
)


def _iphone_markup(src: str, label: str, mode: str = "dark") -> str:
    """A springboard with the icon in place: status bar, apps, dock, home bar."""
    tints = _NEIGHBOURS_DARK if mode == "dark" else _NEIGHBOURS_LIGHT
    cells = [f'<div class="sp-app sp-mine"><img src="{escape(src)}" alt=""><em>{escape(label)}</em></div>']
    cells += [f'<div class="sp-app"><i style="background:{tint}"></i><em></em></div>' for tint in tints]
    dock = '<div class="sp-dock">' + "".join(
        f'<i style="background:{tint}"></i>' for tint in tints[:4]
    ) + "</div>"
    return (
        f'<div class="sp-phone sp-{mode}"><div class="sp-island"></div><div class="sp-screen">'
        f'{_STATUS_BAR}<div class="sp-apps">{"".join(cells)}</div>{dock}'
        f'<div class="sp-homebar"></div></div></div>'
    )


DEVICES = {"iphone": _iphone_markup}


def device_pair(ref: str, label: str) -> str:
    """The same icon on a light and a dark home screen, side by side.

    One background flatters an icon and the other exposes it, and which is
    which depends on the artwork — so a presentation shows both rather than
    picking the kind one.
    """
    cases = "".join(
        f'<div class="sp-devicecase">{_iphone_markup(ref, label, mode)}<span>{mode.title()}</span></div>'
        for mode in ("light", "dark")
    )
    return f"<stimma-devices>{cases}</stimma-devices>"


def contexts_markup(src: str, name: str, subtitle: str = "") -> str:
    """The other surfaces an icon has to survive: a store row, a setting, an alert."""
    src = escape(src)
    name = escape(name)
    sub = escape(subtitle or "Your app")
    return (
        '<stimma-contexts>'
        f'<div class="sp-ctx"><img src="{src}" width="56" height="56" alt="">'
        f'<div class="sp-ctx-body"><b>{name}</b><span>{sub}</span></div>'
        '<span class="sp-get">GET</span></div>'
        f'<div class="sp-ctx"><img src="{src}" width="29" height="29" alt="">'
        f'<div class="sp-ctx-body"><b>{name}</b></div><span class="sp-chev">›</span></div>'
        f'<div class="sp-ctx sp-notify"><img src="{src}" width="38" height="38" alt="">'
        f'<div class="sp-ctx-body"><b>{name}</b><span>Your weekly summary is ready.</span></div>'
        '<span class="sp-when">now</span></div>'
        '</stimma-contexts>'
    )


def expand_kit_elements(manifest: dict[str, Any], body: str) -> tuple[str, list[str]]:
    """Expand empty kit elements into static HTML. Returns (html, problems)."""
    problems: list[str] = []
    counters: dict[str, int] = {}
    seen_ids: set[str] = set()

    def next_id(tag: str, ref: str) -> str:
        counters[tag] = counters.get(tag, 0) + 1
        base = re.sub(r"[^a-z0-9-]+", "-", (ref or tag).lower()).strip("-") or tag
        candidate = f"{base}-{counters[tag]}"
        while candidate in seen_ids:
            counters[tag] += 1
            candidate = f"{base}-{counters[tag]}"
        return candidate

    def register_id(attrs: dict[str, str], tag: str) -> None:
        el_id = attrs.get("id")
        if el_id:
            if el_id in seen_ids:
                problems.append(f"duplicate id {el_id!r} on <{tag}>")
            seen_ids.add(el_id)
        else:
            attrs["id"] = next_id(tag, attrs.get("ref", ""))
            seen_ids.add(attrs["id"])

    def media_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        inner = (m.group("inner") or "").strip()
        register_id(attrs, "stimma-media")
        ref = attrs.get("ref", "")
        path = _resolve_path(manifest, ref)
        if path is None:
            problems.append(f"<stimma-media ref=\"{ref}\"> does not resolve to a member or file in this package")
            return f"<stimma-media{_attr_str(attrs)}>{inner}</stimma-media>"
        attrs["data-path"] = path
        if inner:
            return f"<stimma-media{_attr_str(attrs)}>{inner}</stimma-media>"
        member = member_by_id(manifest, ref)
        alt = attrs.get("alt") or (member.get("name") if member else Path(path).name)
        px = attrs.get("size")
        caption = attrs.get("caption", "")
        if px and px.isdigit():
            # A real-size preview: the browser must not scale it.
            inner_html = (
                f'<img src="{htmllib.escape(path, quote=True)}" width="{px}" height="{px}"'
                f' alt="{htmllib.escape(alt or "", quote=True)}">'
            )
            if not caption:
                caption = px
            inner_html += f'<div class="sp-caption">{htmllib.escape(str(caption))}</div>'
            return f"<stimma-media{_attr_str(attrs)}>{inner_html}</stimma-media>"
        return f"<stimma-media{_attr_str(attrs)}>{_media_markup(path, alt=alt, caption=caption)}</stimma-media>"

    def files_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        inner = (m.group("inner") or "").strip()
        register_id(attrs, "stimma-files")
        ref = attrs.get("ref", "")
        if ref and run_by_id(manifest, ref) is None and ref != "package":
            problems.append(f"<stimma-files ref=\"{ref}\"> does not name a run in this package (use a run id or omit ref)")
            return f"<stimma-files{_attr_str(attrs)}>{inner}</stimma-files>"
        if inner:
            return f"<stimma-files{_attr_str(attrs)}>{inner}</stimma-files>"
        return f"<stimma-files{_attr_str(attrs)}>{_files_markup(manifest, ref)}</stimma-files>"

    def compare_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        inner = (m.group("inner") or "").strip()
        register_id(attrs, "stimma-compare")
        if inner:
            return f"<stimma-compare{_attr_str(attrs)}>{inner}</stimma-compare>"
        a, bref = attrs.get("a", ""), attrs.get("b", "")
        pa, pb = _resolve_path(manifest, a), _resolve_path(manifest, bref)
        if pa is None or pb is None:
            problems.append(f"<stimma-compare a=\"{a}\" b=\"{bref}\"> has an unresolved side")
            return f"<stimma-compare{_attr_str(attrs)}></stimma-compare>"
        la = htmllib.escape(attrs.get("label-a", "A"))
        lb = htmllib.escape(attrs.get("label-b", "B"))
        body = (
            f'<div class="sp-cmp"><figure>{_media_markup(pa)}<figcaption>{la}</figcaption></figure>'
            f'<figure>{_media_markup(pb)}<figcaption>{lb}</figcaption></figure></div>'
        )
        return f"<stimma-compare{_attr_str(attrs)}>{body}</stimma-compare>"

    def grid_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        register_id(attrs, "stimma-grid")
        return f"<stimma-grid{_attr_str(attrs)}>"

    def section_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        inner = m.group("inner") or ""
        label = attrs.pop("label", "")
        head = f'<p class="sp-label">{htmllib.escape(label)}</p>' if label else ""
        return f"<stimma-section{_attr_str(attrs)}>{head}{inner}</stimma-section>"

    def device_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        register_id(attrs, "stimma-device")
        kind = attrs.get("kind", "iphone")
        ref = attrs.get("ref", "")
        path = _resolve_path(manifest, ref)
        builder = DEVICES.get(kind)
        if path is None or builder is None:
            problems.append(
                f'<stimma-device kind="{kind}" ref="{ref}"> could not be placed'
                + ("" if builder else f'; known devices: {", ".join(DEVICES)}')
            )
            return f"<stimma-device{_attr_str(attrs)}></stimma-device>"
        return f"<stimma-device{_attr_str(attrs)}>{builder(path, attrs.get('label', ''))}</stimma-device>"

    def column_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        inner = (m.group("inner") or "").strip()
        title = attrs.pop("title", "")
        head = f"<h3>{htmllib.escape(title)}</h3>" if title else ""
        return f"<stimma-column{_attr_str(attrs)}>{head}<p>{inner}</p></stimma-column>"

    flags = re.IGNORECASE | re.DOTALL
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-device"), device_sub, body, flags=flags)
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-column"), column_sub, body, flags=flags)
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-section"), section_sub, body, flags=flags)
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-media"), media_sub, body, flags=flags)
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-files"), files_sub, body, flags=flags)
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-compare"), compare_sub, body, flags=flags)
    body = re.sub(r"<stimma-grid\b(?P<attrs>[^>]*)>", grid_sub, body, flags=flags)
    for tag in RESERVED_COMPONENTS:
        for m in re.finditer(rf"<{tag}\b(?P<attrs>[^>]*)>", body, flags=flags):
            attrs = _parse_attrs(m.group("attrs"))
            if attrs.get("id"):
                if attrs["id"] in seen_ids:
                    problems.append(f"duplicate id {attrs['id']!r} on <{tag}>")
                seen_ids.add(attrs["id"])
    return body, problems
