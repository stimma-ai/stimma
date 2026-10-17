"""Face and CLIP similarity for the run_code ``stimma`` SDK.

Library media reads the embeddings background indexing already stored; only
workspace files and text are embedded live, and never written to the library.
Every query uses a fresh short-lived session so polling sees the indexer's
commits and the run's own session transaction is left alone.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.logging import get_logger
from database import Face, MediaItem

if TYPE_CHECKING:
    from .code_runtime import StimmaSDK

log = get_logger(__name__)

# Seconds between status checks while waiting on background indexing.
POLL_INTERVAL = 0.5
# Upper bound on pairwise_similarity targets (N×N comparisons, live embeds).
MAX_PAIRWISE_TARGETS = 64
MAX_SEARCH_LIMIT = 500

_IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif",
}
_PHASES = {
    "face": ("face_detection_status", "face detection"),
    "clip": ("clip_status", "image embedding"),
}


@dataclass
class _Ref:
    kind: str  # media | face | path | text
    media_id: int | None = None
    face_id: int | None = None
    path: Path | None = None
    label: str | None = None  # the path as the caller wrote it
    text: str | None = None

    def describe(self) -> dict[str, Any]:
        if self.kind == "media":
            return {"media_id": self.media_id}
        if self.kind == "face":
            return {"face_id": self.face_id}
        if self.kind == "path":
            return {"path": self.label}
        return {"text": self.text}

    def name(self) -> str:
        if self.kind == "media":
            return f"media {self.media_id}"
        if self.kind == "face":
            return f"face {self.face_id}"
        if self.kind == "path":
            return repr(self.label)
        return f"text {self.text!r}"


def _sessions(sdk: "StimmaSDK"):
    return async_sessionmaker(sdk.session.bind, expire_on_commit=False)


def _workspace_file(sdk: "StimmaSDK", value: str | os.PathLike) -> _Ref:
    from .code_runtime import _make_workspace_resolver

    label = os.fspath(value)
    resolved = _make_workspace_resolver(
        sdk.workspace_dir, sdk.project_workspace_dir, read_only=True
    )(label)
    if not resolved.is_file():
        raise FileNotFoundError(f"No workspace file {label!r}")
    return _Ref("path", path=resolved, label=label)


def _looks_like_path(sdk: "StimmaSDK", value: str) -> bool:
    if "/" in value or "\\" in value or Path(value).suffix.lower() in _IMAGE_SUFFIXES:
        return True
    try:
        return (sdk.workspace_dir / value).is_file()
    except (OSError, ValueError):
        return False


def _parse_ref(sdk: "StimmaSDK", value: Any, *, kind: str) -> _Ref:
    """Classify a caller's reference. ``kind`` is "face" or "clip"."""
    if isinstance(value, bool):
        raise TypeError("Expected a media id, face, workspace path or text, got a bool")
    if isinstance(value, (int, np.integer)):
        return _Ref("media", media_id=int(value))
    if isinstance(value, Mapping):
        face_id = value.get("face_id")
        if face_id is None and "id" in value and "bbox" in value:
            face_id = value["id"]  # an entry from detect_faces
        if face_id is not None and kind == "face":
            return _Ref("face", face_id=int(face_id))
        if value.get("media_id") is not None:
            return _Ref("media", media_id=int(value["media_id"]))
        if value.get("path") is not None:
            return _workspace_file(sdk, value["path"])
        if value.get("text") is not None and kind == "clip":
            return _parse_text(value["text"])
        if face_id is not None:
            raise ValueError(
                "CLIP compares whole images; pass the face's media_id or a cropped workspace image"
            )
        raise ValueError(
            f"Can't tell what a dict with keys {sorted(value)} refers to; "
            "expected media_id, face_id, path or text"
        )
    if isinstance(value, os.PathLike):
        return _workspace_file(sdk, value)
    path_attr = getattr(value, "path", None)
    if isinstance(path_attr, (str, os.PathLike)):  # a ToolResult
        return _workspace_file(sdk, path_attr)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return _Ref("media", media_id=int(stripped))
        if kind == "face" or _looks_like_path(sdk, stripped):
            return _workspace_file(sdk, stripped)
        return _parse_text(stripped)
    raise TypeError(
        f"Expected a media id, face, workspace path or text, got {type(value).__name__}"
    )


