"""Prove packaged ZIP/PDF exports load the bundled native renderer on macOS."""
import ctypes
from io import BytesIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import zipfile

runtime = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(runtime / 'backend'))
from packages.export import export_zip
from packages.manifest import new_manifest
from packages.print_cover import export_pdf

with TemporaryDirectory() as directory:
    root = Path(directory)
    (root / 'index.html').write_text(
        '<html><head><style>body { font-family: sans-serif }</style></head>'
        '<body><h1>Package export</h1><p>Readable text.</p></body></html>'
    )
    assert export_pdf(root).startswith(b'%PDF-')
    with zipfile.ZipFile(BytesIO(export_zip(root, new_manifest(title='Package export')))) as archive:
        assert archive.read('cover.pdf').startswith(b'%PDF-')
        assert 'index.html' in archive.namelist()

# Import success alone is insufficient: a build machine's Homebrew can mask a
# missing library. Every vendored soname must resolve inside this runtime.
native_dir = runtime / 'python' / 'lib'
sonames = {library.name for library in native_dir.glob('*.dylib')}
dyld = ctypes.CDLL(None)
dyld._dyld_image_count.restype = ctypes.c_uint32
dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
dyld._dyld_get_image_name.restype = ctypes.c_char_p
for index in range(dyld._dyld_image_count()):
    loaded = Path(dyld._dyld_get_image_name(index).decode())
    if loaded.name in sonames and loaded.resolve().parent != native_dir:
        raise RuntimeError(f'PDF export loaded an unbundled library: {loaded.name}')
print('Packaged macOS ZIP and PDF exports passed')
