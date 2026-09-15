"""A static, paginated copy of the authored cover, using the existing PDF engine."""
from pathlib import Path
from copy import deepcopy

from packages.export import export_single_html

PRINT_CSS = """
@page { size: 1280px 720px; margin: 48px 48px 64px; background: var(--sp-bg, #0d0d0e);
  @bottom-left { content: element(stimma-footer); width: 100%; vertical-align: top; text-align: left; padding-top: 12px; }
}
.sp-page { width: 100%; max-width: none; margin: 0; padding: 0; }
body>stimma-section { max-width: none; padding-left: 0; padding-right: 0; }
body>stimma-section:first-of-type { margin-top: 0; }
.sp-title { font-size: 42px; }
stimma-section, .sp-section { margin-top: 28px; }
h1, h2, h3, .sp-label { break-after: avoid; }
stimma-media, stimma-compare figure { break-inside: avoid; }
stimma-media img, stimma-compare img { max-width: 100%; max-height: 480px; object-fit: contain; }
stimma-grid { grid-template-columns: repeat(3, 1fr); gap: 18px; }
stimma-grid[columns="2"] { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 32px; }
stimma-columns { grid-template-columns: repeat(3, 1fr); gap: 18px; break-inside: avoid; }
stimma-sizes { flex-wrap: wrap; break-inside: avoid; }
.sp-appearance-head .sp-seg, input, button { display: none !important; }
.sp-appearance-body { display: block; }
.sp-appearance-panel { display: block !important; opacity: 1 !important;
  visibility: visible !important; margin-top: 18px; break-inside: avoid; }
.sp-appearance-panel::before { break-after: avoid; content: attr(data-when); display: block;
  text-transform: capitalize; font-size: 12px; margin-bottom: 12px; }
stimma-compare.sp-slider .sp-cmp { display: grid; grid-template-columns: 1fr 1fr; }
stimma-compare.sp-slider figure:first-child { position: static; width: auto; overflow: visible; }
stimma-compare.sp-slider figure:first-child img { width: 100%; max-width: 100%; }
stimma-files .sp-files { display: none; }
.sp-footer { position: running(stimma-footer); width: 100%; margin: 0; padding-top: 10px; }
.sp-footer .sp-brand { display: block; white-space: nowrap; }
.sp-footer .sp-wordmark { margin-left: 3px; }
stimma-section[page] { break-before: page; margin-top: 0; }
stimma-section[page]:first-child { break-before: auto; }
stimma-section[page]>.sp-label, stimma-section[layout]>.sp-label { font-size: 24px; margin-bottom: 28px; }
stimma-section[layout]>.sp-section-body { display: grid; gap: 32px; align-items: center; }
stimma-section[layout=pair]>.sp-section-body { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
stimma-section[layout]>.sp-section-body>* { min-width: 0; }
stimma-section[layout=single]>.sp-section-body, stimma-section[layout=stack]>.sp-section-body { grid-template-columns: 1fr; }
stimma-section[layout]>.sp-section-body>stimma-media img { width: 100%; height: 480px; object-fit: contain; }
stimma-section[layout=stack]>.sp-section-body { gap: 20px; }
stimma-section[layout=stack] .sp-caption, stimma-section[layout=single] .sp-caption { text-align: center; }
stimma-section[layout=stack]>.sp-section-body>stimma-media img { height: 230px; }
stimma-section[page]:has(.sp-section-details)>.sp-section-body>stimma-media img { height: 325px; }
stimma-section[page] .sp-section-details { margin-top: 20px; }
stimma-section[page] .sp-section-details>stimma-grid { grid-template-columns: 1fr 1fr; gap: 32px; }
stimma-section[page] .sp-section-details stimma-media img { width: 100%; height: 110px; object-fit: contain; }
stimma-section[page] .sp-section-details .sp-caption { text-align: center; }
/* A short authored note is a full-width row, with space reserved below scenes. */
stimma-section[layout]>.sp-section-body>.sp-note { grid-column: 1; margin: 0; }
stimma-section[layout=pair]>.sp-section-body>.sp-note { grid-column: 1 / span 2; }
stimma-section[layout]:has(.sp-note)>.sp-section-body>stimma-media img { height: 420px; }
stimma-section[layout=stack]:has(.sp-note)>.sp-section-body>stimma-media img { height: 190px; }
stimma-section[page] .sp-appearance-panel { margin-top: 0; }
stimma-section[page] .sp-appearance-head, stimma-section[page] .sp-appearance-panel::before { display: none; }

"""