def _parse_text(text: Any) -> _Ref:
    text = str(text).strip()
    if not text:
        raise ValueError("Text to embed is empty")
    return _Ref("text", text=text)


def _wake_indexer() -> None:
    try:
        from core.app import get_process_pending_event
        event = get_process_pending_event()
        if event is not None:
            event.set()
    except Exception as exc:  # waking is best effort; polling still works
        log.debug(f"Could not wake background indexing: {exc}")


async def _wait_until_indexed(
    sdk: "StimmaSDK", media_id: int, phase: str, *, wait: bool, timeout: float
) -> str:
    """Block until ``phase`` is done for the media; return its final status.

    Raises when the item can never be indexed, indexing failed, or the wait
    timed out. Returns "completed" or "skipped" (not an image or video).
    """
    column_name, label = _PHASES[phase]
    column = getattr(MediaItem, column_name)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, float(timeout))
    woke = False
    while True:
        async with _sessions(sdk)() as session:
            row = (await session.execute(
                select(column, MediaItem.ephemeral_run_id, MediaItem.deleted_at)
                .where(MediaItem.id == media_id)
            )).first()
        if row is None:
            raise ValueError(f"Media item {media_id} not found")
        status, ephemeral_run_id, deleted_at = row
        if status in ("completed", "skipped"):
            return status
        if status == "failed":
            raise RuntimeError(f"{label.capitalize()} failed for media {media_id}.")
        if ephemeral_run_id is not None or deleted_at is not None:
            raise ValueError(
                f"Media {media_id} is not indexed by the library (it is a run intermediate "
                "or deleted). Pass its workspace file path to embed it directly."
            )
        if not wait:
            raise RuntimeError(
                f"{label.capitalize()} is still pending for media {media_id}. "
                "Try again shortly, or pass wait=True."
            )
        if not woke:
            _wake_indexer()
            woke = True
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(
                f"{label.capitalize()} for media {media_id} is still queued after "
                f"{timeout:g}s. Pass a longer timeout, or copy it into the workspace with "
                f"await stimma.library.get({media_id}) and pass the file path to embed it now."
            )
        await asyncio.sleep(min(POLL_INTERVAL, remaining))


# ── Faces ────────────────────────────────────────────────────────────────


def _face_entry(face: Face) -> dict[str, Any]:
    return {
        "bbox": {
            "x": face.bbox_x, "y": face.bbox_y,
            "width": face.bbox_width, "height": face.bbox_height,
        },
        "area": float(face.bbox_width * face.bbox_height),
    }


async def detect_faces(
    sdk: "StimmaSDK", media_id: int, *, wait: bool = True, timeout: float = 60
) -> list[dict[str, Any]]:
    status = await _wait_until_indexed(sdk, media_id, "face", wait=wait, timeout=timeout)
    if status == "skipped":
        return []
    async with _sessions(sdk)() as session:
        faces = (await session.execute(
            select(Face).where(Face.media_id == media_id).order_by(Face.confidence.desc())
        )).scalars().all()
    out = []
    for face in faces:
        embedding = face.get_embedding()
        out.append({
            "id": face.id,
            **_face_entry(face),
            "confidence": face.confidence,
            "embedding": embedding.tolist() if embedding is not None else None,
        })
    return out


@dataclass
class _FaceVector:
    vector: np.ndarray | None
    info: dict[str, Any]  # reference description, plus face_id/bbox/area or error


