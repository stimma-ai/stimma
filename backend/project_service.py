"""Project path and membership helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app_dirs import get_data_dir
from core.logging import get_logger
from database import Project, ProjectMedia

log = get_logger(__name__)


def get_projects_root() -> Path:
    root = get_data_dir() / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_project_root(project_id: int) -> Path:
    return get_projects_root() / str(project_id)


def get_project_workspace_dir(project_id: int) -> Path:
    path = get_project_root(project_id) / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_project_chat_workspace_dir(project_id: int, chat_id: int) -> Path:
    path = get_project_root(project_id) / "chats" / str(chat_id) / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def infer_project_id_from_workspace_path(workspace_dir: Path | str | None) -> Optional[int]:
    if workspace_dir is None:
        return None
    path = Path(workspace_dir).resolve()
    parts = list(path.parts)
    try:
        projects_index = parts.index("projects")
        return int(parts[projects_index + 1])
    except (ValueError, IndexError):
        return None


def ensure_project_directories(project_id: int) -> Path:
    root = get_project_root(project_id)
    get_project_workspace_dir(project_id)
    return root


async def initialize_project_root(session: AsyncSession, project: Project) -> Project:
    """Ensure the on-disk project root exists and root_path is stored."""
    root = ensure_project_directories(project.id)
    project.root_path = str(root)
    await session.flush()
    return project


async def attach_media_to_project(session: AsyncSession, project_id: int, media_id: int) -> None:
    existing = await session.execute(
        select(ProjectMedia).where(
            ProjectMedia.project_id == project_id,
            ProjectMedia.media_id == media_id,
        )
    )
    if existing.scalar_one_or_none():
        return
    session.add(ProjectMedia(project_id=project_id, media_id=media_id))
    await session.flush()


async def remove_media_from_project(session: AsyncSession, project_id: int, media_id: int) -> bool:
    existing = await session.execute(
        select(ProjectMedia).where(
            ProjectMedia.project_id == project_id,
            ProjectMedia.media_id == media_id,
        )
    )
    row = existing.scalar_one_or_none()
    if not row:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def get_project_or_404(session: AsyncSession, project_id: int) -> Project:
    result = await session.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    project = result.scalar_one_or_none()
    if not project:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Project not found")
    return project