def export_pdf(bundle_dir: Path, *, validate_pages: bool = False) -> bytes:
    """Render embedded assets only: no network or ambient filesystem access."""
    from weasyprint import HTML, default_url_fetcher

    def embedded_only(url, **kwargs):
        if not url.startswith('data:'):
            raise ValueError('PDF cover resources must be embedded')
        return default_url_fetcher(url, **kwargs)

    # Kit print defaults follow kit screen CSS, but precede authored styles.
    # Authors can override typography, page colors and composition normally.
    html = export_single_html(bundle_dir).replace(
        '</style>', f'</style><style>{PRINT_CSS}</style>', 1,
    )
    document = HTML(string=html, url_fetcher=embedded_only)
    # Supplemental HTML disclosures stay out of the deck, including their
    # appearance variants. Remove them before splitting page-level variants.
    for parent in list(document.etree_element.iter()):
        for node in list(parent):
            if 'sp-section-disclosure' in node.get('class', '').split():
                parent.remove(node)
    # File browsers are HTML-only controls. Their otherwise empty section
    # should not create a PDF page containing only a heading and footer.
    for parent in list(document.etree_element.iter()):
        for section in list(parent):
            if section.tag != 'stimma-section':
                continue
            content = section.find("./div[@class='sp-section-body']")
            if content is None or (content.text or '').strip() or not len(content):
                continue
            children = list(content)
            if all(child.tag == 'stimma-files' and not (child.tail or '').strip()
                   and len(child) == 1 and 'sp-files' in child[0].get('class', '').split()
                   for child in children):
                parent.remove(section)
    # Running elements must be encountered before page one is laid out.
    body = document.etree_element.find('body')
    if body is not None:
        for parent in document.etree_element.iter():
            for node in list(parent):
                if 'sp-footer' in node.get('class', '').split():
                    parent.remove(node)
                    body.insert(0, node)
                    break
    # An appearance switch is one responsive HTML section, but each of its
    # variants gets its own PDF page. Work on the print tree, never the cover.
    for parent in list(document.etree_element.iter()):
        for section in list(parent):
            if section.tag != 'stimma-section' or 'page' not in section.attrib:
                continue
            panels = [node for node in section.iter() if 'sp-appearance-panel' in node.get('class', '').split()]
            if len(panels) < 2:
                continue
            index = list(parent).index(section)
            for offset, panel in enumerate(panels):
                clone = deepcopy(section)
                mode = panel.get('data-when', '')
                for node in clone.iter():
                    if offset:
                        node.attrib.pop('id', None)
                    for child in list(node):
                        if 'sp-appearance-panel' in child.get('class', '').split() and child.get('data-when') != mode:
                            node.remove(child)
                heading = clone.find("./p[@class='sp-label']")
                if heading is not None:
                    heading.text = f"{heading.text} · {mode.title()}"
                parent.insert(index + offset, clone)
            parent.remove(section)
    # Keep type/vector artwork sharp and raster scenes at print resolution;
    # the ZIP still contains the original full-resolution preview images.
    try:
        rendered = document.render(presentational_hints=True)
        if validate_pages:
            _validate_page_groups(rendered)
        return rendered.write_pdf(dpi=300)
    except TypeError as exc:
        if "'FunctionBlock' object is not subscriptable" not in str(exc):
            raise
        raise ValueError(
            "The PDF renderer could not compute a CSS grid track. For custom "
            "grids, add explicit @media print grid-template-columns (for example "
            "1fr 1fr), without nested min()/max()/clamp() in minmax(). Keep the "
            "responsive screen columns separately, then preview the PDF again."
        ) from exc


def _validate_page_groups(document) -> None:
    """Diagnose overflow of explicitly authored page groups in draft previews.

    Appearance variants have already become separate elements. Ordinary flowing
    sections remain free to span pages, and existing saved exports are unchanged.
    """
    groups = {}
    for number, page in enumerate(document.pages, 1):
        for box in page._page_box.descendants():
            element = box.element
            if element is None or element.tag != "stimma-section" or "page" not in element.attrib:
                continue
            label = element.find("./p[@class='sp-label']")
            title = "".join(label.itertext()) if label is not None else element.get("id", "Untitled section")
            group = groups.setdefault(id(element), {"title": title, "pages": set()})
            group["pages"].add(number)
    overflow = [f"{group['title']!r} (pages {', '.join(map(str, sorted(group['pages'])))})"
                for group in groups.values() if len(group["pages"]) > 1]
    if overflow:
        raise ValueError(
            "PDF page groups overflow: " + "; ".join(overflow) + ". "
            "Rebalance the named section's content or split it into labeled sections; "
            "keep type readable. Omit the page attribute only for intentionally flowing content. "
            "Then preview again."
        )
