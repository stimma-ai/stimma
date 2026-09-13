"""The cover: a package's front page.

Arbitrary HTML, CSS and JS from the author, plus a small kit of custom
elements for anything that touches members. The kit is static-first: every
kit element is expanded server-side into plain HTML when the bundle is
written, so the page reads correctly with scripts disabled, from a
double-clicked file, in a sandboxed frame, and in the thumbnail renderer.
The kit script only enhances (compare sliders, collapsible trees).

Refs are member ids, run ids, or bundle-relative paths the manifest declares.
Feedback widgets (``stimma-pick``, ``stimma-approve``, ``stimma-comments``)
are reserved: registered as no-ops so an authored cover using them degrades
to its children, never breaks.
"""

from __future__ import annotations

import base64
import html as htmllib
import io
import json
import mimetypes
import re
from pathlib import Path
from typing import Any, Optional

from packages.manifest import (
    COVER_NAME,
    KIT_VERSION,
    member_by_id,
    resolve_ref,
    run_by_id,
)

KIT_ELEMENTS = ("stimma-media", "stimma-files", "stimma-compare", "stimma-grid")
RESERVED_ELEMENTS = ("stimma-pick", "stimma-approve", "stimma-comments")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"}
VIDEO_EXTS = {".mp4", ".webm", ".mov"}
PREVIEW_MAX_SIDE = 1600


class CoverError(ValueError):
    pass


# Kit assets ----------------------------------------------------------------

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
.sp-page{max-width:920px;margin:0 auto;padding:72px 28px 120px}
.sp-title{font-size:clamp(30px,5vw,52px);line-height:1.02;letter-spacing:-0.025em;margin:0;font-weight:600}
.sp-sub{color:var(--sp-muted);margin:10px 0 0;font-size:15px}
.sp-sub b{color:var(--sp-fg);font-weight:500}
.sp-section{margin-top:72px}
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
.sp-files-top{display:flex;align-items:baseline;justify-content:space-between;gap:16px;margin-bottom:12px}
stimma-files ul{list-style:none;margin:0;padding:0}
stimma-files li>div{display:flex;align-items:center;gap:12px;padding:9px 0;border-bottom:1px solid var(--sp-line)}
stimma-files li:last-child>div{border-bottom:0}
stimma-files li.sp-dir>ul{margin-left:18px;padding-left:14px;border-left:1px solid var(--sp-line)}
stimma-files li.sp-dir>div{cursor:pointer;user-select:none;color:var(--sp-fg)}
stimma-files li.sp-dir.sp-collapsed>ul{display:none}
stimma-files .sp-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}
stimma-files .sp-dir>div .sp-name{color:var(--sp-muted)}
stimma-files .sp-meta{color:var(--sp-faint);font-size:12px;font-variant-numeric:tabular-nums}
.sp-dl{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;
  border-radius:6px;color:var(--sp-muted);flex:none;transition:color .15s,background-color .15s}
.sp-dl:hover{color:var(--sp-fg);background:var(--sp-plate)}
.sp-dl svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:1.75;
  stroke-linecap:round;stroke-linejoin:round}
.sp-getall{display:inline-flex;align-items:center;gap:8px;font-size:13px;color:var(--sp-accent);
  padding:6px 10px;border-radius:6px;transition:background-color .15s}
.sp-getall:hover{background:var(--sp-plate)}
.sp-getall svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:1.75;
  stroke-linecap:round;stroke-linejoin:round}

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

.sp-footer{margin-top:96px;padding-top:20px;border-top:1px solid var(--sp-line);
  color:var(--sp-faint);font-size:12px}

/* Recipe presentations ---------------------------------------------------- */
.sp-hero{display:flex;align-items:center;justify-content:center;gap:64px;flex-wrap:wrap;padding:8px 0}
.sp-hero-icon{flex:none}
.sp-hero-icon img{width:180px;height:180px;border-radius:22.37%;
  box-shadow:0 18px 40px rgba(0,0,0,.45)}
