"""Shared helpers for browse similarity filters."""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

import numpy as np
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import Face, MediaItem


DEFAULT_FACE_SIMILARITY_THRESHOLD = 0.65


def parse_similarity_ids(raw_ids: str, field_name: str, max_ids: int = 3) -> list[int]:
    """Parse a comma-separated list of media IDs for similarity filters."""
    try:
        ids = [int(id_str.strip()) for id_str in raw_ids.split(",") if id_str.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_name} must contain only numeric asset IDs")

    if not ids:
        raise HTTPException(status_code=400, detail=f"No valid asset IDs provided for {field_name}")

    if len(ids) > max_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {max_ids} reference IDs allowed for similarity search",
        )

    return ids


def cosine_similarity(embedding_a: np.ndarray, embedding_b: np.ndarray) -> float:
    """Compute cosine similarity defensively, even if stored vectors are not normalized."""
    norm_a = np.linalg.norm(embedding_a)
    norm_b = np.linalg.norm(embedding_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(embedding_a / norm_a, embedding_b / norm_b))


def sort_similarity_items(
    items: list[MediaItem],
    similarity_scores: dict[int, float],
    sort_by: str,
    random_seed: int | None = None,
) -> None:
    """Sort in-place using the same fallback order as browse similarity routes."""
    if sort_by == "similarity":
        items.sort(key=lambda x: similarity_scores[x.id], reverse=True)
    elif sort_by == "created_desc":
        items.sort(key=lambda x: x.created_date if x.created_date else datetime.min, reverse=True)
    elif sort_by == "created_asc":
        items.sort(key=lambda x: x.created_date if x.created_date else datetime.min, reverse=False)
    elif sort_by == "indexed_desc":
        items.sort(key=lambda x: x.indexed_date, reverse=True)
    elif sort_by == "indexed_asc":
        items.sort(key=lambda x: x.indexed_date, reverse=False)
    elif sort_by == "random" and random_seed is not None:
        import random as py_random

        py_random.Random(random_seed).shuffle(items)


async def get_reference_face_embeddings(
    session: AsyncSession,
    reference_ids: Sequence[int],
) -> list[np.ndarray]:
    """Load every face embedding from the reference media IDs."""
    result = await session.execute(select(MediaItem.id).where(MediaItem.id.in_(reference_ids)))
    found_ids = {row[0] for row in result.all()}
    missing_ids = [media_id for media_id in reference_ids if media_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail="One or more reference assets not found")

    result = await session.execute(
        select(Face)
        .where(Face.media_id.in_(reference_ids))
        .where(Face.auraface_embedding.isnot(None))
    )
    faces = result.scalars().all()

    media_ids_with_faces = {face.media_id for face in faces}
    missing_face_ids = [media_id for media_id in reference_ids if media_id not in media_ids_with_faces]
    if missing_face_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Reference assets {missing_face_ids} have no face embeddings",
        )

    embeddings = [face.get_embedding() for face in faces]
    return [embedding for embedding in embeddings if embedding is not None]


async def filter_items_by_face_similarity(
    session: AsyncSession,
    items: Sequence[MediaItem],
    reference_ids: Sequence[int],
    similarity_threshold: float | None = None,
) -> tuple[list[MediaItem], dict[int, float]]:
    """
    Filter media items by face similarity.

    An image can contain multiple faces, so each candidate item receives the best
    cosine score across all reference face embeddings and all candidate faces.
    """
    threshold = (
        similarity_threshold
        if similarity_threshold is not None
        else getattr(get_settings().face_detection, "similarity_threshold", DEFAULT_FACE_SIMILARITY_THRESHOLD)
    )
    reference_embeddings = await get_reference_face_embeddings(session, reference_ids)
    if not reference_embeddings:
        raise HTTPException(status_code=400, detail="No valid reference face embeddings found")

    item_ids = [item.id for item in items]
    if not item_ids:
        return [], {}

    result = await session.execute(
        select(Face)
        .where(Face.media_id.in_(item_ids))
        .where(Face.auraface_embedding.isnot(None))
    )
    candidate_faces = result.scalars().all()

    faces_by_media_id: dict[int, list[np.ndarray]] = {}
    for face in candidate_faces:
        embedding = face.get_embedding()
        if embedding is None:
            continue
        faces_by_media_id.setdefault(face.media_id, []).append(embedding)

    reference_id_set = set(reference_ids)
    filtered_items: list[MediaItem] = []
    similarity_scores: dict[int, float] = {}

    for item in items:
        candidate_embeddings = faces_by_media_id.get(item.id, [])
        best_similarity = None
        for candidate_embedding in candidate_embeddings:
            for reference_embedding in reference_embeddings:
                similarity = cosine_similarity(reference_embedding, candidate_embedding)
                if best_similarity is None or similarity > best_similarity:
                    best_similarity = similarity

        if best_similarity is None:
            continue

        if item.id in reference_id_set or best_similarity >= threshold:
            similarity_scores[item.id] = float(best_similarity)
            filtered_items.append(item)

    return filtered_items, similarity_scores


async def filter_media_query_by_face_similarity(
    session: AsyncSession,
    query,
    reference_ids: Sequence[int],
    similarity_threshold: float | None = None,
) -> tuple[list[MediaItem], dict[int, float]]:
    result = await session.execute(query)
    items = result.scalars().all()
    return await filter_items_by_face_similarity(session, items, reference_ids, similarity_threshold)
