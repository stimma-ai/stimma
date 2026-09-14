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

KIT_VERSION = 3

# The elements a cover may use. Anything else is the author's own markup.
COMPONENTS = (
    "stimma-section", "stimma-media", "stimma-grid", "stimma-sizes",
    "stimma-columns", "stimma-column", "stimma-files",
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

/* Files: one quiet row that opens into a browser. Compact until asked, and
   native <details> so the tree is still reachable with scripts off. */
stimma-files{display:block}
.sp-files{display:block}
.sp-files>summary{list-style:none;display:flex;align-items:center;gap:12px;flex-wrap:wrap;
  padding:2px 0;cursor:pointer}
.sp-files>summary::-webkit-details-marker{display:none}
.sp-files>summary:focus{outline:none}
.sp-files>summary:focus-visible{outline:2px solid var(--sp-accent);outline-offset:4px;border-radius:8px}
.sp-files-what{font-size:13px;color:var(--sp-muted);flex:1;min-width:110px;
  font-variant-numeric:tabular-nums}
.sp-browse{display:inline-flex;align-items:center;gap:7px;font-size:13px;color:var(--sp-muted);
  padding:7px 12px;border-radius:7px;flex:none;transition:color .15s,background-color .15s}
.sp-files>summary:hover .sp-browse{color:var(--sp-fg);background:var(--sp-plate)}
.sp-files[open]>summary .sp-browse{color:var(--sp-fg)}
.sp-files[open]>summary .sp-browse .sp-caret{transform:rotate(180deg)}

/* The browser: one raised surface, divided by hairlines and nothing else. */
.sp-browser{display:grid;grid-template-columns:minmax(190px,270px) 1fr;
  margin-top:14px;border:1px solid var(--sp-line);border-radius:10px;overflow:hidden}
.sp-tree{padding:8px 6px;max-height:420px;overflow:auto;border-right:1px solid var(--sp-line)}
.sp-tree:focus{outline:none}
.sp-tree:focus-visible{outline:2px solid var(--sp-accent);outline-offset:-2px}
stimma-files ul{list-style:none;margin:0;padding:0}
stimma-files li{position:relative}
stimma-files .sp-row{display:flex;align-items:center;gap:10px;padding:5px 9px;min-height:32px;
  border-radius:7px;cursor:default;transition:background-color .12s}
stimma-files .sp-row:hover{background:var(--sp-plate)}
stimma-files .sp-row:focus{outline:none}
stimma-files .sp-row:focus-visible{outline:2px solid var(--sp-accent);outline-offset:-2px}
stimma-files .sp-row.sp-sel{background:var(--sp-plate);box-shadow:inset 2px 0 0 var(--sp-accent)}
stimma-files .sp-row.sp-sel .sp-name{color:var(--sp-fg)}
stimma-files li.sp-file>.sp-row{cursor:pointer}
stimma-files li.sp-dir>.sp-row{cursor:pointer;user-select:none}
stimma-files li.sp-dir>ul{margin-left:18px;padding-left:13px;border-left:1px solid var(--sp-line)}
stimma-files li.sp-dir.sp-collapsed>ul{display:none}
stimma-files .sp-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-size:13px;color:var(--sp-fg)}
stimma-files li.sp-dir>.sp-row .sp-name{color:var(--sp-muted)}
stimma-files .sp-meta{color:var(--sp-faint);font-size:12px;font-variant-numeric:tabular-nums;flex:none}
stimma-files .sp-caret{width:14px;height:14px;flex:none;color:var(--sp-faint);
  display:inline-flex;align-items:center;justify-content:center;transition:transform .15s}
stimma-files li.sp-dir.sp-collapsed>.sp-row .sp-caret{transform:rotate(-90deg)}
stimma-files .sp-caret svg{width:11px;height:11px;stroke:currentColor;fill:none;stroke-width:2.2;
  stroke-linecap:round;stroke-linejoin:round}
.sp-browse .sp-caret{color:inherit;width:11px;height:11px}
stimma-files .sp-thumb{width:22px;height:22px;flex:none;border-radius:4px;object-fit:contain;
  background:var(--sp-plate)}
stimma-files .sp-glyph{width:22px;height:22px;flex:none;display:inline-flex;align-items:center;
  justify-content:center;color:var(--sp-faint)}