async def _face_vector(sdk: "StimmaSDK", ref: _Ref, *, timeout: float) -> _FaceVector:
    info = ref.describe()
    if ref.kind == "path":
        from face_detection_service import get_face_detection_service

        service = get_face_detection_service()
        detected = await asyncio.to_thread(service.detect_faces, ref.path)
        detected = [f for f in detected if f.get("embedding") is not None]
        if not detected:
            return _FaceVector(None, {**info, "error": f"No face found in {ref.name()}."})
        largest = max(detected, key=lambda f: f["bbox"]["width"] * f["bbox"]["height"])
        bbox = {k: float(v) for k, v in largest["bbox"].items()}
        return _FaceVector(
            np.asarray(largest["embedding"], dtype=np.float32),
            {**info, "bbox": bbox, "area": bbox["width"] * bbox["height"]},
        )

    if ref.kind == "face":
        async with _sessions(sdk)() as session:
            face = await session.get(Face, ref.face_id)
        if face is None:
            raise ValueError(f"Face {ref.face_id} not found")
        embedding = face.get_embedding()
        info = {"media_id": face.media_id, "face_id": face.id, **_face_entry(face)}
        if embedding is None:
            return _FaceVector(None, {**info, "error": f"Face {face.id} has no identity embedding."})
        return _FaceVector(embedding, info)

    status = await _wait_until_indexed(sdk, ref.media_id, "face", wait=True, timeout=timeout)
    if status == "skipped":
        return _FaceVector(None, {**info, "error": f"Media {ref.media_id} is not an image or video."})
    async with _sessions(sdk)() as session:
        faces = (await session.execute(
            select(Face).where(Face.media_id == ref.media_id, Face.auraface_embedding.isnot(None))
        )).scalars().all()
    if not faces:
        return _FaceVector(None, {**info, "error": f"No face found in {ref.name()}."})
    largest = max(faces, key=lambda f: f.bbox_width * f.bbox_height)
    return _FaceVector(largest.get_embedding(), {**info, "face_id": largest.id, **_face_entry(largest)})


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    from utils.similarity import cosine_similarity
    return round(cosine_similarity(a, b), 4)


async def face_similarity(sdk: "StimmaSDK", a: Any, b: Any, *, timeout: float = 60) -> dict[str, Any]:
    fa = await _face_vector(sdk, _parse_ref(sdk, a, kind="face"), timeout=timeout)
    fb = await _face_vector(sdk, _parse_ref(sdk, b, kind="face"), timeout=timeout)
    result: dict[str, Any] = {"similarity": None, "a": fa.info, "b": fb.info}
    errors = [f.info["error"] for f in (fa, fb) if f.vector is None]
    if errors:
        result["error"] = " ".join(errors)
    else:
        result["similarity"] = _cosine(fa.vector, fb.vector)
    return result


def _check_limit(limit: int) -> int:
    limit = int(limit)
    if not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}")
    return limit


def _population():
    from routes.media import similarity_search_population
    return similarity_search_population()


def _unit_rows(blobs: Sequence[bytes], dim: int) -> tuple[np.ndarray, list[int]]:
    """Stack float32 blobs of length ``dim`` into unit rows; return (matrix, kept indexes)."""
    kept = [i for i, blob in enumerate(blobs) if len(blob) == dim * 4]
    if not kept:
        return np.zeros((0, dim), dtype=np.float32), []
    matrix = np.frombuffer(b"".join(blobs[i] for i in kept), dtype=np.float32).reshape(len(kept), dim)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms, kept


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


