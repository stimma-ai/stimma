"""Exports: a ZIP with HTML/PDF covers, or one portable HTML file."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any, Optional

from packages.cover import inline_cover_assets
from packages.manifest import COVER_NAME, INTERNAL_DIR, run_by_id


def _add_dir(zf: zipfile.ZipFile, root: Path, prefix: str, *, skip_internal: bool) -> None:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        if skip_internal and rel.startswith(INTERNAL_DIR + "/"):
            continue
        zf.write(path, f"{prefix}{rel}")


def run_zip_bytes(bundle_dir: Path, manifest: dict[str, Any], run_id: str) -> Optional[bytes]:
    """Zip one run's subtree with paths relative to the run root.

    A folder, nothing more: the package export is the zip with the cover in
    it, and this is "download this folder" from inside that.
    """
    run = run_by_id(manifest, run_id)
    if run is None:
        return None
    root = (run.get("root") or "").rstrip("/")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in run.get("files") or []:
            src = Path(bundle_dir) / entry["path"]
            if src.is_file():
                arcname = entry["path"][len(root) + 1:] if root and entry["path"].startswith(root + "/") else entry["path"]
                zf.write(src, arcname)
    return buf.getvalue()


def run_zip_for_path(bundle_dir: Path, manifest: dict[str, Any], rel_path: str) -> Optional[bytes]:
    """Resolve ``<run-root>.zip`` requests to a zip of that run."""
    if not rel_path.endswith(".zip"):
        return None
    root = rel_path[:-4]
    for run in manifest.get("runs") or []:
        if (run.get("root") or "").rstrip("/") == root:
            return run_zip_bytes(bundle_dir, manifest, run["id"])
    return None


def export_zip(bundle_dir: Path, manifest: dict[str, Any], *, folder_name: Optional[str] = None) -> bytes:
    """The whole package, including a static PDF copy of its cover."""
    bundle_dir = Path(bundle_dir)
    prefix = f"{folder_name.rstrip('/')}/" if folder_name else ""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        _add_dir(zf, bundle_dir, prefix, skip_internal=True)
        if (bundle_dir / COVER_NAME).is_file():
            from packages.print_cover import export_pdf

            # Keep any hand-added file with this name; never duplicate ZIP entries.
            pdf_name = "cover.pdf"
            suffix = 2
            while (bundle_dir / pdf_name).exists():
                pdf_name = f"cover-{suffix}.pdf"
                suffix += 1
            zf.writestr(f"{prefix}{pdf_name}", export_pdf(bundle_dir))
        for run in manifest.get("runs") or []:
            root = (run.get("root") or "").rstrip("/")
            data = run_zip_bytes(bundle_dir, manifest, run["id"])
            if root and data:
                zf.writestr(f"{prefix}{root}.zip", data)
    return buf.getvalue()


def export_single_html(bundle_dir: Path) -> str:
    """The cover with previews inlined: opens anywhere, read-only."""
    html_text = (Path(bundle_dir) / COVER_NAME).read_text(encoding="utf-8")
    # Retain high-resolution device/context imagery in the portable cover.
    # Thumbnail callers keep inline_cover_assets' smaller default separately.
    return inline_cover_assets(bundle_dir, html_text, max_side=3840)
