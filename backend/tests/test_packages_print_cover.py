"""The PDF is a portable copy of the cover, not another recipe output."""
import io
import zipfile

import pytest

from PIL import Image
import pypdfium2 as pdfium

from packages.cover import render_cover_document
from packages.export import export_zip
from packages.manifest import new_manifest
from packages.print_cover import export_pdf


def test_zip_includes_readable_pdf_with_both_appearances_and_repeating_footer(tmp_path, monkeypatch):
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
        assert text.count('Made with') == len(pdf)
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


@pytest.mark.parametrize("second_layout", ["single", "stack"])
def test_page_groups_print_as_landscape_slides(tmp_path, second_layout):
    manifest = new_manifest(title='Example')
    Image.new('RGB', (800, 500), 'orange').save(tmp_path / 'image.png')
    manifest['members'] = [{'id': 'm1', 'name': 'Image', 'path': 'image.png'}]
    html, problems = render_cover_document(manifest, authored_html='''
      <div class="sp-page"><h1>Example</h1>
        <stimma-section page label="First platform" layout="pair">
          <stimma-media ref="m1"></stimma-media><stimma-media ref="m1"></stimma-media>
          <stimma-grid slot="details">
            <stimma-media ref="m1" caption="Store example"></stimma-media>
            <stimma-media ref="m1" caption="Notification example"></stimma-media>
          </stimma-grid>
        </stimma-section>
        <stimma-section page label="Second platform" layout="SECOND_LAYOUT">
          <stimma-media ref="m1"></stimma-media>
          EXTRA_MEDIA
        </stimma-section>
        <stimma-section page label="Details">
          <stimma-appearance label="Appearance">
            <div when="light"><stimma-media ref="m1" caption="Light example"></stimma-media></div>
            <div when="dark"><stimma-media ref="m1" caption="Dark example"></stimma-media></div>
          </stimma-appearance>
        </stimma-section>
        <stimma-section page label="Contents"><p>One image.</p></stimma-section>
      </div>'''.replace('SECOND_LAYOUT', second_layout).replace('EXTRA_MEDIA', '<stimma-media ref="m1"></stimma-media>' if second_layout == 'stack' else ''), bundle_dir=tmp_path)
    assert not problems
    (tmp_path / 'index.html').write_text(html)
    with pdfium.PdfDocument(export_pdf(tmp_path)) as pdf:
        assert len(pdf) == 6  # opening, two platforms, two appearances, contents
        texts = [' '.join(page.get_textpage().get_text_range().split()) for page in pdf]
        assert 'First platform' in texts[1] and 'Second platform' not in texts[1]
        assert 'Store example' in texts[1] and 'Notification example' in texts[1]
        assert 'Second platform' in texts[2]
        assert 'Light example' in texts[3] and 'Dark example' not in texts[3]
        assert 'Dark example' in texts[4] and 'Light example' not in texts[4]
        assert all(text.count('Made with') == 1 for text in texts)
        assert all(page.get_width() / page.get_height() == 16 / 9 for page in pdf)
    assert (tmp_path / 'index.html').read_text() == html


def test_crowded_pair_reports_an_authoring_problem(tmp_path):
    manifest = new_manifest(title='Example')
    _, problems = render_cover_document(manifest, authored_html='''
      <stimma-section page label="Crowded" layout="pair">
        <stimma-media ref="missing"></stimma-media>
        <stimma-media ref="missing"></stimma-media>
        <stimma-media ref="missing"></stimma-media>
      </stimma-section>''', bundle_dir=tmp_path)
    assert any('layout=pair needs 2 media items' in problem for problem in problems)


def test_optional_details_stay_in_html_without_duplicating_pdf_slides(tmp_path):
    manifest = new_manifest(title='Example')
    Image.new('RGB', (800, 500), 'orange').save(tmp_path / 'image.png')
    manifest['members'] = [{'id': 'm1', 'name': 'Image', 'path': 'image.png'}]
    html, problems = render_cover_document(manifest, authored_html='''
      <div class="sp-page"><h1>Example</h1>
        <stimma-section page label="Phone scenes" layout="pair">
          <stimma-media ref="m1"></stimma-media><stimma-media ref="m1"></stimma-media>
          <details slot="details"><summary>Details</summary>
            <stimma-appearance label="Appearance">
              <stimma-grid when="light">
                <stimma-media ref="m1" caption="Light store"></stimma-media>
                <stimma-media ref="m1" caption="Light notification"></stimma-media>
              </stimma-grid>
              <stimma-grid when="dark">
                <stimma-media ref="m1" caption="Dark store"></stimma-media>
                <stimma-media ref="m1" caption="Dark notification"></stimma-media>
              </stimma-grid>
            </stimma-appearance>
          </details>
        </stimma-section>
      </div>''', bundle_dir=tmp_path)
    assert not problems
    assert '<details slot="details">' in html
    assert 'Light store' in html and 'Dark store' in html
    (tmp_path / 'index.html').write_text(html)
    with pdfium.PdfDocument(export_pdf(tmp_path)) as pdf:
        assert len(pdf) == 2
        text = pdf[1].get_textpage().get_text_range()
        assert 'Phone scenes' in text and text.count('Made with') == 1
        assert all(word not in text for word in ['Details', 'Appearance', 'store', 'notification'])
        # The main scene images are still present.
        images = [obj for obj in pdf[1].get_objects() if obj.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE]
        assert len(images) >= 2
    assert (tmp_path / 'index.html').read_text() == html
