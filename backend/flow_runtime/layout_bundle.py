"""Shared helpers for building ``.stimmalayout`` bundles.

Both the agent-level ``create_layout`` tool and the flow-level
``create_layout`` DSL primitive build the same on-disk bundle shape:

    {name}.stimmalayout/
        index.html   # self-contained; data-stimma-width / data-stimma-height
        *.png, *.jpg, *.gif, *.webp, *.bmp, *.svg   # referenced assets, flat

The renderer at ``routes.media_files._generate_layout_preview`` reads the
``data-stimma-width`` / ``data-stimma-height`` data attributes off the root
``<html>`` tag and expects all image refs to be bundle-relative. If either
caller drifts from this shape, rasterization silently falls back to
content-measure and may produce wrong dimensions — so all bundle wrapping,
ref extraction, ref linting, and ref-copying lives here.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path


IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'}

# Reference patterns — local file refs we want to validate and copy:
#   src="file.png"  src='file.png'       (HTML attributes)
#   url("file.png") url('file.png') url(file.png)  (CSS background-image etc.)
# The tempered-dot ``(?:(?!quote).)*`` is deliberate: an earlier version
# excluded *both* quote chars from the attribute value, which meant a
# pathological ref like ``src="['x.png']"`` (e.g. Python stringified a list)
# didn't match at all — so the linter silently passed and a broken bundle
# shipped. Allowing the opposite-quote character inside the value lets the
# linter catch those cases.
SRC_ATTR_RE = re.compile(
    r'(src)\s*=\s*(?P<quote>["\'])(?P<ref>(?:(?!(?P=quote)).)*)(?P=quote)',
    re.IGNORECASE,
)
CSS_URL_RE = re.compile(
    r'(url)\(\s*(?:(?P<quote>["\'])(?P<ref>(?:(?!(?P=quote)).)*)(?P=quote)|(?P<ref_bare>[^"\')\s]+))\s*\)',
)


def extract_document_parts(html: str) -> tuple[str, str]:
    """If ``html`` is a full document, extract body content and ``<style>`` blocks.

    Returns ``(body_content, css_text)``. When ``html`` is just a fragment,
    returns ``(html, "")``.
    """
    stripped = html.strip()
    if not (stripped.lower().startswith('<!doctype') or stripped.lower().startswith('<html')):
        return html, ""

    styles: list[str] = []
    for m in re.finditer(r'<style[^>]*>(.*?)</style>', stripped, re.DOTALL | re.IGNORECASE):
        styles.append(m.group(1))

    body_match = re.search(r'<body[^>]*>(.*)</body>', stripped, re.DOTALL | re.IGNORECASE)
    if body_match:
        body = body_match.group(1).strip()
    else:
        body = re.sub(r'<!doctype[^>]*>', '', stripped, flags=re.IGNORECASE)
        body = re.sub(r'</?html[^>]*>', '', body, flags=re.IGNORECASE)
        body = re.sub(r'<head>.*?</head>', '', body, flags=re.DOTALL | re.IGNORECASE)
        body = body.strip()

    return body, "\n".join(styles)


def _ref_from_match(match: re.Match) -> str:
    groups = match.groupdict()
    return groups.get("ref") or groups.get("ref_bare") or ""


def extract_all_refs(html: str) -> list[str]:
    """Extract all local file refs from HTML ``src`` attrs and CSS ``url()``."""
    refs: list[str] = []
    for pattern in (SRC_ATTR_RE, CSS_URL_RE):
        for match in pattern.finditer(html):
            ref = _ref_from_match(match)
            # '#...' is an in-document fragment reference (SVG gradients,
            # filters, clip paths — fill="url(#grad)"), not a file.
            if ref and not ref.startswith(('data:', 'http://', 'https://', '/', '#')):
                refs.append(ref)
    return refs


def lint_image_refs(html: str, workspace_path: Path) -> list[str]:
    """Return list of referenced files that are missing or not images."""
    missing: list[str] = []
    for ref in extract_all_refs(html):
        source = workspace_path / ref
        if not source.exists():
            missing.append(ref)
        elif source.suffix.lower() not in IMAGE_EXTENSIONS:
            missing.append(f"{ref} (not an image file)")
    return missing


def copy_referenced_images(html: str, workspace_path: Path, bundle_path: Path) -> str:
    """Copy referenced images into the bundle and rewrite refs to bundle-relative names.

    Refs that are data URIs, http(s), or absolute paths are left unchanged.
    """

    def _copy_and_rewrite(src_value: str) -> str | None:
        if src_value.startswith(('data:', 'http://', 'https://', '/', '#')):
            return None
        source = workspace_path / src_value
        if not source.exists() or source.suffix.lower() not in IMAGE_EXTENSIONS:
            return None
        dest_name = source.name
        dest = bundle_path / dest_name
        if not dest.exists():
            shutil.copy2(source, dest)
        return dest_name

    def replace_src(match):
        attr = match.group(1)
        quote = match.group("quote") or '"'
        src_value = _ref_from_match(match)
        dest_name = _copy_and_rewrite(src_value)
        if dest_name is None:
            return match.group(0)
        return f'{attr}={quote}{dest_name}{quote}'

    def replace_url(match):
        keyword = match.group(1)
        quote = match.group("quote") or ''
        src_value = _ref_from_match(match)
        dest_name = _copy_and_rewrite(src_value)
        if dest_name is None:
            return match.group(0)
        return f'{keyword}({quote}{dest_name}{quote})'

    html = SRC_ATTR_RE.sub(replace_src, html)
    html = CSS_URL_RE.sub(replace_url, html)
    return html


def assemble_index_html(
    html: str,
    *,
    width: int,
    height: int | None,
    extra_css: str = "",
) -> str:
    """Wrap user HTML into a self-contained ``index.html`` document.

    - Extracts body content and inline ``<style>`` blocks from full-document input.
    - Merges extracted styles + ``extra_css`` + a fixed-canvas CSS reset.
    - Emits ``data-stimma-width`` and ``data-stimma-height`` on ``<html>`` so the
      rasterizer picks up canvas dimensions. ``height=None`` emits ``"auto"`` for
      content-measured rendering.
    """
    body_content, extracted_styles = extract_document_parts(html)

    all_css = ""
    if extracted_styles:
        all_css += extracted_styles + "\n"
    if extra_css:
        all_css += extra_css + "\n"
    all_css += "\n".join([
        "html, body { margin: 0 !important; padding: 0 !important;",
        "  width: 100% !important; height: 100% !important;",
        "  overflow: hidden !important; }",
    ])

    style_block = f"<style>{all_css}</style>"
    height_attr = "auto" if height is None else str(height)
    return (
        f'<!DOCTYPE html>\n'
        f'<html data-stimma-width="{width}" data-stimma-height="{height_attr}">\n'
        f'<head><meta charset="utf-8">{style_block}</head>\n'
        f'<body>{body_content}</body>\n'
        f'</html>'
    )