async def find_faces_like(
    sdk: "StimmaSDK", ref: Any, *, limit: int = 50, min_similarity: float | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    from config import get_settings
    from utils.similarity import DEFAULT_FACE_SIMILARITY_THRESHOLD

    limit = _check_limit(limit)
    threshold = float(min_similarity) if min_similarity is not None else getattr(
        get_settings().face_detection, "similarity_threshold", DEFAULT_FACE_SIMILARITY_THRESHOLD
    )
    reference = await _face_vector(sdk, _parse_ref(sdk, ref, kind="face"), timeout=timeout)
    result: dict[str, Any] = {"reference": reference.info, "min_similarity": threshold, "matches": []}
    if reference.vector is None:
        result["error"] = reference.info["error"]
        return result

    exclude_media = reference.info.get("media_id")
    async with _sessions(sdk)() as session:
        rows = (await session.execute(
            select(
                Face.id, Face.media_id, Face.bbox_x, Face.bbox_y, Face.bbox_width,
                Face.bbox_height, Face.auraface_embedding,
            )
            .join(MediaItem, MediaItem.id == Face.media_id)
            .where(Face.auraface_embedding.isnot(None), *_population())
        )).all()
    rows = [r for r in rows if r.media_id != exclude_media]
    matrix, kept = _unit_rows([r.auraface_embedding for r in rows], reference.vector.shape[0])
    scores = matrix @ _unit(reference.vector) if kept else np.zeros(0)

    best: dict[int, tuple[float, Any]] = {}
    for score, index in zip(scores.tolist(), kept):
        row = rows[index]
        if row.media_id not in best or score > best[row.media_id][0]:
            best[row.media_id] = (score, row)
    ranked = sorted(
        (item for item in best.values() if item[0] >= threshold), key=lambda item: -item[0]
    )
    result["total_compared"] = len(best)
    result["matches"] = [
        {
            "media_id": row.media_id,
            "face_id": row.id,
            "similarity": round(score, 4),
            "bbox": {"x": row.bbox_x, "y": row.bbox_y, "width": row.bbox_width, "height": row.bbox_height},
            "area": float(row.bbox_width * row.bbox_height),
        }
        for score, row in ranked[:limit]
    ]
    return result


# ── CLIP ─────────────────────────────────────────────────────────────────


async def _reschedule_clip(sdk: "StimmaSDK", media_ids: list[int]) -> None:
    """Clear embeddings from an older model so indexing recomputes them."""
    if not media_ids:
        return
    async with _sessions(sdk)() as session:
        await session.execute(
            update(MediaItem).where(MediaItem.id.in_(media_ids))
            .values(clip_embedding=None, clip_status="pending")
        )
        await session.commit()
    log.info(f"Rescheduled {len(media_ids)} stale CLIP embeddings for re-indexing")
    _wake_indexer()


async def _clip_vector(sdk: "StimmaSDK", ref: _Ref, *, timeout: float) -> np.ndarray:
    from clip_service import CLIP_EMBEDDING_DIM, get_clip_service

    if ref.kind == "path":
        return await asyncio.to_thread(get_clip_service().encode_image, ref.path)
    if ref.kind == "text":
        return await asyncio.to_thread(get_clip_service().encode_text, ref.text)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, float(timeout))
    while True:
        remaining = max(0.0, deadline - loop.time())
        status = await _wait_until_indexed(sdk, ref.media_id, "clip", wait=True, timeout=remaining)
        if status == "skipped":
            raise ValueError(f"Media {ref.media_id} is not an image or video, so it has no CLIP embedding.")
        async with _sessions(sdk)() as session:
            blob = (await session.execute(
                select(MediaItem.clip_embedding).where(MediaItem.id == ref.media_id)
            )).scalar_one_or_none()
        if blob is not None and len(blob) == CLIP_EMBEDDING_DIM * 4:
            return np.frombuffer(blob, dtype=np.float32)
        # Missing or from an older model: recompute in the background and wait.
        await _reschedule_clip(sdk, [ref.media_id])


def _clip_ref(sdk: "StimmaSDK", value: Any) -> _Ref:
    return _parse_ref(sdk, value, kind="clip")


async def clip_embedding(sdk: "StimmaSDK", target: Any, *, timeout: float = 60) -> dict[str, Any]:
    from clip_service import CLIP_MODEL_VERSION

    ref = _clip_ref(sdk, target)
    vector = await _clip_vector(sdk, ref, timeout=timeout)
    return {
        **ref.describe(),
        "embedding": [float(x) for x in vector],
        "dim": int(vector.shape[0]),
        "model": CLIP_MODEL_VERSION,
    }


