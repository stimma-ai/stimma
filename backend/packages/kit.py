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
  padding-bottom:12px;border-bottom:1px solid var(--sp-line);margin-bottom:6px}
.sp-files-what{font-size:13px;color:var(--sp-muted)}
stimma-files ul{list-style:none;margin:0;padding:0}
stimma-files li>div{display:flex;align-items:center;gap:10px;padding:5px 0;min-height:30px}
stimma-files li.sp-dir>ul{margin-left:9px;padding-left:13px;border-left:1px solid var(--sp-line)}
stimma-files li.sp-dir>div{cursor:pointer;user-select:none}
stimma-files li.sp-dir.sp-collapsed>ul{display:none}
stimma-files .sp-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-size:13.5px;color:var(--sp-fg)}
stimma-files li.sp-dir>div .sp-name{color:var(--sp-muted)}
stimma-files .sp-meta{color:var(--sp-faint);font-size:12px;font-variant-numeric:tabular-nums;flex:none}
stimma-files .sp-caret{width:12px;height:12px;flex:none;color:var(--sp-faint);
  transition:transform .15s}
stimma-files li.sp-dir.sp-collapsed>div .sp-caret{transform:rotate(-90deg)}
stimma-files .sp-caret svg{width:12px;height:12px;stroke:currentColor;fill:none;stroke-width:2;
  stroke-linecap:round;stroke-linejoin:round}
.sp-dl{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;
  border-radius:6px;color:var(--sp-faint);flex:none;opacity:0;transition:color .15s,background-color .15s,opacity .15s}
stimma-files li>div:hover .sp-dl{opacity:1}
.sp-dl:hover{color:var(--sp-fg);background:var(--sp-plate)}
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

/* Recipe presentations ---------------------------------------------------- */
.sp-hero{display:flex;align-items:center;justify-content:center;gap:64px;flex-wrap:wrap;margin-top:36px}
.sp-hero-icon{flex:none}
.sp-hero-icon img{width:172px;height:172px;border-radius:22.37%;
  box-shadow:0 20px 44px rgba(0,0,0,.5)}
.sp-hero-icon span{font-size:12px;color:var(--sp-faint);font-variant-numeric:tabular-nums}

.sp-phone{flex:none;width:228px;aspect-ratio:9/19.5;border-radius:38px;padding:8px;
  background:#2c2c30;
  box-shadow:0 26px 64px rgba(0,0,0,.55)}
