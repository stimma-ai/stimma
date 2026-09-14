"""A static, paginated copy of the authored cover, using the existing PDF engine."""
from pathlib import Path

from packages.export import export_single_html

PRINT_CSS = """
@page { size: A4; margin: 16mm; background: #0d0d0e; }
html, body { font-family: sans-serif; }
.sp-page { width: 100%; max-width: none; margin: 0; padding: 0; }
.sp-title { font-size: 32px; }
stimma-section, .sp-section { margin-top: 28px; }
h1, h2, h3, .sp-label { break-after: avoid; }
stimma-media, stimma-compare figure { break-inside: avoid; }
stimma-media img, stimma-compare img { max-width: 100%; max-height: 220mm; object-fit: contain; }
stimma-grid { grid-template-columns: repeat(3, 1fr) !important; gap: 18px; }
stimma-grid:has(stimma-media[size]) { grid-template-columns: repeat(5, 1fr) !important; }
stimma-columns { grid-template-columns: repeat(3, 1fr); gap: 18px; break-inside: avoid; }
stimma-sizes { flex-wrap: wrap; break-inside: avoid; }
.sp-appearance-head .sp-seg, input, button { display: none !important; }
.sp-appearance-body { display: block; }
.sp-appearance-panel { display: block !important; opacity: 1 !important;
  visibility: visible !important; margin-top: 18px; break-inside: avoid; }
.sp-appearance-panel::before { break-after: avoid; content: attr(data-when); display: block;
  text-transform: capitalize; font-size: 12px; margin-bottom: 12px; }
.sp-appearance-panel > div:has(stimma-media) { display: grid; grid-template-columns: 1fr 1fr !important; gap: 18px; }
stimma-compare.sp-slider .sp-cmp { display: grid; grid-template-columns: 1fr 1fr; }
stimma-compare.sp-slider figure:first-child { position: static; width: auto; overflow: visible; }
stimma-compare.sp-slider figure:first-child img { width: 100%; max-width: 100%; }
stimma-files .sp-files { display: none; }
stimma-files::before { content: "Browse the included files in index.html."; font-size: 12px; }
.sp-footer { break-inside: avoid; margin-top: 28px; padding-top: 14px; }
.sp-footer .sp-brand { display: block; white-space: nowrap; }
.sp-footer .sp-wordmark { margin-left: 7px; }
"""


def export_pdf(bundle_dir: Path) -> bytes:
    """Render embedded assets only: no network or ambient filesystem access."""
    from weasyprint import HTML, default_url_fetcher

    def embedded_only(url, **kwargs):
        if not url.startswith('data:'):
            raise ValueError('PDF cover resources must be embedded')
        return default_url_fetcher(url, **kwargs)

    html = export_single_html(bundle_dir).replace(
        '</head>', f'<style>{PRINT_CSS}</style></head>', 1,
    )
    # Keep type/vector artwork sharp and raster scenes at print resolution;
    # the ZIP still contains the original full-resolution preview images.
    return HTML(string=html, url_fetcher=embedded_only).write_pdf(
        presentational_hints=True, dpi=300,
    )
