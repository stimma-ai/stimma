"""Building, saving, rebuilding and inspecting package bundles.

``PackageBuilder`` assembles a ``.stimmapackage`` directory in managed
staging, then ``save`` registers it as a MediaItem and (optionally) as a
``package`` container Asset whose members mirror the manifest: a member whose
media is an Asset's payload links to that Asset (so a new revision of the
master makes the package stale); bare media is embedded exactly.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app_dirs
from config_version import get_config_version_manager
from core.logging import get_logger
from database import Asset, AssetRevision, ContainerMember, MediaItem
from generation_metadata import dump_generation_metadata
from packages import cache as run_cache
from packages.cover import COVER_NAME, CoverError, render_cover_document
from packages.manifest import (
    COVER_SOURCE_NAME,
    TILE_NAME,
    EXTRAS_DIR,
    KIT_VERSION,
    MANIFEST_NAME,
    MEMBERS_DIR,
    PACKAGE_EXTENSION,
    PACKAGE_FORMAT,
    ManifestError,
    check_bundle_path,
    check_case_collisions,
    iter_manifest_paths,
    new_manifest,
    parse_manifest,
    read_manifest,
    sha256_file,
    slugify,
    validate_manifest,
    write_manifest,
)
from packages.recipes import (
    RecipeError,
    RecipeSpec,
    ResolvedInput,
    WrittenFile,
    cache_key,
    describe_file,
    get_recipe,
    run_recipe,
    validate_inputs,
    validate_params,
)
from utils.lineage import propagate_tool_lineage, record_lineage

log = get_logger(__name__)

RUN_TIMEOUT_S = 180.0


class PackageError(ValueError):
    pass


def _require_standalone_file(path: Path, file_format: str | None = None) -> None:
    """Native container JSON resolves through the library, not relative files.

    A raw manifest is not a portable container export. This applies to all
    library-reference container families; ordinary JSON and source ZIPs remain
    valid package files.
    """
    from sprite_document import CONTAINER_FORMATS

    reference_formats = CONTAINER_FORMATS - {PACKAGE_FORMAT}
    name = path.name.lower()
    if (file_format or "").lower() in reference_formats or any(
        name.endswith("." + fmt) for fmt in reference_formats
    ):
        raise PackageError(
            f"{path.name} is a library-reference manifest, not a standalone source file. "
            "Use self-contained source archives or production exports instead; "
            "omit this loose native manifest from the handoff."
        )


def _as_png(data: bytes) -> bytes:
    """Normalize tile bytes to PNG so the thumbnail path has one format to open."""
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            if (img.format or "").upper() == "PNG":
                return data
            buf = io.BytesIO()
            img.convert("RGBA").save(buf, format="PNG", optimize=True)
            return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise PackageError(f"tile image is not a readable image: {exc}") from exc


# Media resolution -----------------------------------------------------------

async def live_media(session: AsyncSession, media_id: int) -> MediaItem:
    media = await session.get(MediaItem, int(media_id))
    if (
        media is None
        or media.deleted_at is not None
        or media.deletion_pending_at is not None
        or media.ephemeral_run_id is not None
    ):
        raise PackageError(f"media {media_id} is not available")
    if not Path(media.file_path).exists():
        raise PackageError(f"media {media_id} has no file on disk")
    return media


async def media_for_hash(session: AsyncSession, digest: str) -> Optional[MediaItem]:
    return await session.scalar(
        select(MediaItem)
        .where(
            MediaItem.file_hash == digest,
            MediaItem.deleted_at.is_(None),
            MediaItem.deletion_pending_at.is_(None),
            MediaItem.ephemeral_run_id.is_(None),
        )
        .order_by(MediaItem.id.desc())
        .limit(1)
    )


async def media_for_member(session: AsyncSession, member: dict[str, Any]) -> Optional[MediaItem]:
    """Resolve a manifest member: media id first (when its hash still matches), then hash."""
    media_id = member.get("media_id")
    if media_id is not None:
        media = await session.get(MediaItem, int(media_id))
        if (
            media is not None
            and media.deleted_at is None
            and media.deletion_pending_at is None
            and media.file_hash == member.get("hash")
        ):
            return media
    if member.get("hash"):
        return await media_for_hash(session, member["hash"])
    return None


# Builder --------------------------------------------------------------------

@dataclass
class _Member:
    id: str
    role: Optional[str]
    media: MediaItem
    name: str
    rel_path: str


@dataclass
class _Run:
    id: str
    spec: RecipeSpec
    inputs: dict[str, str]  # role -> member id
    params: dict[str, Any]
    root: str
    files: list[WrittenFile] = field(default_factory=list)
    key: str = ""
    cached: bool = False
    tile_png: Optional[bytes] = None
    source_dir: Optional[Path] = None


@dataclass
class _Extra:
    source: Path
    name: str
    rel_path: str


class PackageBuilder:
    """Assemble one package revision. Use as ``async with`` to clean up scratch."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        profile_id: str,
        title: str,
        slug: Optional[str] = None,
        chat_id: Optional[int] = None,
        project_id: Optional[int] = None,
        output_context_kind: Optional[str] = None,
        output_context_id: Optional[str] = None,
        source: str = "package_builder",
    ):
        self.session = session
        self.profile_id = profile_id
        self.title = (title or "").strip() or "Untitled package"
        self.slug = slug or slugify(self.title)
        self.chat_id = chat_id
        self.project_id = project_id
        self.output_context_kind = output_context_kind
        self.output_context_id = output_context_id
        self.source = source
        self.members: list[_Member] = []
        self.runs: list[_Run] = []
        self.extras: list[_Extra] = []
        self.cover_source: Optional[str] = None
        self.tile_png: Optional[bytes] = None
        self._scratch = Path(tempfile.mkdtemp(prefix="stimma-package-"))
        self._bundle_dir: Optional[Path] = None
        self._used_paths: set[str] = set()
        self._dirty_runs: set[str] = set()

    async def __aenter__(self) -> "PackageBuilder":
        return self

    async def __aexit__(self, *exc) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        shutil.rmtree(self._scratch, ignore_errors=True)

    async def load(self, media_id: int) -> None:
        """Open an exact saved revision, preserving its files and recipe versions.

        This is an edit, not a rebuild from current masters or current recipes.
        """
        media = await live_media(self.session, media_id)
        if media.file_format != PACKAGE_FORMAT:
            raise PackageError("Open requires package media")
        await self.load_snapshot(Path(media.file_path))

    async def load_snapshot(self, bundle: Path) -> None:
        """Restore a verified bundle snapshot, including unsaved preview outputs."""
        if self.members or self.runs or self.extras:
            raise PackageError("Open requires an empty draft")
        bundle = Path(bundle)

        def contained(rel):
            path = bundle / rel
            if not path.resolve().is_relative_to(bundle.resolve()) or not path.is_file():
                raise PackageError(f"Package file unavailable: {rel}")
            return path

        contained(MANIFEST_NAME)
        manifest = read_manifest(bundle)
        problems = validate_manifest(manifest)
        if problems:
            raise PackageError("Invalid package: " + "; ".join(problems))

        def checked(entry):
            rel = check_bundle_path(entry["path"])
            path = contained(rel)
            if sha256_file(path) != entry["hash"]:
                raise PackageError(f"Package file changed: {rel}")
            return path

        self.title, self.slug = manifest["title"], manifest["slug"]
        for entry in manifest.get("members", []):
            checked(entry)
            source = await media_for_member(self.session, entry)
            if source is None or not Path(source.file_path).is_file() or sha256_file(Path(source.file_path)) != entry["hash"]:
                raise PackageError(f"Package member payload unavailable: {entry['name']}")
            self.members.append(_Member(entry["id"], entry.get("role"), source,
                                        entry["name"], entry["path"]))
            self._used_paths.add(entry["path"])
        for entry in manifest.get("runs", []):
            recipe = entry["recipe"]
            # These bytes are already built. Installed recipes are needed only
            # for an explicit rerun, never to carry existing outputs forward.
            spec = RecipeSpec(recipe["id"], recipe["version"], recipe["display_name"],
                              "Preserved output", [], [], lambda b: None,
                              source=recipe["source"])
            run = _Run(entry["id"], spec, dict(entry["inputs"]), dict(entry["params"]),
                       entry["root"], key=entry.get("cache_key", ""))
            run.source_dir = self._scratch / "preserved" / run.id
            for file in entry.get("files", []):
                src = checked(file)
                if not file["path"].startswith(run.root):
                    raise PackageError("Run file is outside its root")
                rel = file["path"][len(run.root):]
                dst = run.source_dir / check_bundle_path(rel)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                role = next((k for k, v in run.inputs.items() if v == file.get("source")), None)
                run.files.append(WrittenFile(rel, file["hash"], file["size"], source=role))
            self.runs.append(run)
            self._used_paths.add(run.root.rstrip("/"))
        for entry in manifest.get("extras", []):
            src = checked(entry)
            dst = self._scratch / "preserved-extras" / check_bundle_path(entry["path"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            self.extras.append(_Extra(dst, entry["name"], entry["path"]))
            self._used_paths.add(entry["path"])
        cover = bundle / COVER_SOURCE_NAME
        if (manifest.get("cover") or {}).get("kind") == "authored":
            if not cover.is_file():
                raise PackageError("Package is missing its editable cover source")
            self.cover_source = contained(COVER_SOURCE_NAME).read_text(encoding="utf-8")
        if manifest.get("cover_image"):
            self.set_tile(contained(check_bundle_path(manifest["cover_image"])))

    async def replace_member(self, member_id: str, media_id: int) -> None:
        """Replace one source in place; dependent runs must be explicitly rerun."""
        member = self.member(member_id)
        media = await live_media(self.session, media_id)
        _require_standalone_file(Path(media.file_path), media.file_format)
        if not Path(media.file_path).is_file():
            raise PackageError("Replacement member must be a file")
        if member.media.file_hash != media.file_hash:
            self._dirty_runs.update(r.id for r in self.runs if member_id in r.inputs.values())
        member.media = media

    async def rerun(self, run_id: str, params: Optional[dict[str, Any]] = None) -> str:
        """Rebuild only one run, retaining its id and output root."""
        old = next((r for r in self.runs if r.id == run_id), None)
        if old is None:
            raise PackageError(f"Unknown run {run_id!r}")
        index = self.runs.index(old)
        root = old.root.rstrip("/")
        self._used_paths.discard(root)
        from uuid import uuid4
        try:
            await self.run(old.spec.id, old.inputs, old.params if params is None else params,
                           run_id="edit-" + uuid4().hex, root=root)
        except Exception:
            self._used_paths.add(root)
            raise
        new = self.runs.pop()
        if not new.cached:
            new.source_dir = self._scratch / "runs" / new.id
        new.id = old.id
        self.runs[index] = new
        self._dirty_runs.discard(run_id)
        return run_id

    # members
    def _unique_path(self, rel_path: str) -> str:
        rel = check_bundle_path(rel_path)
        if rel.lower() not in {p.lower() for p in self._used_paths}:
            self._used_paths.add(rel)
            return rel
        stem, dot, ext = rel.rpartition(".")
        if not dot or "/" in ext:
            stem, ext = rel, ""
        n = 2
        while True:
            candidate = f"{stem}-{n}.{ext}" if ext else f"{stem}-{n}"
            if candidate.lower() not in {p.lower() for p in self._used_paths}:
                self._used_paths.add(candidate)
                return candidate
            n += 1

    async def add_member(self, media_id: int, *, role: Optional[str] = None, member_id: Optional[str] = None) -> str:
        """Add a library media item as a member. Returns the member id."""
        media = await live_media(self.session, media_id)
        _require_standalone_file(Path(media.file_path), media.file_format)
        for existing in self.members:
            if existing.media.id == media.id and (role is None or existing.role == role):
                return existing.id
        n = len(self.members) + 1
        while any(m.id == f"m{n}" for m in self.members):
            n += 1
        mid = member_id or f"m{n}"
        if any(m.id == mid for m in self.members):
            raise PackageError(f"member id {mid!r} already used")
        name = os.path.basename(media.file_path)
        if Path(media.file_path).is_dir():
            raise PackageError(f"media {media.id} is a bundle and cannot be a package member")
        rel = self._unique_path(f"{MEMBERS_DIR}/{name}")
        self.members.append(_Member(id=mid, role=role, media=media, name=name, rel_path=rel))
        return mid

    def member(self, member_id: str) -> _Member:
        for m in self.members:
            if m.id == member_id:
                return m
        raise PackageError(f"unknown member {member_id!r}")

    # extras
    def add_extra(self, path: Path, *, name: Optional[str] = None) -> str:
        path = Path(path)
        if not path.is_file():
            raise PackageError(f"extra file not found: {path}")
        _require_standalone_file(path)
        name = name or path.name
        rel = self._unique_path(f"{EXTRAS_DIR}/{name}")
        self.extras.append(_Extra(source=path, name=name, rel_path=rel))
        return rel

    def replace_extra(self, ref: str, path: Path) -> str:
        """Replace an exact existing extra ref without changing its name or path."""
        extra = next((item for item in self.extras if item.rel_path == ref), None)
        if extra is None:
            raise PackageError(f"unknown extra {ref!r}; use its manifest path")
        path = Path(path)
        if not path.is_file():
            raise PackageError(f"extra file not found: {path}")
        _require_standalone_file(path)
        extra.source = path
        return extra.rel_path

    # the package's face
    def set_tile(self, source: "Path | bytes") -> None:
        """Set the designed square shown for this package in the library.

        Accepts image bytes or a path. Anything the agent can make works — a
        layout it designed, a render, a mockup. It is stored outside the
        deliverable and is never part of what the client receives.
        """
        data = source if isinstance(source, bytes) else Path(source).read_bytes()
        if not data:
            raise PackageError("tile image is empty")
        self.tile_png = _as_png(data)

    # cover
    def set_cover(self, html_text: str) -> None:
        if not (html_text or "").strip():
            raise PackageError("cover HTML is empty")
        _document, problems = render_cover_document(self._manifest(), authored_html=html_text, strict=True)
        if problems:
            raise CoverError("cover has problems: " + "; ".join(problems))
        self.cover_source = html_text

    # runs
    async def _resolve_inputs(self, spec: RecipeSpec, inputs: dict[str, str]) -> dict[str, ResolvedInput]:
        resolved: dict[str, ResolvedInput] = {}
        for role, member_id in inputs.items():
            member = self.member(member_id)
            path = Path(member.media.file_path)
            facts = describe_file(path)
            resolved[role] = ResolvedInput(
                role=role, path=path, hash=member.media.file_hash, member_id=member.id, **facts
            )
        return resolved

    async def _render_vector(self, given: ResolvedInput, size: int) -> bytes:
        """Render one vector input at ``size``, natively, memoized by content.

        Every size is its own render, so small artwork is drawn small instead
        of being resampled from a large raster. Renders are cached by (content
        hash, size) across runs and rebuilds, since the same mark at the same
        size is the same pixels.
        """
        from utils.svg_doc import intrinsic_size, parse_svg, read_svg_file
        from utils.document_render import (
            LayoutRenderBusy,
            LayoutRenderUnavailable,
            render_svg_document,
        )

        size = max(1, int(size))
        cached = run_cache.render_lookup(self.profile_id, given.hash, size)
        if cached is not None:
            return cached

        text = read_svg_file(given.path)
        try:
            w, h = intrinsic_size(parse_svg(text))
        except Exception:  # noqa: BLE001
            w, h = 1, 1
        if w >= h:
            rw, rh = size, max(1, int(round(size * h / w)))
        else:
            rw, rh = max(1, int(round(size * w / h))), size
        try:
            png = await render_svg_document(
                text, rw, rh, queue_timeout_s=60.0
            )
        except (LayoutRenderBusy, LayoutRenderUnavailable) as exc:
            raise RecipeError(
                "Vector artwork is rendered by the app's own engine, so Stimma has to be "
                f"open to build this package from {given.path.name}. "
                "Open Stimma and try again, or use a raster master."
            ) from exc
        run_cache.render_store(self.profile_id, given.hash, size, png)
        return png

    async def run(
        self,
        recipe_id: str,
        inputs: dict[str, str],
        params: Optional[dict[str, Any]] = None,
        *,
        run_id: Optional[str] = None,
        root: Optional[str] = None,
    ) -> str:
        """Run a recipe over members. Returns the run id. Memoized by content."""
        spec = get_recipe(recipe_id, self.profile_id)
        if spec is None:
            raise PackageError(f"recipe {recipe_id!r} is not installed")
        n = len(self.runs) + 1
        while any(r.id == f"r{n}" for r in self.runs):
            n += 1
        rid = run_id or f"r{n}"
        if any(r.id == rid for r in self.runs):
            raise PackageError(f"run id {rid!r} already used")
        resolved = await self._resolve_inputs(spec, inputs)
        problems = validate_inputs(spec, resolved)
        if problems:
            raise RecipeError("; ".join(problems))
        canonical = validate_params(spec, params)
        key = cache_key(spec, resolved, canonical, slug=self.slug)
        root_name = self._unique_path((root or spec.id).rstrip("/"))
        run = _Run(id=rid, spec=spec, inputs=dict(inputs), params=canonical, root=root_name + "/", key=key)
        cached = run_cache.lookup(self.profile_id, key)
        if cached is not None:
            run.files, run.tile_png = cached
            run.cached = True
        else:
            out_dir = self._scratch / "runs" / rid
            try:
                result = await asyncio.wait_for(
                    run_recipe(
                        spec, resolved, canonical, out_dir,
                        slug=self.slug, renderer=self._render_vector,
                    ),
                    timeout=RUN_TIMEOUT_S,
                )
            except asyncio.TimeoutError as exc:
                raise RecipeError(f"recipe {spec.id!r} exceeded {RUN_TIMEOUT_S:.0f}s; recipes must be quick") from exc
            run.files = result.files
            run.tile_png = result.tile_png
            run_cache.store(self.profile_id, key, out_dir, result.files, tile_png=result.tile_png)
        self.runs.append(run)
        return rid

    # assembly
    def _manifest(self) -> dict[str, Any]:
        manifest = new_manifest(title=self.title, slug=self.slug)
        for m in self.members:
            manifest["members"].append({
                "id": m.id,
                "role": m.role,
                "name": m.name,
                "path": m.rel_path,
                "media_id": m.media.id,
                "hash": m.media.file_hash,
                "size": m.media.file_size,
                "media_type": mimetypes.guess_type(m.name)[0] or "application/octet-stream",
                "width": m.media.width,
                "height": m.media.height,
            })
        for r in self.runs:
            manifest["runs"].append({
                "id": r.id,
                "recipe": {
                    "id": r.spec.id,
                    "version": r.spec.version,
                    "source": r.spec.source,
                    "display_name": r.spec.display_name,
                },
                "inputs": r.inputs,
                "params": r.params,
                "root": r.root,
                "cache_key": r.key,
                "files": [
                    {
                        "path": r.root + f.path,
                        "hash": f.hash,
                        "size": f.size,
                        **({"source": r.inputs.get(f.source)} if f.source else {}),
                    }
                    for f in r.files
                ],
            })
        for e in self.extras:
            manifest["extras"].append({
                "name": e.name,
                "path": e.rel_path,
                "hash": sha256_file(e.source),
                "size": e.source.stat().st_size,
            })
        tile = self.tile_png or next((r.tile_png for r in self.runs if r.tile_png), None)
        manifest["cover_image"] = TILE_NAME if tile else None
        manifest["cover"] = {
            "path": COVER_NAME,
            "kind": "authored" if self.cover_source else "auto",
            "kit_version": KIT_VERSION,
        }
        return manifest

    def manifest(self) -> dict[str, Any]:
        """Snapshot the draft, including exact bundle paths for all run files."""
        return self._manifest()

    def _assemble(self, manifest: dict[str, Any], destination: Path | None = None) -> Path:
        if self._dirty_runs:
            raise PackageError("Changed members require rerun() for: " + ", ".join(sorted(self._dirty_runs)))
        if destination is None:
            staging = app_dirs.get_managed_staging_dir(self.profile_id, "generated")
            staging.mkdir(parents=True, exist_ok=True)
            base = f"{self.slug}{PACKAGE_EXTENSION}"
            bundle = staging / base
            n = 1
            while bundle.exists():
                n += 1
                bundle = staging / f"{self.slug}-{n}{PACKAGE_EXTENSION}"
        else:
            bundle = destination
        bundle.mkdir(parents=True)
        try:
            for m in self.members:
                dst = bundle / m.rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(m.media.file_path, dst)
            for r in self.runs:
                run_root = bundle / r.root.rstrip("/")
                run_root.mkdir(parents=True, exist_ok=True)
                if r.cached:
                    run_cache.materialize(self.profile_id, r.key, r.files, run_root, copy=destination is not None)
                else:
                    src_root = r.source_dir or self._scratch / "runs" / r.id
                    for f in r.files:
                        dst = run_root / f.path
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_root / f.path, dst)
            for e in self.extras:
                dst = bundle / e.rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(e.source, dst)
            tile = self.tile_png or next((r.tile_png for r in self.runs if r.tile_png), None)
            if tile:
                tile_path = bundle / TILE_NAME
                tile_path.parent.mkdir(parents=True, exist_ok=True)
                tile_path.write_bytes(tile)
            html_text, problems = render_cover_document(
                manifest, authored_html=self.cover_source, strict=True, bundle_dir=bundle
            )
            if problems:
                raise CoverError("cover has problems: " + "; ".join(problems))
            (bundle / COVER_NAME).write_text(html_text, encoding="utf-8")
            if self.cover_source:
                src = bundle / COVER_SOURCE_NAME
                src.parent.mkdir(parents=True, exist_ok=True)
                src.write_text(self.cover_source, encoding="utf-8")
            paths = list(iter_manifest_paths(manifest)) + [COVER_NAME]
            check_case_collisions(paths)
            write_manifest(bundle, manifest)
        except Exception:
            shutil.rmtree(bundle, ignore_errors=True)
            raise
        return bundle

    async def save(
        self,
        *,
        materialize_asset: bool = False,
        revises_asset_id: Optional[int] = None,
        revision_note: Optional[str] = None,
        origin_type: Optional[str] = None,
    ) -> tuple[MediaItem, Optional[Asset]]:
        """Write the bundle, register it, and optionally create/advance the Asset."""
        if not self.members and not self.runs and not self.extras:
            raise PackageError("a package needs at least one member, run or extra file")
        manifest = self._manifest()
        errors = validate_manifest(manifest)
        if errors:
            raise ManifestError("; ".join(errors))
        bundle = await asyncio.to_thread(self._assemble, manifest)

        now = datetime.utcnow()
        member_ids = [m.media.id for m in self.members]
        media_item = MediaItem(
            file_path=str(bundle),
            file_hash=sha256_file(bundle / COVER_NAME),  # replaced by the whole-bundle hash on staging
            file_size=(bundle / COVER_NAME).stat().st_size,
            file_format=PACKAGE_FORMAT,
            original_filename=bundle.name,
            created_date=now,
            modified_date=now,
            indexed_date=now,
            metadata_status="completed",
            metadata_processed_at=now,
            metadata_config_version=get_config_version_manager().get_version("metadata"),
            width=0,
            height=0,
            megapixels=0.0,
            has_alpha=False,
            clip_status="skipped",
            face_detection_status="skipped",
            vlm_caption_status="skipped",
            raw_metadata=json.dumps(manifest),
            generation_metadata=dump_generation_metadata(
                task_type="package",
                source=self.source,
                source_inputs=[{"media_id": m.media.id, "role": m.role or "member"} for m in self.members],
                extra={
                    "package": {
                        "title": self.title,
                        "recipes": [r.spec.id for r in self.runs],
                        "member_count": len(self.members),
                    }
                },
            ),
        )
        self.session.add(media_item)
        await self.session.flush()

        from storage_service import cleanup_staged_source, stage_managed_media

        await stage_managed_media(self.session, media=media_item, profile_id=self.profile_id, remove_source=True)

        if self.output_context_kind and self.output_context_id:
            from asset_service import acquire_media_owner

            await acquire_media_owner(
                self.session,
                media_id=media_item.id,
                root_kind=self.output_context_kind,
                root_id=self.output_context_id,
                role="result",
                idempotency_key=f"{self.output_context_kind}:{self.output_context_id}:package:{media_item.id}",
            )
        if self.chat_id is not None:
            from asset_service import acquire_media_owner

            await acquire_media_owner(
                self.session,
                media_id=media_item.id,
                root_kind="chat",
                root_id=self.chat_id,
                role="result",
                idempotency_key=f"chat:{self.chat_id}:package:{media_item.id}",
            )
        if self.project_id is not None:
            from project_service import attach_media_to_project

            await attach_media_to_project(self.session, self.project_id, media_item.id)

        await self.session.commit()
        await self.session.refresh(media_item)
        await cleanup_staged_source(self.session, media_id=media_item.id)

        if member_ids:
            await record_lineage(self.session, media_item.id, member_ids, "package")
            await propagate_tool_lineage(self.session, media_item.id, member_ids)
            await self.session.commit()

        asset: Optional[Asset] = None
        if revises_asset_id is not None:
            asset = await commit_package_revision(
                self.session, asset_id=revises_asset_id, media=media_item, note=revision_note
            )
        elif materialize_asset:
            asset = await create_package_asset(self.session, media=media_item, origin_type=origin_type or self.source)
        await self.session.commit()

        try:
            run_cache.enforce_budget(self.profile_id)
            run_cache.enforce_render_budget(self.profile_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"package run cache budget enforcement failed: {exc}")

        try:
            from utils.websocket import ws_manager

            await ws_manager.broadcast("media_added", {"media_id": media_item.id, "count": 1})
        except Exception as exc:  # noqa: BLE001
            log.debug(f"package media_added broadcast skipped: {exc}")
        return media_item, asset


# Manifest access ------------------------------------------------------------

async def manifest_for_media(session: AsyncSession, media: MediaItem) -> Optional[dict[str, Any]]:
    """The manifest, from the cached copy or from disk."""
    manifest = parse_manifest(media.raw_metadata or "")
    if manifest is not None:
        return manifest
    bundle = Path(media.file_path)
    if bundle.is_dir():
        try:
            manifest = read_manifest(bundle)
        except (ManifestError, OSError):
            return None
        media.raw_metadata = json.dumps(manifest)
        return manifest
    return None


# Container membership -------------------------------------------------------

async def package_member_specs(session: AsyncSession, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Container member specs: link an Asset when the member is one, else embed the media.

    ``title`` carries the member id so a revision's rows map back onto the
    manifest; ``member_metadata`` keeps role and hash.
    """
    specs: list[dict[str, Any]] = []
    for member in manifest.get("members") or []:
        media = await media_for_member(session, member)
        if media is None:
            continue
        revision = await session.scalar(
            select(AssetRevision).join(Asset, Asset.id == AssetRevision.asset_id).where(
                AssetRevision.primary_media_id == media.id,
                AssetRevision.deleted_at.is_(None),
                Asset.deleted_at.is_(None),
                Asset.state == "active",
            )
        )
        spec: dict[str, Any] = (
            {"linked_asset_id": revision.asset_id} if revision is not None else {"embedded_media_id": media.id}
        )
        spec["title"] = member["id"]
        spec["member_metadata"] = json.dumps({"role": member.get("role"), "hash": member.get("hash")})
        specs.append(spec)
    return specs


async def create_package_asset(
    session: AsyncSession, *, media: MediaItem, origin_type: str = "package", origin_id: Optional[str] = None
) -> Asset:
    from container_service import create_container_asset_from_media

    manifest = await manifest_for_media(session, media)
    if manifest is None:
        raise PackageError("media is not a package")
    return await create_container_asset_from_media(
        session,
        media_id=media.id,
        container_type="package",
        members=await package_member_specs(session, manifest),
        title=manifest.get("title"),
        origin_type=origin_type,
        origin_id=origin_id,
        idempotency_key=f"package:media:{media.id}",
    )


async def commit_package_revision(
    session: AsyncSession, *, asset_id: int, media: MediaItem, note: Optional[str] = None
) -> Asset:
    from container_service import commit_container_revision

    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None or asset.asset_type != "package":
        raise PackageError(f"asset {asset_id} is not a package")
    manifest = await manifest_for_media(session, media)
    if manifest is None:
        raise PackageError("media is not a package")
    await commit_container_revision(
        session,
        asset_id=asset_id,
        media_id=media.id,
        members=await package_member_specs(session, manifest),
        parent_revision_id=asset.current_revision_id,
        note=note,
        idempotency_key=f"package:revision:{asset_id}:{media.id}",
    )
    return asset


# Status and rebuild ---------------------------------------------------------

async def _revision_for_media(session: AsyncSession, media_id: int) -> Optional[AssetRevision]:
    return await session.scalar(
        select(AssetRevision).where(
            AssetRevision.primary_media_id == media_id,
            AssetRevision.deleted_at.is_(None),
        )
    )


async def package_status(session: AsyncSession, media: MediaItem) -> dict[str, Any]:
    """Which members have moved on since this revision was built."""
    manifest = await manifest_for_media(session, media)
    if manifest is None:
        raise PackageError("media is not a package")
    revision = await _revision_for_media(session, media.id)
    links: dict[str, int] = {}
    if revision is not None:
        rows = await session.scalars(
            select(ContainerMember).where(
                ContainerMember.container_revision_id == revision.id,
                ContainerMember.deleted_at.is_(None),
                ContainerMember.linked_asset_id.is_not(None),
            )
        )
        for row in rows:
            if row.title:
                links[row.title] = int(row.linked_asset_id)
    members_out = []
    stale = False
    for member in manifest.get("members") or []:
        entry: dict[str, Any] = {
            "id": member["id"],
            "role": member.get("role"),
            "name": member.get("name"),
            "hash": member.get("hash"),
            "media_id": member.get("media_id"),
            "linked_asset_id": links.get(member["id"]),
            "current_hash": member.get("hash"),
            "current_media_id": member.get("media_id"),
            "stale": False,
            "unavailable": False,
        }
        asset_id = links.get(member["id"])
        if asset_id is not None:
            asset = await session.get(Asset, asset_id)
            head = (
                await session.get(AssetRevision, asset.current_revision_id)
                if asset is not None and asset.current_revision_id
                else None
            )
            head_media = await session.get(MediaItem, head.primary_media_id) if head is not None else None
            if head_media is None or head_media.deleted_at is not None:
                entry["unavailable"] = True
            else:
                entry["current_hash"] = head_media.file_hash
                entry["current_media_id"] = head_media.id
                entry["stale"] = head_media.file_hash != member.get("hash")
        else:
            current = await media_for_member(session, member)
            entry["unavailable"] = current is None
        stale = stale or entry["stale"]
        members_out.append(entry)
    return {
        "asset_id": revision.asset_id if revision is not None else None,
        "revision_id": revision.id if revision is not None else None,
        "stale": stale,
        "members": members_out,
        "runs": [
            {"id": r["id"], "recipe": r.get("recipe"), "root": r.get("root"), "file_count": len(r.get("files") or [])}
            for r in manifest.get("runs") or []
        ],
        "cover": manifest.get("cover"),
        "title": manifest.get("title"),
    }


async def rebuild_package(
    session: AsyncSession,
    *,
    profile_id: str,
    asset_id: int,
    note: Optional[str] = None,
    chat_id: Optional[int] = None,
) -> tuple[MediaItem, Asset, dict[str, Any]]:
    """Re-run every recipe against the members' current revisions; carry the cover forward.

    Returns ``(new_media, asset, report)`` where ``report`` says which runs were
    re-executed and whether the cover was carried unchanged.
    """
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None or asset.asset_type != "package":
        raise PackageError(f"asset {asset_id} is not a package")
    head = await session.get(AssetRevision, asset.current_revision_id) if asset.current_revision_id else None
    if head is None:
        raise PackageError("package has no current revision")
    old_media = await session.get(MediaItem, head.primary_media_id)
    if old_media is None:
        raise PackageError("package revision has no media")
    status = await package_status(session, old_media)
    manifest = await manifest_for_media(session, old_media)
    assert manifest is not None
    old_bundle = Path(old_media.file_path)

    async with PackageBuilder(
        session,
        profile_id=profile_id,
        title=asset.title or manifest.get("title") or "Package",
        slug=manifest.get("slug"),
        chat_id=chat_id,
        source="package_rebuild",
    ) as builder:
        current_by_member = {m["id"]: m for m in status["members"]}
        for member in manifest.get("members") or []:
            current = current_by_member.get(member["id"], {})
            media_id = current.get("current_media_id") or member.get("media_id")
            if current.get("unavailable") or media_id is None:
                raise PackageError(f"member {member.get('name') or member['id']} is no longer available; cannot rebuild")
            await builder.add_member(int(media_id), role=member.get("role"), member_id=member["id"])
        report_runs = []
        for run in manifest.get("runs") or []:
            recipe = run.get("recipe") or {}
            spec = get_recipe(recipe.get("id", ""), profile_id)
            if spec is None:
                raise PackageError(f"recipe {recipe.get('id')!r} is not installed; cannot rebuild")
            if spec.version != recipe.get("version"):
                log.info(f"rebuild: recipe {spec.id} version {recipe.get('version')} -> {spec.version}")
            rid = await builder.run(
                spec.id, dict(run.get("inputs") or {}), dict(run.get("params") or {}),
                run_id=run["id"], root=(run.get("root") or spec.id).rstrip("/"),
            )
            report_runs.append({"id": rid, "recipe": spec.id, "reused_cache": builder.runs[-1].cached})
        for extra in manifest.get("extras") or []:
            src = old_bundle / extra["path"]
            if src.is_file():
                builder.add_extra(src, name=extra.get("name"))
        old_tile = old_bundle / TILE_NAME
        if (manifest.get("cover_image") or "") and old_tile.is_file():
            builder.set_tile(old_tile)
        cover_src = old_bundle / COVER_SOURCE_NAME
        cover_carried = False
        if (manifest.get("cover") or {}).get("kind") == "authored" and cover_src.is_file():
            builder.set_cover(cover_src.read_text(encoding="utf-8"))
            cover_carried = True
        new_media, _ = await builder.save(revises_asset_id=asset_id, revision_note=note or "Rebuilt from current masters")
    report = {"runs": report_runs, "cover_carried_unchanged": cover_carried, "was_stale": status["stale"]}
    return new_media, asset, report