.sp-phone{flex:none;width:216px;aspect-ratio:9/19.5;border-radius:34px;padding:9px;
  background:#0b0b0c;box-shadow:0 24px 60px rgba(0,0,0,.5)}
.sp-screen{width:100%;height:100%;border-radius:26px;overflow:hidden;position:relative;
  background:linear-gradient(165deg,#3a4a63,#141a26 70%)}
.sp-screen .sp-apps{position:absolute;top:11%;left:0;right:0;display:grid;
  grid-template-columns:repeat(4,1fr);gap:14px 10px;padding:0 14px}
.sp-screen .sp-app{display:grid;justify-items:center;gap:5px}
.sp-screen .sp-app img,.sp-screen .sp-app span.sp-blank{width:38px;height:38px;border-radius:22.37%}
.sp-screen .sp-app span.sp-blank{background:rgba(255,255,255,.14)}
.sp-screen .sp-app em{font-style:normal;font-size:7px;color:#fff;opacity:.9;
  text-shadow:0 1px 2px rgba(0,0,0,.6)}
.sp-sizes{display:flex;align-items:flex-end;gap:26px;flex-wrap:wrap}
.sp-size{display:grid;justify-items:center;gap:8px}
.sp-size img{border-radius:22.37%;image-rendering:auto}
.sp-size span{font-size:11px;color:var(--sp-muted);font-variant-numeric:tabular-nums}
.sp-platforms{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:0}
.sp-platform{padding:16px 0;border-top:1px solid var(--sp-line)}
.sp-platform h3{margin:0 0 4px;font-size:14px;font-weight:500}
.sp-platform p{margin:0;font-size:13px;color:var(--sp-muted)}
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


def _render_tree(node: dict[str, Any], prefix: str) -> str:
    items = sorted(node.items(), key=lambda kv: (not isinstance(kv[1], dict) or "__file__" in kv[1], kv[0].lower()))
    out = ["<ul>"]
    for name, child in items:
        if name in ("__dir__", "__file__"):
            continue
        if "__file__" in child:
            entry = child["__file__"]
            href = htmllib.escape(entry["path"], quote=True)
            out.append(
                f'<li><div><span class="sp-name">{htmllib.escape(name)}</span>'
                f'<span class="sp-meta">{_human_size(int(entry.get("size") or 0))}</span>'
                f'<a class="sp-dl" href="{href}" download title="Download {htmllib.escape(name, quote=True)}"'
                f' aria-label="Download {htmllib.escape(name, quote=True)}">{_ICON_DOWNLOAD}</a></div></li>'
            )
        else:
            out.append(
                f'<li class="sp-dir"><div><span class="sp-name">{htmllib.escape(name)}</span></div>'
                f'{_render_tree(child, prefix + name + "/")}</li>'
            )
    out.append("</ul>")
    return "".join(out)


def _files_markup(manifest: dict[str, Any], ref: str) -> str:
    run = run_by_id(manifest, ref)
    if run is not None:
        root = run.get("root") or ""
        entries = run.get("files") or []
        zip_name = htmllib.escape(root.rstrip("/") + ".zip", quote=True)
        total = sum(int(e.get("size") or 0) for e in entries)
        head = (
            f'<div class="sp-files-top"><span class="sp-meta sp-num">{len(entries)} files · {_human_size(total)}</span>'
            f'<a class="sp-getall" href="{zip_name}" download>{_ICON_ARCHIVE}<span>Download all</span></a></div>'
        )
        return head + _render_tree(_tree(entries, root), root)

    sections = [{"path": m["path"], "size": m.get("size", 0)} for m in manifest.get("members") or []]
    for run in manifest.get("runs") or []:
        sections.extend(run.get("files") or [])
    for extra in manifest.get("extras") or []:
        sections.append({"path": extra["path"], "size": extra.get("size", 0)})
    total = sum(int(e.get("size") or 0) for e in sections)
    head = (
        f'<div class="sp-files-top"><span class="sp-meta sp-num">{len(sections)} files · {_human_size(total)}</span></div>'
    )
    return head + _render_tree(_tree(sections, ""), "")


def _resolve_path(manifest: dict[str, Any], ref: str) -> Optional[str]:
    resolved = resolve_ref(manifest, ref)
    if resolved is None or resolved["kind"] == "run":
        return None
    return resolved["path"]


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
        return f"<stimma-media{_attr_str(attrs)}>{_media_markup(path, alt=alt, caption=attrs.get('caption', ''))}</stimma-media>"

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

    flags = re.IGNORECASE | re.DOTALL
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-media"), media_sub, body, flags=flags)
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-files"), files_sub, body, flags=flags)
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-compare"), compare_sub, body, flags=flags)
    body = re.sub(r"<stimma-grid\b(?P<attrs>[^>]*)>", grid_sub, body, flags=flags)
    for tag in RESERVED_ELEMENTS:
        for m in re.finditer(rf"<{tag}\b(?P<attrs>[^>]*)>", body, flags=flags):
            attrs = _parse_attrs(m.group("attrs"))
            if attrs.get("id"):
                if attrs["id"] in seen_ids:
                    problems.append(f"duplicate id {attrs['id']!r} on <{tag}>")
                seen_ids.add(attrs["id"])
    return body, problems


# Lint -----------------------------------------------------------------------

_EXTERNAL_RE = re.compile(r"""(?:src|href)\s*=\s*["']\s*(?:https?:)?//""", re.IGNORECASE)
_CSS_EXTERNAL_RE = re.compile(r"""url\(\s*["']?\s*(?:https?:)?//""", re.IGNORECASE)
_IMPORT_RE = re.compile(r"""@import\s+(?:url\()?["']?\s*(?:https?:)?//""", re.IGNORECASE)
_MODULE_RE = re.compile(r"""<script\b[^>]*type\s*=\s*["']module["']""", re.IGNORECASE)


def lint_cover_source(body: str) -> list[str]:
    """Problems in authored HTML that break portability."""
    problems: list[str] = []
    if _EXTERNAL_RE.search(body) or _CSS_EXTERNAL_RE.search(body) or _IMPORT_RE.search(body):
        problems.append(
            "the cover references an external URL (http(s):// or //). Covers must be self-contained: "
            "bundle fonts and images into the package, or reference members by ref"
        )
    if _MODULE_RE.search(body):
        problems.append('<script type="module"> does not run from a double-clicked file; use a classic script')
    return problems


# Document assembly ----------------------------------------------------------

def _extract_parts(html_text: str) -> tuple[str, str, str]:
    """Split authored HTML into (head_extra, body, title)."""
    from flow_runtime.layout_bundle import extract_document_parts

    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    if m:
        title = htmllib.unescape(m.group(1).strip())
    body, css = extract_document_parts(html_text)
    head_extra = f"<style>{css}</style>" if css else ""
    # Preserve authored <head> scripts (classic) so an author can put the kit-using code up top.
    head_match = re.search(r"<head[^>]*>(.*?)</head>", html_text, re.IGNORECASE | re.DOTALL)
    if head_match:
        scripts = re.findall(r"<script\b[^>]*>.*?</script>", head_match.group(1), re.IGNORECASE | re.DOTALL)
        head_extra += "".join(scripts)
    return head_extra, body, title


def _total_size(manifest: dict[str, Any]) -> int:
    """Bytes of what the recipient receives. Inputs are not part of the count."""
    total = 0
    for run in manifest.get("runs") or []:
        total += sum(int(e.get("size") or 0) for e in run.get("files") or [])
    total += sum(int(e.get("size") or 0) for e in manifest.get("extras") or [])
    return total


def _total_files(manifest: dict[str, Any]) -> int:
    produced = sum(len(run.get("files") or []) for run in manifest.get("runs") or [])
    produced += len(manifest.get("extras") or [])
    # A package with nothing but inputs is still a package of those files.
    return produced or len(manifest.get("members") or [])


def _run_presentation(run: dict[str, Any], manifest: dict[str, Any]) -> Optional[str]:
    """Ask the recipe that produced this run to present it, if it can."""
    from packages.recipes import get_recipe

    recipe_id = (run.get("recipe") or {}).get("id")
    if not recipe_id:
        return None
    try:
        spec = get_recipe(recipe_id)
    except Exception:  # noqa: BLE001
        return None
    if spec is None or spec.present is None:
        return None
    try:
        fragment = spec.present(run, manifest)
    except Exception:  # noqa: BLE001
        return None
    return fragment or None


def auto_cover_body(manifest: dict[str, Any]) -> str:
    """The cover a package gets when nobody designed one.

    It leads with the work, says what is inside in the words someone receiving
    it would use, and keeps the file list quiet and last. Nothing structural
    about how the package was assembled belongs on this page.
    """
    title = htmllib.escape(manifest.get("title") or "Package")
    parts = [f'<div class="sp-page"><h1 class="sp-title">{title}</h1>']

    runs = manifest.get("runs") or []
    labels = [
        (run.get("recipe") or {}).get("display_name") or (run.get("recipe") or {}).get("id") or ""
        for run in runs
    ]
    labels = [label for label in labels if label]
    summary = " · ".join(filter(None, [
        ", ".join(labels),
        f"{_total_files(manifest)} files",
        _human_size(_total_size(manifest)),
    ]))
    if summary:
        parts.append(f'<p class="sp-sub">{htmllib.escape(summary)}</p>')

    presented = False
    for run in runs:
        fragment = _run_presentation(run, manifest)
        if fragment:
            parts.append(f'<div class="sp-section">{fragment}</div>')
            presented = True

    if not presented:
        members = manifest.get("members") or []
        if members:
            parts.append('<div class="sp-section"><stimma-grid>')
            for member in members:
                ref = htmllib.escape(member["id"], quote=True)
                parts.append(f'<stimma-media ref="{ref}" plate></stimma-media>')
            parts.append("</stimma-grid></div>")

    extras = manifest.get("extras") or []
    if extras:
        parts.append('<div class="sp-section"><p class="sp-label">Also included</p><stimma-files></stimma-files></div>')
    else:
        for run in runs:
            ref = htmllib.escape(run["id"], quote=True)
            parts.append(
                f'<div class="sp-section"><p class="sp-label">Files</p>'
                f'<stimma-files ref="{ref}"></stimma-files></div>'
            )

    parts.append('<p class="sp-footer">Made with Stimma.</p></div>')
    return "".join(parts)


def render_cover_document(
    manifest: dict[str, Any],
    *,
    authored_html: Optional[str] = None,
    strict: bool = True,
) -> tuple[str, list[str]]:
    """Build the final ``index.html`` text. Returns (html, problems).

    With ``strict``, unresolved refs and portability problems are errors the
    caller should refuse; otherwise they are returned as warnings and the
    page still renders (the auto cover never has problems).
    """
    problems: list[str] = []
    if authored_html:
        head_extra, body, title = _extract_parts(authored_html)
        problems.extend(lint_cover_source(authored_html))
    else:
        head_extra, body, title = "", auto_cover_body(manifest), ""
    body, expand_problems = expand_kit_elements(manifest, body)
    problems.extend(expand_problems)
    if strict and problems:
        return "", problems
    title = title or manifest.get("title") or "Package"
    manifest_json = json.dumps(_public_manifest(manifest), separators=(",", ":")).replace("</", "<\\/")
    html_text = (
        "<!DOCTYPE html>\n"
        '<html lang="en" data-stimma-package="1">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{htmllib.escape(title)}</title>\n"
        f'<meta name="generator" content="stimma-package kit {KIT_VERSION}">\n'
        f"<style>{KIT_CSS}</style>\n"
        f'<script type="application/json" id="stimma-package-manifest">{manifest_json}</script>\n'
        f"<script>{KIT_JS.replace('%(kit_version)d', str(KIT_VERSION))}</script>\n"
        f"{head_extra}\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )
    return html_text, problems


def _public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """The manifest as the page sees it: no local media ids."""
    out = json.loads(json.dumps(manifest))
    for member in out.get("members") or []:
        member.pop("media_id", None)
    return out


# Single-file inlining -------------------------------------------------------

_SRC_RE = re.compile(r"""(?P<attr>\b(?:src|href|poster))\s*=\s*(?P<q>["'])(?P<ref>[^"']+)(?P=q)""", re.IGNORECASE)
_CSS_URL_RE = re.compile(r"""url\(\s*(?P<q>["']?)(?P<ref>[^"')\s]+)(?P=q)\s*\)""", re.IGNORECASE)


def _preview_bytes(path: Path, max_side: int) -> tuple[bytes, str]:
    """Bytes + mime for inlining. Rasters get downscaled to ``max_side``."""
    ext = path.suffix.lower()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
        try:
            from PIL import Image

            with Image.open(path) as img:
                img.load()
                if max(img.size) > max_side:
                    img.thumbnail((max_side, max_side), Image.LANCZOS)
                    buf = io.BytesIO()
                    if img.mode in ("RGBA", "LA", "P"):
                        img.convert("RGBA").save(buf, format="PNG", optimize=True)
                        return buf.getvalue(), "image/png"
                    img.convert("RGB").save(buf, format="JPEG", quality=88, optimize=True)
                    return buf.getvalue(), "image/jpeg"
        except Exception:  # noqa: BLE001
            pass
    return path.read_bytes(), mime


def inline_cover_assets(bundle_dir: Path, html_text: str, *, max_side: int = PREVIEW_MAX_SIDE) -> str:
    """Rewrite relative image/video refs to data URLs. Non-media links are dropped to plain text.

    This is what the single-file export and the thumbnail renderer consume.
    Video is not inlined (size); a ``<video>`` becomes a note.
    """
    bundle_dir = Path(bundle_dir)
    cache: dict[str, str] = {}

    def data_url(ref: str) -> Optional[str]:
        if ref.startswith(("data:", "http:", "https:", "//", "#", "mailto:", "javascript:")):
            return None
        rel = ref.split("?", 1)[0].split("#", 1)[0]
        if rel in cache:
            return cache[rel]
        target = (bundle_dir / rel)
        try:
            target.resolve().relative_to(bundle_dir.resolve())
        except ValueError:
            return None
        if not target.is_file():
            return None
        ext = target.suffix.lower()
        if ext in VIDEO_EXTS:
            return None
        data, mime = _preview_bytes(target, max_side)
        url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        cache[rel] = url
        return url

    def src_sub(m: re.Match) -> str:
        attr, q, ref = m.group("attr"), m.group("q"), m.group("ref")
        url = data_url(ref)
        if url is None:
            if attr.lower() == "href" and not ref.startswith(("#", "data:", "http", "//", "mailto:")):
                return f'data-href={q}{ref}{q}'  # download link to a file that is not here
            return m.group(0)
        if attr.lower() == "href" and not Path(ref).suffix.lower() in IMAGE_EXTS:
            return f'data-href={q}{ref}{q}'
        return f"{attr}={q}{url}{q}"

    def css_sub(m: re.Match) -> str:
        url = data_url(m.group("ref"))
        return m.group(0) if url is None else f'url("{url}")'

    out = _SRC_RE.sub(src_sub, html_text)
    out = _CSS_URL_RE.sub(css_sub, out)
    out = re.sub(r"<video\b[^>]*>.*?</video>", '<div class="sp-caption">Video is in the full package.</div>', out, flags=re.IGNORECASE | re.DOTALL)
    out = out.replace('<html lang="en" data-stimma-package="1">', '<html lang="en" data-stimma-package="1" data-stimma-single-file="1">', 1)
    return out


def cover_path(bundle_dir: Path) -> Path:
    return Path(bundle_dir) / COVER_NAME
