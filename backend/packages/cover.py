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

from packages.kit import (
    IMAGE_EXTS,
    KIT_CSS,
    KIT_JS,
    KIT_VERSION,
    VIDEO_EXTS,
    escape,
    expand_kit_elements,
    files,
    footer,
    grid,
    human_size,
    media,
    section,
)
from packages.manifest import COVER_NAME

KIT_ELEMENTS = ("stimma-media", "stimma-files", "stimma-compare", "stimma-grid")
RESERVED_ELEMENTS = ("stimma-pick", "stimma-approve", "stimma-comments")
PREVIEW_MAX_SIDE = 1600


class CoverError(ValueError):
    pass


# Kit assets ----------------------------------------------------------------

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

    Components only: the same vocabulary an authored cover uses, so a package
    made without a designer still reads as part of the same family.
    """
    parts = [f'<h1 class="sp-title">{escape(manifest.get("title") or "Package")}</h1>']

    runs = manifest.get("runs") or []
    labels = [
        (run.get("recipe") or {}).get("display_name") or (run.get("recipe") or {}).get("id") or ""
        for run in runs
    ]
    summary = " · ".join(x for x in [
        ", ".join(label for label in labels if label),
        f"{_total_files(manifest)} files",
        human_size(_total_size(manifest)),
    ] if x)
    if summary:
        parts.append(f'<p class="sp-sub">{escape(summary)}</p>')

    presented = False
    for run in runs:
        fragment = _run_presentation(run, manifest)
        if fragment:
            parts.append(fragment)
            presented = True

    if not presented:
        members = manifest.get("members") or []
        if members:
            parts.append(section(grid(media(m["id"], plate=True) for m in members)))

    if manifest.get("extras"):
        parts.append(section(files(), label="Files"))
    else:
        for run in runs:
            parts.append(section(files(run["id"]), label="Files"))

    parts.append(footer())
    return f'<div class="sp-page">{"".join(parts)}</div>'


def render_cover_document(
    manifest: dict[str, Any],
    *,
    authored_html: Optional[str] = None,
    strict: bool = True,
    bundle_dir: Optional[Path] = None,
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
    body, expand_problems = expand_kit_elements(manifest, body, bundle_dir)
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
