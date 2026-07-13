"""Managed mutable state for non-destructive editors."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app_dirs
from database import ManagedArtifact, WorkingDocument


MAX_AUTOSAVE_GENERATIONS = 3


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


async def save_working_document_state(
    session: AsyncSession,
    *,
    document: WorkingDocument,
    profile_id: str,
    project: Any,
) -> str:
    """Write a new generation, index it, and prune bounded old generations."""
    next_generation = document.generation + 1
    path = (
        app_dirs.get_profile_dir(profile_id)
        / "editor_documents"
        / str(document.id)
        / f"generation-{next_generation}.json"
    )
    await asyncio.to_thread(_write_json_atomic, path, project)
    artifact = ManagedArtifact(
        owner_kind="working_document",
        owner_id=str(document.id),
        artifact_kind="editor_state",
        locator=str(path),
        state="available",
    )
    session.add(artifact)
    document.state_locator = str(path)
    document.generation = next_generation
    document.updated_at = datetime.utcnow()
    await session.flush()

    artifacts = list(
        await session.scalars(
            select(ManagedArtifact)
            .where(
                ManagedArtifact.owner_kind == "working_document",
                ManagedArtifact.owner_id == str(document.id),
                ManagedArtifact.artifact_kind == "editor_state",
                ManagedArtifact.deleted_at.is_(None),
            )
            .order_by(ManagedArtifact.id.desc())
        )
    )
    for old in artifacts[MAX_AUTOSAVE_GENERATIONS:]:
        try:
            await asyncio.to_thread(Path(old.locator).unlink, missing_ok=True)
        except OSError:
            continue
        await session.delete(old)
    await session.flush()
    return str(path)


async def load_working_document_state(document: WorkingDocument) -> Any:
    if not document.state_locator:
        raise FileNotFoundError("Working document has no saved state")
    path = Path(document.state_locator)
    return await asyncio.to_thread(lambda: json.loads(path.read_text(encoding="utf-8")))