async def clip_similarity(sdk: "StimmaSDK", a: Any, b: Any, *, timeout: float = 60) -> dict[str, Any]:
    ra, rb = _clip_ref(sdk, a), _clip_ref(sdk, b)
    va = await _clip_vector(sdk, ra, timeout=timeout)
    vb = await _clip_vector(sdk, rb, timeout=timeout)
    return {"similarity": _cosine(va, vb), "a": ra.describe(), "b": rb.describe()}


async def find_similar(
    sdk: "StimmaSDK", ref: Any, *, limit: int = 50, min_similarity: float | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    from clip_service import CLIP_EMBEDDING_DIM
    from config import get_settings

    limit = _check_limit(limit)
    parsed = _clip_ref(sdk, ref)
    settings = get_settings()
    if min_similarity is not None:
        threshold = float(min_similarity)
    elif parsed.kind == "text":
        threshold = settings.clip_text_similarity_threshold
    else:
        threshold = settings.clip_similarity_threshold
    query = _unit(await _clip_vector(sdk, parsed, timeout=timeout))

    async with _sessions(sdk)() as session:
        rows = (await session.execute(
            select(MediaItem.id, MediaItem.clip_embedding)
            .where(MediaItem.clip_embedding.isnot(None), *_population())
        )).all()
    rows = [r for r in rows if r.id != parsed.media_id]
    matrix, kept = _unit_rows([r.clip_embedding for r in rows], CLIP_EMBEDDING_DIM)
    kept_set = set(kept)
    stale = [r.id for i, r in enumerate(rows) if i not in kept_set]
    if stale:
        await _reschedule_clip(sdk, stale)
    scores = matrix @ query if kept else np.zeros(0)
    ranked = sorted(
        ((score, rows[i].id) for score, i in zip(scores.tolist(), kept) if score >= threshold),
        key=lambda item: -item[0],
    )
    return {
        "reference": parsed.describe(),
        "min_similarity": threshold,
        "total_compared": len(kept),
        "matches": [
            {"media_id": media_id, "similarity": round(score, 4)}
            for score, media_id in ranked[:limit]
        ],
    }


# ── Pairwise ─────────────────────────────────────────────────────────────


async def pairwise_similarity(
    sdk: "StimmaSDK", targets: Sequence[Any], *, kind: str = "clip", timeout: float = 60
) -> dict[str, Any]:
    if kind not in ("clip", "face"):
        raise ValueError('kind must be "clip" or "face"')
    targets = [targets] if isinstance(targets, (str, bytes, Mapping)) else list(targets)
    if not 1 <= len(targets) <= MAX_PAIRWISE_TARGETS:
        raise ValueError(
            f"pairwise_similarity takes 1 to {MAX_PAIRWISE_TARGETS} targets, got {len(targets)}. "
            "For a library-wide search use find_similar or find_faces_like."
        )

    vectors: list[np.ndarray | None] = []
    infos: list[dict[str, Any]] = []
    for target in targets:
        if kind == "face":
            face = await _face_vector(sdk, _parse_ref(sdk, target, kind="face"), timeout=timeout)
            vectors.append(face.vector)
            infos.append(face.info)
        else:
            ref = _clip_ref(sdk, target)
            vectors.append(await _clip_vector(sdk, ref, timeout=timeout))
            infos.append(ref.describe())

    n = len(vectors)
    present = [i for i, v in enumerate(vectors) if v is not None]
    matrix: list[list[float | None]] = [[None] * n for _ in range(n)]
    if present:
        dims = {vectors[i].shape[0] for i in present}
        if len(dims) > 1:
            raise ValueError("Targets produced embeddings of different sizes and can't be compared")
        stacked = np.stack([_unit(vectors[i]) for i in present])
        scores = np.clip(stacked @ stacked.T, -1.0, 1.0)
        for row, i in enumerate(present):
            for col, j in enumerate(present):
                matrix[i][j] = round(float(scores[row, col]), 4)
    return {"kind": kind, "targets": infos, "matrix": matrix}
