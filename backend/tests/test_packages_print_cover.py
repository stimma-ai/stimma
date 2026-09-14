"""The PDF is a portable copy of the cover, not another recipe output."""
import io
import zipfile

from PIL import Image
import pypdfium2 as pdfium

from packages.cover import render_cover_document
from packages.export import export_zip
from packages.manifest import new_manifest
from packages.print_cover import export_pdf


def test_zip_includes_readable_pdf_with_both_appearances_and_one_footer(tmp_path, monkeypatch):
    import socket

    def denied(*args, **kwargs):
        raise AssertionError('PDF export must stay local')

    monkeypatch.setattr(socket, 'socket', denied)
    image = Image.new('RGB', (800, 500), '#e96a12')
    image.save(tmp_path / 'image.png')
    manifest = new_manifest(title='Example')
    html, problems = render_cover_document(manifest, authored_html='''
      <div class="sp-page"><h1 class="sp-title">Example</h1>
      <stimma-appearance label="Appearance">
        <div when="light">Light example<img src="image.png"></div>
        <div when="dark">Dark example<img src="image.png"></div>
      </stimma-appearance></div>''', bundle_dir=tmp_path)
    assert not problems
    (tmp_path / 'index.html').write_text(html)
    # Preserve an existing extra and avoid duplicate ZIP members.
    (tmp_path / 'cover.pdf').write_bytes(b'Existing hand-added file')
    with zipfile.ZipFile(io.BytesIO(export_zip(tmp_path, manifest))) as archive:
        assert archive.read('cover.pdf') == b'Existing hand-added file'
        data = archive.read('cover-2.pdf')
        assert len(archive.namelist()) == len(set(archive.namelist()))
    with pdfium.PdfDocument(data) as pdf:
        text = ' '.join(''.join(page.get_textpage().get_text_range() for page in pdf).split())
        assert 'Light example' in text and 'Dark example' in text
        assert text.count('Made with') == 1
        assert 'Example' in text
        assert any(obj.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE for page in pdf for obj in page.get_objects())
    assert not (tmp_path / 'cover-2.pdf').exists(), 'Export must not mutate the saved bundle'


def test_pdf_does_not_fetch_external_or_ambient_resources(tmp_path, monkeypatch):
    import weasyprint
    calls = []
    original = weasyprint.default_url_fetcher

    def fetch(url, **kwargs):
        calls.append(url)
        return original(url, **kwargs)

    monkeypatch.setattr(weasyprint, 'default_url_fetcher', fetch)
    secret = tmp_path.parent / 'not-in-package.txt'
    secret.write_text('Private data must not be read')
    (tmp_path / 'index.html').write_text(f'''<html><head></head><body>
      <h1>Local cover</h1><img src="https://example.com/remote.png">
      <img src="{secret.as_uri()}"></body></html>''')
    assert export_pdf(tmp_path).startswith(b'%PDF-')
    assert calls == []