stimma-files .sp-glyph svg{width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:1.6;
  stroke-linecap:round;stroke-linejoin:round}
.sp-dl{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;
  border-radius:6px;color:var(--sp-faint);flex:none;opacity:0;
  transition:color .15s,background-color .15s,opacity .15s}
stimma-files .sp-row:hover .sp-dl,stimma-files .sp-row.sp-sel .sp-dl,.sp-dl:focus-visible{opacity:1}
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

/* The viewer pane: a header line and the file itself. */
.sp-view{min-width:0;display:flex;flex-direction:column}
.sp-view-head{display:flex;align-items:center;gap:10px;padding:11px 14px 9px;min-height:42px}
.sp-vname{font-size:13px;color:var(--sp-fg);flex:none;max-width:45%;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.sp-vmeta{font-size:12px;color:var(--sp-faint);font-variant-numeric:tabular-nums;
  flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sp-vact{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--sp-muted);
  padding:5px 10px;border-radius:6px;flex:none;border:0;background:none;cursor:pointer;
  font-family:inherit;transition:color .15s,background-color .15s}
.sp-vact:hover{color:var(--sp-fg);background:var(--sp-plate)}
.sp-vact:focus{outline:none}
.sp-vact:focus-visible{outline:2px solid var(--sp-accent);outline-offset:1px}
.sp-vact svg{width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:1.75;
  stroke-linecap:round;stroke-linejoin:round}
.sp-vact[aria-pressed=true]{color:var(--sp-accent)}
.sp-view-body{flex:1;min-height:230px;max-height:420px;overflow:auto;padding:0 14px 14px;
  display:flex;flex-direction:column;gap:10px}
.sp-view-body.sp-center{align-items:center;justify-content:center;text-align:center}
.sp-shot{max-width:100%;width:auto;height:auto;border-radius:2px;
  background:repeating-conic-gradient(#8883 0% 25%,transparent 0% 50%) 50%/16px 16px}
video.sp-shot,audio.sp-shot{width:100%;background:none}
.sp-code{margin:0;font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  color:var(--sp-muted);white-space:pre-wrap;word-break:break-word;tab-size:2}
.sp-empty{color:var(--sp-faint);font-size:13px;margin:0}
.sp-blank{display:grid;justify-items:center;gap:8px;color:var(--sp-faint);font-size:13px}
.sp-blank .sp-glyph{width:40px;height:40px}
.sp-blank .sp-glyph svg{width:30px;height:30px}
.sp-vnote{color:var(--sp-faint);font-size:12px;margin:0}
@media (max-width:640px){
  .sp-browser{grid-template-columns:1fr}
  .sp-tree{border-right:0;border-bottom:1px solid var(--sp-line);max-height:220px}
}

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
  ['stimma-section','stimma-media','stimma-grid','stimma-sizes',
   'stimma-columns','stimma-column','stimma-files','stimma-compare',
   'stimma-pick','stimma-approve','stimma-comments'].forEach(define);

  function ready(fn){
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  function closest(el, sel){
    return (el && el.closest) ? el.closest(sel) : null;
  }

  // The file browser. Compact by default: a <details> whose summary is the
  // quiet row, and whose open state is a two-pane browser inside the page —
  // no overlay. The pane reads text straight out of the row, because a cover
  // has to work from a double-clicked file, where fetch() of a sibling file is
  // blocked by every browser.
  function setupFiles(){
    var DOT = '  ·  ';

    function el(tag, cls){
      var node = document.createElement(tag);
      if (cls) node.className = cls;
      return node;
    }

    function unpack(text){
      return text.replace(/<\\\//g, '</').replace(/<\\!--/g, '<!--');
    }

    function sourceOf(li){
      var holder = li.querySelector('script.sp-src');
      return holder ? unpack(holder.textContent) : null;
    }

    function fold(row){
      var li = row.parentElement;
      var folded = li.classList.toggle('sp-collapsed');
      row.setAttribute('aria-expanded', folded ? 'false' : 'true');
    }

    function visibleRows(files){
      return Array.prototype.filter.call(
        files.querySelectorAll('.sp-tree .sp-row'),
        function(row){ return row.offsetParent !== null; }
      );
    }

    function pretty(text){
      try { return JSON.stringify(JSON.parse(text), null, 2); } catch (e) { return text; }
    }

    function blank(body, label){
      body.className = 'sp-view-body sp-center';
      var box = el('div', 'sp-blank');
      var glyph = el('span', 'sp-glyph');
      glyph.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' +
        '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>' +
        '<path d="M14 3v5h5"/></svg>';
      var text = el('span');
      text.textContent = label;
      box.appendChild(glyph); box.appendChild(text);
      body.appendChild(box);
    }

    function render(files, row){
      var view = files.querySelector('.sp-view');
      if (!view) return;
      view.__row = row;
      var li = row.parentElement;
      var kind = li.getAttribute('data-kind') || 'other';
      var path = li.getAttribute('data-path') || '';
      var name = li.getAttribute('data-name') || '';
      var size = li.getAttribute('data-size') || '';
      var source = sourceOf(li);
      var showSource = kind === 'svg' && view.getAttribute('data-mode') === 'source';

      view.textContent = '';
      var header = el('div', 'sp-view-head');
      var title = el('span', 'sp-vname');
      title.textContent = name;
      var meta = el('span', 'sp-vmeta');
      meta.textContent = size;
      header.appendChild(title); header.appendChild(meta);
      var body = el('div', 'sp-view-body');

      if (kind === 'svg' && source !== null) {
        var toggle = el('button', 'sp-vact sp-src-toggle');
        toggle.type = 'button';
        toggle.textContent = 'Source';
        toggle.setAttribute('aria-pressed', showSource ? 'true' : 'false');
        header.appendChild(toggle);
      }
      // No href means the file is not alongside the page (a single-file
      // export), and an inert button is worse than no button.
      var dl = row.querySelector('.sp-dl');
      if (dl && dl.getAttribute('href') && kind !== 'folder') {
        var copy = dl.cloneNode(true);
        copy.className = 'sp-vact';
        var label = el('span');
        label.textContent = 'Download';
        copy.appendChild(label);
        header.appendChild(copy);
      }
      view.appendChild(header); view.appendChild(body);

      if (kind === 'folder') {
        meta.textContent = 'Folder' + DOT + (li.getAttribute('data-count') || '0') + ' files';
        body.className = 'sp-view-body sp-center';
        var hint = el('p', 'sp-empty');
        hint.textContent = 'Select a file to view it here.';
        body.appendChild(hint);
        return;
      }

      if (kind === 'image' || (kind === 'svg' && !showSource)) {
        body.className = 'sp-view-body sp-center';
        var img = el('img', 'sp-shot');
        img.alt = name;
        img.addEventListener('load', function(){
          if (img.naturalWidth) {
            meta.textContent = img.naturalWidth + ' × ' + img.naturalHeight + DOT + size;
          }
        });
        img.addEventListener('error', function(){
          body.textContent = '';
          blank(body, 'This file cannot be shown here' + DOT + size);
        });
        // The row's thumbnail is the same file, and it is the one reference a
        // single-file export rewrites — so it is the one worth following.
        var thumb = row.querySelector('.sp-thumb');
        img.src = (thumb && thumb.getAttribute('src')) || path;
        body.appendChild(img);
        return;
      }

      if (kind === 'text' || (kind === 'svg' && showSource)) {
        if (source === null) {
          body.className = 'sp-view-body sp-center';
          var away = el('p', 'sp-empty');
          away.textContent = 'Open the package to view this file.';
          body.appendChild(away);
          return;
        }
        var pre = el('pre', 'sp-code');
        pre.textContent = /\.(json|webmanifest)$/i.test(name) ? pretty(source) : source;
        body.appendChild(pre);
        if (li.getAttribute('data-truncated')) {
          var note = el('p', 'sp-vnote');
          note.textContent = 'Showing the first 64 KB of ' + size + '.';
          body.appendChild(note);
        }
        return;
      }

      if (kind === 'video' || kind === 'audio') {
        var player = el(kind === 'video' ? 'video' : 'audio', 'sp-shot');
        player.controls = true;
        player.preload = 'metadata';
        player.src = path;
        if (kind === 'video') {
          player.addEventListener('loadedmetadata', function(){
            if (player.videoWidth) {
              meta.textContent = player.videoWidth + ' × ' + player.videoHeight + DOT + size;
            }
          });
        }
        body.appendChild(player);
        return;
      }

      if (kind === 'icns') {
        blank(body, 'macOS icon' + DOT + size);
        return;
      }
      blank(body, (name.split('.').pop() || 'file').toUpperCase() + ' file' + DOT + size);
    }

    function select(files, row, focus){
      files.querySelectorAll('.sp-row.sp-sel').forEach(function(other){
        other.classList.remove('sp-sel');
        other.setAttribute('aria-selected', 'false');
      });
      row.classList.add('sp-sel');
      row.setAttribute('aria-selected', 'true');
      if (focus !== false) {
        try { row.focus({ preventScroll: true }); } catch (e) { row.focus(); }
      }
      render(files, row);
    }

    function move(files, delta){
      var list = visibleRows(files);
      if (!list.length) return;
      var current = files.querySelector('.sp-row.sp-sel');
      var at = list.indexOf(current);
      var next = at < 0 ? (delta > 0 ? 0 : list.length - 1)
                        : Math.min(list.length - 1, Math.max(0, at + delta));
      select(files, list[next], true);
    }

    function collapse(files){
      var box = files ? files.querySelector('details.sp-files') : null;
      var open = box ? [box] : Array.prototype.slice.call(
        document.querySelectorAll('stimma-files details.sp-files[open]'));
      open.forEach(function(details){
        if (!details.open) return;
        details.open = false;
        var summary = details.querySelector('summary');
        if (summary) summary.focus();
      });
    }

    // Opening for the first time puts something in the pane, so the browser
    // never reads as an empty box the reader has to poke at.
    document.querySelectorAll('stimma-files details.sp-files').forEach(function(details){
      details.addEventListener('toggle', function(){
        var files = closest(details, 'stimma-files');
        if (!details.open || !files || files.querySelector('.sp-row.sp-sel')) return;
        var first = files.querySelector('.sp-tree li.sp-file > .sp-row');
        if (first) select(files, first, false);
      });
    });

    document.addEventListener('click', function(ev){
      var toggle = closest(ev.target, '.sp-src-toggle');
      if (toggle) {
        var holder = closest(toggle, '.sp-view');
        var owner = closest(toggle, 'stimma-files');
        if (holder && owner && holder.__row) {
          holder.setAttribute('data-mode',
            holder.getAttribute('data-mode') === 'source' ? 'preview' : 'source');
          render(owner, holder.__row);
        }
        return;
      }
      // A download is a download: it never moves the selection or folds a row.
      if (closest(ev.target, 'a')) return;
      var row = closest(ev.target, 'stimma-files .sp-tree .sp-row');
      if (!row) return;
      var files = closest(row, 'stimma-files');
      if (!files) return;
      if (row.parentElement.classList.contains('sp-dir')) fold(row);
      select(files, row);
    });

    document.addEventListener('keydown', function(ev){
      var files = closest(ev.target, 'stimma-files') || closest(document.activeElement, 'stimma-files');
      if (ev.key === 'Escape') { collapse(files); return; }
      if (!files) return;
      // The summary, the source toggle and the download links keep their own
      // keyboard behaviour; the tree only claims keys aimed at the tree.
      if (closest(ev.target, 'summary') || closest(ev.target, 'a') || closest(ev.target, 'button')) return;
      if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
        ev.preventDefault();
        move(files, ev.key === 'ArrowDown' ? 1 : -1);
        return;
      }
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      var row = closest(ev.target, '.sp-row') || files.querySelector('.sp-row.sp-sel');
      if (!row) return;
      ev.preventDefault();
      if (row.parentElement.classList.contains('sp-dir')) fold(row);
      select(files, row);
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

# What the row can show as a 22px thumbnail: the browser draws these itself.
_PREVIEWABLE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"}
_RASTER_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".avif"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
# Anything a person would open in a text editor. A package is full of these —
# Contents.json, a manifest, a readme — and they are the files the engineer
# integrating the work actually needs to read.
_TEXT_EXTS = {
    ".json", ".webmanifest", ".txt", ".md", ".markdown", ".xml", ".html", ".htm",
    ".css", ".js", ".mjs", ".ts", ".plist", ".tres", ".tscn", ".yaml", ".yml",
    ".csv", ".tsv", ".toml", ".ini", ".cfg", ".conf", ".svg", ".srt", ".vtt",
    ".strings", ".gitignore", ".log", ".sql",
}
# A viewer shows a slab, not a whole book: past this the page pays for bytes
# nobody reads. The rest of the file is one download away.
TEXT_INLINE_MAX = 64 * 1024


def _file_kind(name: str) -> str:
    """Which viewer a file gets. Extension only — the cover is written once."""
    ext = Path(name).suffix.lower()
    if ext == ".svg":
        return "svg"
    if ext == ".icns":
        return "icns"
    if ext in _RASTER_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext in _TEXT_EXTS:
        return "text"
    return "other"


def _download_href(path: str) -> str:
    sep = "&" if "?" in path else "?"
    return htmllib.escape(f"{path}{sep}download=1", quote=True)


def _inline_text(bundle_dir: Optional[Path], rel: str) -> Optional[tuple[str, bool]]:
    """The file's text, for embedding in the row. ``(text, truncated)`` or None.

    A cover is opened from a double-clicked file as often as from a server, and
    there ``fetch()`` of a sibling file is blocked by every browser — so the
    text has to travel inside the page or not at all.
    """
    if bundle_dir is None:
        return None
    base = Path(bundle_dir)
    target = base / rel
    try:
        target.resolve().relative_to(base.resolve())
    except (ValueError, OSError):
        return None
    try:
        if not target.is_file():
            return None
        raw = target.read_bytes()[: TEXT_INLINE_MAX + 1]
    except OSError:
        return None
    truncated = len(raw) > TEXT_INLINE_MAX
    raw = raw[:TEXT_INLINE_MAX]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        if not truncated:
            return None  # binary wearing a text extension
        text = raw.decode("utf-8", errors="ignore")
    return text, truncated


def _source_script(text: str) -> str:
    """Text as an inert child of the row.

    ``</`` and ``<!--`` are the only sequences that can end or confuse script
    data, so they are the only ones escaped; the viewer puts them back, which
    keeps a file's bytes intact through the round trip.
    """
    payload = text.replace("</", "<\\/").replace("<!--", "<\\!--")
    return f'<script type="text/plain" class="sp-src">{payload}</script>'


def _render_tree(
    node: dict[str, Any],
    prefix: str,
    depth: int = 0,
    bundle_dir: Optional[Path] = None,
) -> str:
    items = sorted(node.items(), key=lambda kv: (not isinstance(kv[1], dict) or "__file__" in kv[1], kv[0].lower()))
    out = ['<ul role="group">' if depth else "<ul>"]
    for name, child in items:
        if name in ("__dir__", "__file__"):
            continue
        safe = htmllib.escape(name)
        quoted = htmllib.escape(name, quote=True)
        if "__file__" in child:
            entry = child["__file__"]
            path = entry["path"]
            size = int(entry.get("size") or 0)
            kind = _file_kind(name)
            src_path = htmllib.escape(path, quote=True)
            lead = (
                f'<img class="sp-thumb" src="{src_path}" alt="" loading="lazy">'
                if Path(name).suffix.lower() in _PREVIEWABLE else _GLYPH_FILE
            )
            body = ""
            extra = ""
            if kind in ("text", "svg"):
                inlined = _inline_text(bundle_dir, path)
                if inlined is None and kind == "text" and bundle_dir is not None:
                    kind = "other"  # binary wearing a text extension
                elif inlined is not None:
                    body = _source_script(inlined[0])
                    if inlined[1]:
                        extra = ' data-truncated="1"'
            out.append(
                f'<li class="sp-file" data-kind="{kind}" data-path="{src_path}"'
                f' data-name="{quoted}" data-bytes="{size}"'
                f' data-size="{human_size(size)}"{extra}>'
                f'<div class="sp-row" role="treeitem" tabindex="-1" aria-selected="false">'
                f'{lead}<span class="sp-name">{safe}</span>'
                f'<span class="sp-meta">{human_size(size)}</span>'
                f'<a class="sp-dl" href="{_download_href(path)}" download'
                f' aria-label="Download {quoted}">{_ICON_DOWNLOAD}</a></div>{body}</li>'
            )
        else:
            count = _count_files(child)
            # Open: the reader asked for the browser, so the browser shows what
            # is in it. Every folder still folds, and the pane scrolls.
            out.append(
                f'<li class="sp-dir" data-kind="folder" data-name="{quoted}" data-count="{count}">'
                f'<div class="sp-row" role="treeitem" tabindex="-1" aria-selected="false"'
                f' aria-expanded="true">{_CARET}{_GLYPH_FOLDER}'
                f'<span class="sp-name">{safe}</span>'
                f'<span class="sp-meta">{count}</span></div>'
                f'{_render_tree(child, prefix + name + "/", depth + 1, bundle_dir)}</li>'
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


def _browser_markup(count: int, total: int, action: str, tree: str) -> str:
    """The compact row, and the browser it opens into.

    ``<details>`` rather than a scripted toggle: closed is the resting state,
    and a reader with scripts off can still open it and read the tree.
    """
    plural = "file" if count == 1 else "files"
    return (
        '<details class="sp-files"><summary class="sp-files-top">'
        f'<span class="sp-files-what"><span class="sp-num">{count}</span> {plural}'
        f' · <span class="sp-num">{_human_size(total)}</span></span>{action}'
        f'<span class="sp-browse">Browse files{_CARET}</span></summary>'
        '<div class="sp-browser">'
        f'<div class="sp-tree" role="tree" tabindex="0">{tree}</div>'
        '<div class="sp-view"><div class="sp-view-head"><span class="sp-vname">Files</span></div>'
        '<div class="sp-view-body sp-center">'
        '<p class="sp-empty">Select a file to view it here.</p></div></div>'
        '</div></details>'
    )


def _files_markup(manifest: dict[str, Any], ref: str, bundle_dir: Optional[Path] = None) -> str:
    run = run_by_id(manifest, ref)
    if run is not None:
        root = (run.get("root") or "").rstrip("/")
        entries = run.get("files") or []
        total = sum(int(e.get("size") or 0) for e in entries)
        zip_href = _download_href(f"{root}.zip")
        action = (
            f'<a class="sp-zip" href="{zip_href}" download>{_ICON_ARCHIVE}'
            f'<b>Download {htmllib.escape(root)}.zip</b> <em>{_human_size(total)}</em></a>'
        )
        tree = _render_tree(_tree(entries, root + "/"), root + "/", bundle_dir=bundle_dir)
        return _browser_markup(len(entries), total, action, tree)

    sections = [{"path": m["path"], "size": m.get("size", 0)} for m in manifest.get("members") or []]
    for run in manifest.get("runs") or []:
        sections.extend(run.get("files") or [])
    for extra in manifest.get("extras") or []:
        sections.append({"path": extra["path"], "size": extra.get("size", 0)})
    total = sum(int(e.get("size") or 0) for e in sections)
    tree = _render_tree(_tree(sections, ""), "", bundle_dir=bundle_dir)
    return _browser_markup(len(sections), total, "", tree)


def _resolve_path(manifest: dict[str, Any], ref: str) -> Optional[str]:
    resolved = resolve_ref(manifest, ref)
    if resolved is None or resolved["kind"] == "run":
        return None
    return resolved["path"]


# Tinted neighbours, so a home screen reads as somebody's phone rather than a
# wireframe of grey boxes. Separate ramps per mode: the same tints that look
# like apps on a dark wallpaper look like smudges on a light one.
def expand_kit_elements(
    manifest: dict[str, Any],
    body: str,
    bundle_dir: Optional[Path] = None,
) -> tuple[str, list[str]]:
    """Expand empty kit elements into static HTML. Returns (html, problems).

    ``bundle_dir`` is where the package's files are on disk while it is being
    written. With it, text files travel inside the page and the file browser
    can show them offline; without it (a cover rendered from a manifest alone)
    the rows simply carry no source.
    """
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
        return f"<stimma-files{_attr_str(attrs)}>{_files_markup(manifest, ref, bundle_dir)}</stimma-files>"

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

    def column_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        inner = (m.group("inner") or "").strip()
        title = attrs.pop("title", "")
        head = f"<h3>{htmllib.escape(title)}</h3>" if title else ""
        return f"<stimma-column{_attr_str(attrs)}>{head}<p>{inner}</p></stimma-column>"

    flags = re.IGNORECASE | re.DOTALL
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
