"""Which library media a workspace file was made from, recorded as the file is written.

The agent makes media in code (Pillow, NumPy, ``stimma.ffmpeg``,
``stimma.join_video``) and then shows or saves the result. Here the platform
notes, per output file, the library media that went into that file, so the save
inherits exactly those. Nothing is guessed from what else the run touched.

Records are keyed by the file's content hash, not its path: a copy or rename
keeps its sources, an overwrite drops them. An input resolves to library media
when its bytes are a library item (a workspace copy, a tool result), else to the
sources recorded for those bytes, so chains flatten: a file made from a file made
from library clips lists the clips. The ledger lives in the chat workspace.

Images saved from Pillow record the sources their data carried
(``source_tags``); ffmpeg runs record theirs from the command. Anything else
(raw frames, an external encoder) is declared with
``stimma.record_sources(out, inputs)`` or with ``sources=`` on save.
"""
from __future__ import annotations

import asyncio
import glob as _glob
import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Iterable, Sequence

from sqlalchemy import select

from core.logging import get_logger
from database import MediaItem

log = get_logger(__name__)

LEDGER_NAME = ".stimma-sources.json"
# Image sequences (frames/%04d.png) can be large; past this many files the
# sequence is not traced rather than stalling the call.
_SEQUENCE_CAP = 5000
_LIST_FILE_MAX_BYTES = 1_000_000
_VIDEO_FORMATS = {"mp4", "mov", "webm", "mkv", "avi", "m4v", "gif"}
_AUDIO_FORMATS = {"mp3", "wav", "flac", "aac", "m4a", "ogg", "opus"}

# (path, size, mtime_ns) -> sha256, so repeated calls over the same clips hash once.
_digest_cache: dict[tuple[str, int, int], str] = {}


def file_digest(path: Path) -> str | None:
    try:
        st = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    key = (str(path), st.st_size, st.st_mtime_ns)
    cached = _digest_cache.get(key)
    if cached:
        return cached
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    digest = h.hexdigest()
    if len(_digest_cache) > 20000:
        _digest_cache.clear()
    _digest_cache[key] = digest
    return digest


def _ledger_path(workspace_dir: Path | str) -> Path:
    return Path(workspace_dir) / LEDGER_NAME


