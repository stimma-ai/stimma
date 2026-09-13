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
:root{--sp-bg:#0f0f10;--sp-fg:#ececec;--sp-muted:#9a9a9a;--sp-line:#2a2a2b;--sp-card:#171718;--sp-accent:#2dd4bf}
@media (prefers-color-scheme: light){:root{--sp-bg:#faf9f7;--sp-fg:#1a1a1a;--sp-muted:#6b6b6b;--sp-line:#e4e1dc;--sp-card:#ffffff}}
html,body{margin:0;padding:0;background:var(--sp-bg);color:var(--sp-fg);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
*{box-sizing:border-box}
a{color:inherit}
.sp-page{max-width:1200px;margin:0 auto;padding:48px 24px 96px}
.sp-title{font-size:clamp(32px,6vw,64px);line-height:1;letter-spacing:-0.02em;margin:0 0 8px;font-weight:700}
.sp-sub{color:var(--sp-muted);margin:0 0 40px}
.sp-h2{font-size:14px;letter-spacing:.12em;text-transform:uppercase;color:var(--sp-muted);margin:48px 0 16px;font-weight:600}
.sp-card{background:var(--sp-card);border:1px solid var(--sp-line);border-radius:8px;overflow:hidden}
stimma-media{display:block}
stimma-media img,stimma-media video{display:block;max-width:100%;height:auto;background:
  linear-gradient(45deg,#8883 25%,transparent 25%,transparent 75%,#8883 75%),linear-gradient(45deg,#8883 25%,transparent 25%,transparent 75%,#8883 75%);
  background-size:16px 16px;background-position:0 0,8px 8px}
stimma-media[real-size] img{max-width:none;width:auto;height:auto}
stimma-media .sp-caption{font-size:13px;color:var(--sp-muted);padding:8px 0 0}
stimma-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--sp-cell,220px),1fr));gap:16px}
stimma-grid stimma-media{background:var(--sp-card);border:1px solid var(--sp-line);border-radius:6px;padding:12px}
stimma-grid stimma-media img{margin:0 auto}
stimma-files{display:block}
stimma-files .sp-files-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-bottom:1px solid var(--sp-line);font-weight:600}
stimma-files .sp-files-head a{font-size:13px;font-weight:500;color:var(--sp-accent);text-decoration:none}
stimma-files ul{list-style:none;margin:0;padding:0}
stimma-files li{padding:0}
stimma-files li>div{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 16px;border-bottom:1px solid var(--sp-line);font-size:14px}
stimma-files li:last-child>div{border-bottom:0}
stimma-files li.sp-dir>ul{padding-left:16px;border-left:1px solid var(--sp-line);margin-left:16px}
stimma-files li.sp-dir>div{cursor:pointer;user-select:none}
stimma-files li.sp-dir.sp-collapsed>ul{display:none}
stimma-files .sp-meta{color:var(--sp-muted);font-size:12px;font-variant-numeric:tabular-nums}
stimma-files a.sp-dl{color:var(--sp-accent);text-decoration:none;font-size:12px}
stimma-compare{display:block;position:relative;overflow:hidden;border-radius:6px;background:var(--sp-card);border:1px solid var(--sp-line)}
stimma-compare .sp-cmp{display:grid;grid-template-columns:1fr 1fr;gap:2px}
stimma-compare .sp-cmp figure{margin:0}
stimma-compare .sp-cmp img{display:block;width:100%;height:auto}
stimma-compare .sp-cmp figcaption{font-size:12px;color:var(--sp-muted);padding:6px 8px}
stimma-compare.sp-slider .sp-cmp{display:block;position:relative}
stimma-compare.sp-slider .sp-cmp figure:first-child{position:absolute;inset:0;overflow:hidden;width:var(--sp-split,50%)}
stimma-compare.sp-slider .sp-cmp figure:first-child img{width:var(--sp-w,100%);max-width:none}
stimma-compare.sp-slider input[type=range]{position:absolute;left:0;right:0;bottom:8px;width:100%;margin:0;opacity:.85}
stimma-compare.sp-slider figcaption{position:absolute;top:8px;background:#0008;color:#fff;border-radius:4px}
stimma-compare.sp-slider figure:first-child figcaption{left:8px}
stimma-compare.sp-slider figure:last-child figcaption{right:8px}
.sp-members{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}
.sp-footer{margin-top:64px;color:var(--sp-muted);font-size:12px}
stimma-pick,stimma-approve,stimma-comments{display:block}
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
                f'<li><div><span>{htmllib.escape(name)}</span>'
                f'<span class="sp-meta">{_human_size(int(entry.get("size") or 0))} '
                f'<a class="sp-dl" href="{href}" download>Download</a></span></div></li>'
            )
        else:
            out.append(f'<li class="sp-dir"><div><span>{htmllib.escape(name)}/</span></div>{_render_tree(child, prefix + name + "/")}</li>')
    out.append("</ul>")
    return "".join(out)