.sp-screen{width:100%;height:100%;border-radius:31px;overflow:hidden;position:relative;
  background:radial-gradient(130% 90% at 20% 0%,#5a6d8c 0%,#2b3548 45%,#161b27 100%);
  display:flex;flex-direction:column}
.sp-statusbar{display:flex;align-items:center;justify-content:space-between;
  padding:9px 16px 0;font-size:9px;color:#fff;opacity:.92;font-weight:600}
.sp-statusbar .sp-bars{display:flex;align-items:flex-end;gap:1.5px}
.sp-statusbar .sp-bars i{display:block;width:2px;background:#fff;border-radius:1px}
.sp-statusbar .sp-batt{width:14px;height:7px;border:1px solid rgba(255,255,255,.85);
  border-radius:2px;position:relative}
.sp-statusbar .sp-batt::after{content:"";position:absolute;inset:1px;right:4px;background:#fff;border-radius:1px}
.sp-apps{flex:1;display:grid;grid-template-columns:repeat(4,1fr);
  align-content:start;gap:14px 8px;padding:14px 12px 0}
.sp-app{display:grid;justify-items:center;gap:4px}
.sp-app img,.sp-app i{display:block;width:40px;height:40px;border-radius:22.37%}
.sp-app i{background:rgba(255,255,255,.16);box-shadow:inset 0 1px 0 rgba(255,255,255,.12)}
.sp-app em{font-style:normal;font-size:7.5px;line-height:1;color:#fff;opacity:.92;
  text-shadow:0 1px 2px rgba(0,0,0,.5);max-width:46px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sp-app.sp-mine img{box-shadow:0 4px 12px rgba(0,0,0,.4)}
.sp-dock{margin:0 10px 10px;padding:8px;border-radius:24px;background:rgba(255,255,255,.14);
  display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.sp-dock i{display:block;width:40px;height:40px;border-radius:22.37%;
  background:rgba(255,255,255,.18);justify-self:center}

"""

KIT_JS = r"""
(function(){
  if (window.__stimmaKit) return; window.__stimmaKit = true;
  var manifestEl = document.getElementById('stimma-package-manifest');
  var manifest = null;
  try { manifest = manifestEl ? JSON.parse(manifestEl.textContent) : null; } catch (e) { manifest = null; }
  window.stimmaPackage = { manifest: manifest, kitVersion: %(kit_version)d, host: document.documentElement.getAttribute('data-stimma-host') || null };
  function define(name, cls){ if (window.customElements && !customElements.get(name)) customElements.define(name, cls); }
  var Passive = function(){ return Reflect.construct(HTMLElement, [], this.constructor); };
  Passive.prototype = Object.create(HTMLElement.prototype); Passive.prototype.constructor = Passive;
  // Static-first: the server already expanded these. The classes only enhance.
  define('stimma-media', class extends HTMLElement {});
  define('stimma-grid', class extends HTMLElement {});
  define('stimma-pick', class extends HTMLElement {});
  define('stimma-approve', class extends HTMLElement {});
  define('stimma-comments', class extends HTMLElement {});
  define('stimma-files', class extends HTMLElement {
    connectedCallback(){
      var self = this;
      self.querySelectorAll('li.sp-dir > div').forEach(function(head){
        head.addEventListener('click', function(ev){
          if (ev.target && ev.target.tagName === 'A') return;
          head.parentElement.classList.toggle('sp-collapsed');
        });
      });
    }
  });
  define('stimma-compare', class extends HTMLElement {
    connectedCallback(){
      var self = this;
      if (self.getAttribute('mode') !== 'slider') return;
      var wrap = self.querySelector('.sp-cmp'); if (!wrap) return;
      var first = wrap.querySelector('figure:first-child'); var imgs = wrap.querySelectorAll('img');
      if (imgs.length < 2) return;
      self.classList.add('sp-slider');
      var range = document.createElement('input'); range.type = 'range'; range.min = 0; range.max = 100; range.value = 50;
      function apply(){ self.style.setProperty('--sp-split', range.value + '%'); }
      function size(){ self.style.setProperty('--sp-w', wrap.clientWidth + 'px'); }
      range.addEventListener('input', apply); window.addEventListener('resize', size);
      self.appendChild(range); size(); apply();
      imgs[1].addEventListener('load', size);
    }
  });
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


def _download_href(path: str) -> str:
    sep = "&" if "?" in path else "?"
    return htmllib.escape(f"{path}{sep}download=1", quote=True)


def _render_tree(node: dict[str, Any], prefix: str) -> str:
    items = sorted(node.items(), key=lambda kv: (not isinstance(kv[1], dict) or "__file__" in kv[1], kv[0].lower()))
    out = ["<ul>"]
    for name, child in items:
        if name in ("__dir__", "__file__"):
            continue
        safe = htmllib.escape(name)
        if "__file__" in child:
            entry = child["__file__"]
            out.append(
                f'<li><div><span class="sp-name">{safe}</span>'
                f'<span class="sp-meta">{_human_size(int(entry.get("size") or 0))}</span>'
                f'<a class="sp-dl" href="{_download_href(entry["path"])}" download'
                f' aria-label="Download {htmllib.escape(name, quote=True)}">{_ICON_DOWNLOAD}</a></div></li>'
            )
        else:
            count = _count_files(child)
            out.append(
                f'<li class="sp-dir"><div>{_CARET}<span class="sp-name">{safe}</span>'
                f'<span class="sp-meta">{count}</span></div>{_render_tree(child, prefix + name + "/")}</li>'
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
        return head + _render_tree(_tree(entries, root + "/"), root + "/")

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
    return head + _render_tree(_tree(sections, ""), "")


def _resolve_path(manifest: dict[str, Any], ref: str) -> Optional[str]:
    resolved = resolve_ref(manifest, ref)
    if resolved is None or resolved["kind"] == "run":
        return None
    return resolved["path"]


_NEIGHBOUR_TINTS = (
    "rgba(255,255,255,.18)", "rgba(120,180,255,.30)", "rgba(255,190,120,.26)",
    "rgba(150,230,190,.26)", "rgba(220,150,235,.24)", "rgba(255,255,255,.13)",
    "rgba(255,150,150,.24)", "rgba(160,190,255,.22)", "rgba(255,255,255,.20)",
    "rgba(200,235,150,.24)", "rgba(255,255,255,.15)",
)


def _iphone_markup(src: str, label: str) -> str:
    """A believable springboard: status bar, a grid of apps, a dock.

    Placeholders are tinted rather than grey so it reads as somebody's phone
    instead of a wireframe.
    """
    cells = [f'<div class="sp-app sp-mine"><img src="{escape(src)}" alt=""><em>{escape(label)}</em></div>']
    cells += [f'<div class="sp-app"><i style="background:{tint}"></i><em></em></div>' for tint in _NEIGHBOUR_TINTS]
    status = (
        '<div class="sp-statusbar"><span>9:41</span>'
        '<span style="display:flex;align-items:center;gap:4px">'
        '<span class="sp-bars"><i style="height:3px"></i><i style="height:5px"></i>'
        '<i style="height:7px"></i><i style="height:9px"></i></span>'
        '<span class="sp-batt"></span></span></div>'
    )
    dock = '<div class="sp-dock">' + "<i></i>" * 4 + "</div>"
    return (
        f'<div class="sp-phone"><div class="sp-screen">{status}'
        f'<div class="sp-apps">{"".join(cells)}</div>{dock}</div></div>'
    )


DEVICES = {"iphone": _iphone_markup}


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