def _read_ledger(workspace_dir: Path | str) -> dict[str, Any]:
    try:
        data = json.loads(_ledger_path(workspace_dir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("files"), dict) else {"version": 1, "files": {}}
    except (OSError, ValueError):
        return {"version": 1, "files": {}}


def _dedupe(ids: Iterable[Any]) -> list[int]:
    return list(dict.fromkeys(int(i) for i in ids if isinstance(i, int) and not isinstance(i, bool)))


_ledger_lock = threading.Lock()


def _write_ledger(workspace_dir: Path | str, entries: dict[str, dict[str, Any]]) -> None:
    """Merge entries into the ledger. Agent code saves from its own thread while
    the app loop records ffmpeg runs, hence the lock."""
    from providers.result_receipt import atomic_json
    with _ledger_lock:
        ledger = _read_ledger(workspace_dir)
        ledger["files"].update(entries)
        try:
            atomic_json(str(_ledger_path(workspace_dir)), ledger)
        except OSError as e:
            log.warning(f"[file-sources] could not record sources: {e}")


def _entry(sources: Iterable[Any], base: Any = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"sources": list(sources)}
    if base is not None:
        entry["base"] = base
    return entry


def note_written(workspace_dir: Path | str, path: Path, keys: Iterable[int | str]) -> None:
    """A file was just written from data carrying these source keys (media ids
    or content hashes of files; see ``source_tags``). Synchronous: called from
    inside the save."""
    digest = file_digest(Path(path))
    keys = [k for k in dict.fromkeys(keys) if k != digest]
    if digest and keys:
        _write_ledger(workspace_dir, {digest: _entry(keys)})


async def record_sources(workspace_dir: Path | str | None, outputs: Sequence[Path], sources: Sequence[int],
                         base: int | None = None) -> None:
    """Note that each output file was made from ``sources`` (library media ids).
    ``base`` names the one it is a changed version of, when there are several."""
    sources = _dedupe(sources)
    if workspace_dir is None or not outputs or not sources:
        return
    digests = [d for d in await asyncio.to_thread(lambda: [file_digest(Path(p)) for p in outputs]) if d]
    if digests:
        _write_ledger(workspace_dir, {d: _entry(sources, base if base in sources else None) for d in digests})


async def library_ids_by_hash(session, digests: Sequence[str]) -> dict[str, int]:
    if not digests:
        return {}
    rows = await session.execute(
        select(MediaItem.file_hash, MediaItem.id).where(
            MediaItem.file_hash.in_(list(set(digests))),
            MediaItem.deleted_at.is_(None),
            MediaItem.deletion_pending_at.is_(None),
        ).order_by(MediaItem.id.desc())
    )
    found: dict[str, int] = {}
    for file_hash, media_id in rows.all():
        found.setdefault(file_hash, media_id)
    return found


async def _resolve(session, workspace_dir: Path | str | None, keys: Sequence[Any]) -> list[int]:
    """Source keys as library media ids, in order. A media id is itself; a
    content hash is the library item with those bytes, else the sources recorded
    for those bytes, so chains flatten to library media."""
    files = _read_ledger(workspace_dir)["files"] if workspace_dir is not None else {}

    def recorded(digest: str) -> list[Any]:
        return list((files.get(digest) or {}).get("sources") or [])

    # Every hash reachable through the ledger, for one library lookup.
    reachable: dict[str, None] = {}
    pending = [k for k in keys if isinstance(k, str)]
    while pending:
        digest = pending.pop()
        if digest not in reachable:
            reachable[digest] = None
            pending.extend(k for k in recorded(digest) if isinstance(k, str))
    library = await library_ids_by_hash(session, list(reachable))

    out: list[int] = []

    def expand(key: Any, seen: frozenset[str]) -> None:
        if isinstance(key, int) and not isinstance(key, bool):
            out.append(key)
        elif isinstance(key, str):
            if key in library:
                out.append(library[key])
            elif key not in seen:
                for inner in recorded(key):
                    expand(inner, seen | {key})

    for key in keys:
        expand(key, frozenset())
    return list(dict.fromkeys(out))


async def sources_for_files(session, workspace_dir: Path | str | None, paths: Sequence[Path]) -> list[int]:
    """Library media behind these files, in input order (see module docstring)."""
    digests = await asyncio.to_thread(lambda: [file_digest(Path(p)) for p in paths])
    return await _resolve(session, workspace_dir, [d for d in digests if d])


async def _saved_file_sources(session, workspace_dir: Path | str | None, path: Path) -> tuple[list[int], int | None]:
    digest = await asyncio.to_thread(file_digest, Path(path))
    if workspace_dir is None or not digest:
        return [], None
    entry = _read_ledger(workspace_dir)["files"].get(digest) or {}
    sources = await _resolve(session, workspace_dir, entry.get("sources") or [])
    base = entry.get("base")
    return sources, base if base in sources else None


async def sources_for_file(session, workspace_dir: Path | str | None, path: Path) -> list[int]:
    """Recorded sources of a file about to be saved. A file that is itself a
    library item has none of its own: saving it again is not a derivation."""
    return (await _saved_file_sources(session, workspace_dir, path))[0]


# --- ffmpeg argv --------------------------------------------------------------

_SEQUENCE = re.compile(r"%0?\d*d")


def _expand(token: str, cwd: Path) -> list[Path]:
    """A path token as files: a plain path, or an image sequence pattern."""
    path = Path(token)
    if not path.is_absolute():
        path = cwd / path
    if _SEQUENCE.search(token):
        pattern = _SEQUENCE.sub("*", str(path).replace("[", "[[]"))
        matches = sorted(_glob.glob(pattern))
        return [Path(m) for m in matches[:_SEQUENCE_CAP]] if len(matches) <= _SEQUENCE_CAP else []
    return [path]


def _concat_list_entries(path: Path) -> list[Path] | None:
    """Files named by an ffmpeg concat list (``file 'clip.mp4'`` lines), or None."""
    try:
        if not path.is_file() or path.stat().st_size > _LIST_FILE_MAX_BYTES:
            return None
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    entries: list[Path] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("file "):
            continue
        name = line[5:].strip()
        if len(name) >= 2 and name[0] == name[-1] and name[0] in "'\"":
            name = name[1:-1].replace("'\\''", "'")
        entry = Path(name)
        entries.append(entry if entry.is_absolute() else path.parent / entry)
    return entries or None


def ffmpeg_inputs(argv: Sequence[str], cwd: Path) -> list[Path]:
    """Every file an ffmpeg command reads as media input, in order."""
    files: list[Path] = []
    for i, token in enumerate(argv[:-1]):
        if token != "-i":
            continue
        value = argv[i + 1]
        if value.startswith("concat:"):
            for part in value[len("concat:"):].split("|"):
                files.extend(_expand(part, cwd))
            continue
        if "://" in value or value.startswith(("pipe:", "-")):
            continue
        for path in _expand(value, cwd):
            listed = _concat_list_entries(path) if path.suffix.lower() in (".txt", ".ffconcat", ".list", "") else None
            files.extend(listed if listed is not None else [path])
    return files


def _snapshot(paths: Iterable[Path]) -> dict[Path, tuple[int, int] | None]:
    shot: dict[Path, tuple[int, int] | None] = {}
    for p in paths:
        try:
            st = p.stat()
            shot[p] = (st.st_size, st.st_mtime_ns) if p.is_file() else None
        except OSError:
            shot[p] = None
    return shot


class FfmpegTrace:
    """Before/after view of one ffmpeg run: what it read, what it wrote."""

    def __init__(self, argv: Sequence[str], cwd: Path):
        self.cwd = cwd
        self.inputs = ffmpeg_inputs(argv, cwd)
        input_tokens = {argv[i + 1] for i, t in enumerate(argv[:-1]) if t == "-i"}
        # Output candidates: bare (non-flag) tokens that aren't inputs. Option
        # values that aren't files simply never exist; files that only exist
        # before and after unchanged weren't written.
        self._candidates = [
            t for t in argv
            if t and not t.startswith("-") and t not in input_tokens
            and "=" not in t and ("/" in t or "." in t)
        ]
        self._before = _snapshot(p for t in self._candidates for p in _expand(t, cwd))

    def outputs(self) -> list[Path]:
        after_paths = [p for t in self._candidates for p in _expand(t, self.cwd)]
        after = _snapshot(after_paths)
        inputs = {p.resolve() for p in self.inputs}
        return [p for p, state in after.items()
                if state is not None and state != self._before.get(p) and p.resolve() not in inputs]


async def trace_ffmpeg_result(session, workspace_dir: Path | str | None, trace: FfmpegTrace) -> None:
    """After a successful ffmpeg run: record its outputs' library sources."""
    try:
        outputs = await asyncio.to_thread(trace.outputs)
        if not outputs or not trace.inputs:
            return
        # ffmpeg calls run in gather(); the lookup owns its read transaction so
        # concurrent calls never share (and invalidate) the chat's session.
        from sqlalchemy.ext.asyncio import async_sessionmaker
        async with async_sessionmaker(session.bind, expire_on_commit=False)() as own:
            sources = await sources_for_files(own, workspace_dir, trace.inputs)
        await record_sources(workspace_dir, outputs, sources)
    except Exception as e:  # Lineage is a record, never a reason to fail the call.
        log.warning(f"[file-sources] ffmpeg trace failed: {e}")


# --- provenance for a saved file ---------------------------------------------

def _kind(fmt: str | None) -> str:
    fmt = (fmt or "").lower()
    if fmt in _VIDEO_FORMATS:
        return "video"
    if fmt in _AUDIO_FORMATS:
        return "audio"
    return "image"


def _trace_entry(media_id: int, gen: dict) -> dict[str, Any]:
    parameters = dict(gen.get("parameters") or {})
    if parameters.get("seed") is None and gen.get("seed") is not None:
        parameters["seed"] = gen["seed"]
    return {
        "media_id": media_id,
        "task_type": gen.get("task_type"),
        "tool_id": gen.get("tool_id"),
        "model": gen.get("model"),
        "generator": gen.get("generator"),
        "prompt": gen.get("prompt"),
        "negative_prompt": gen.get("negative_prompt"),
        "parameters": parameters,
        "generated_at": gen.get("generated_at"),
        "source_inputs": gen.get("source_inputs") if isinstance(gen.get("source_inputs"), list) else [],
        "seed": gen.get("seed"),
    }


async def build_edit_provenance(session, source_media_ids: list[int], *, output_format: str | None = None,
                                base: int | None = None) -> dict[str, Any]:
    """Provenance for a file made in agent code from library media.

    Made from one thing, it is an edit of it: the source's own history carries
    on as ``lineage_trace`` and reads as one line. Made from several, it is a
    new thing with those as its inputs (a video of two or more videos is a
    stitch of its clips): each input keeps its own history, none of it is this
    file's. ``base`` names the one input a several-source file is a changed
    version of, which makes it an edit of that one with the rest as inputs.
    """
    source_media_ids = list(dict.fromkeys(source_media_ids))
    provenance: dict[str, Any] = {"task_type": "agent_edit", "source_media_ids": source_media_ids}
    if not source_media_ids:
        return provenance
    result = await session.execute(select(MediaItem).where(MediaItem.id.in_(source_media_ids)))
    source_items = {item.id: item for item in result.scalars().all()}
    if not source_items:
        return provenance

    if len(source_media_ids) == 1:
        base = source_media_ids[0]
    elif base not in source_media_ids:
        base = None
    if base is not None and base != source_media_ids[0]:
        source_media_ids = [base, *(mid for mid in source_media_ids if mid != base)]
        provenance["source_media_ids"] = source_media_ids

    video_sources = [mid for mid in source_media_ids if mid in source_items and _kind(source_items[mid].file_format) == "video"]
    stitched = base is None and _kind(output_format) == "video" and len(video_sources) >= 2
    if stitched:
        provenance["task_type"] = "video-stitch"
    elif base is None:
        provenance["task_type"] = "agent_compose"

    lineage_trace: list[dict] = []
    base_item = source_items.get(base) if base is not None else None
    if base_item is not None:
        base_gen: dict = {}
        if base_item.generation_metadata:
            try:
                base_gen = json.loads(base_item.generation_metadata)
            except (TypeError, json.JSONDecodeError):
                pass
        lineage_trace = [e for e in (base_gen.get("lineage_trace") or []) if isinstance(e, dict) and e.get("media_id") != base]
        lineage_trace.append(_trace_entry(base, base_gen))
        # An edit carries its source's tool, for tool lineage propagation.
        if base_gen.get("tool_id"):
            provenance["tool_id"] = base_gen["tool_id"]
    provenance["lineage_trace"] = lineage_trace

    def role(mid: int) -> str:
        kind = _kind(source_items[mid].file_format)
        if kind == "video":
            return "clip" if stitched else "input_video"
        if kind == "audio":
            return "input_audio"
        return "source_image" if mid == base else "image"

    provenance["source_inputs"] = [
        {"media_id": mid, "role": role(mid), "file_path": source_items[mid].file_path}
        for mid in source_media_ids if mid in source_items
    ]
    return provenance


async def provenance_for_saved_file(session, workspace_dir: Path | str | None, path: Path,
                                    explicit: Sequence[int] | None = None,
                                    based_on: int | None = None) -> dict[str, Any] | None:
    """Provenance for ``library save`` of a workspace file: recorded sources plus
    any the caller declared (declared first). None when there are none."""
    recorded, recorded_base = await _saved_file_sources(session, workspace_dir, path)
    sources = _dedupe([*([based_on] if based_on is not None else []), *(explicit or []), *recorded])
    if not sources:
        return None
    fmt = Path(path).suffix.lstrip(".").lower()
    base = await build_edit_provenance(session, sources, output_format=fmt,
                                       base=based_on if based_on is not None else recorded_base)
    base.setdefault("tool_id", None)
    return {**base, "parameters": {}, "seed": None}