def _files_markup(manifest: dict[str, Any], ref: str) -> str:
    run = run_by_id(manifest, ref)
    if run is not None:
        root = run.get("root") or ""
        entries = run.get("files") or []
        label = root.rstrip("/") or run["id"]
        zip_name = root.rstrip("/") + ".zip"
        head = (
            f'<div class="sp-files-head"><span>{htmllib.escape(label)}/</span>'
            f'<a href="{htmllib.escape(zip_name, quote=True)}" download>Download folder as zip</a></div>'
        )
        return f'<div class="sp-card">{head}{_render_tree(_tree(entries, root), root)}</div>'
    # whole package: members, runs, extras
    sections = []
    for member in manifest.get("members") or []:
        sections.append({"path": member["path"], "size": member.get("size", 0)})
    for run in manifest.get("runs") or []:
        sections.extend(run.get("files") or [])
    for extra in manifest.get("extras") or []:
        sections.append({"path": extra["path"], "size": extra.get("size", 0)})
    head = '<div class="sp-files-head"><span>All files</span></div>'
    return f'<div class="sp-card">{head}{_render_tree(_tree(sections, ""), "")}</div>'


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


def auto_cover_body(manifest: dict[str, Any]) -> str:
    """A plain, competent cover for packages built without an author."""
    parts = [f'<div class="sp-page"><h1 class="sp-title">{htmllib.escape(manifest.get("title") or "Package")}</h1>']
    members = manifest.get("members") or []
    runs = manifest.get("runs") or []
    subtitle = []
    if members:
        subtitle.append(f"{len(members)} member{'s' if len(members) != 1 else ''}")
    if runs:
        subtitle.append(f"{len(runs)} recipe run{'s' if len(runs) != 1 else ''}")
    parts.append(f'<p class="sp-sub">{" · ".join(subtitle) or "Empty package"}</p>')
    if members:
        parts.append('<h2 class="sp-h2">Members</h2><stimma-grid>')
        for member in members:
            role = f' caption="{htmllib.escape(member.get("role") or "", quote=True)}"' if member.get("role") else ""
            parts.append(f'<stimma-media ref="{htmllib.escape(member["id"], quote=True)}"{role}></stimma-media>')
        parts.append("</stimma-grid>")
    for run in runs:
        label = run.get("recipe", {}).get("display_name") or run.get("recipe", {}).get("id") or run["id"]
        parts.append(f'<h2 class="sp-h2">{htmllib.escape(label)}</h2><stimma-files ref="{htmllib.escape(run["id"], quote=True)}"></stimma-files>')
    extras = manifest.get("extras") or []
    if extras:
        parts.append('<h2 class="sp-h2">Also included</h2><div class="sp-card"><ul>')
        for extra in extras:
            href = htmllib.escape(extra["path"], quote=True)
            parts.append(f'<li><div><span>{htmllib.escape(extra.get("name") or Path(extra["path"]).name)}</span><a class="sp-dl" href="{href}" download>Download</a></div></li>')
        parts.append("</ul></div>")
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
