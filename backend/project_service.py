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


async def is_live_project(session: AsyncSession, project_id: Optional[int]) -> bool:
    if project_id is None:
        return False
    project = await session.get(Project, project_id)
    return project is not None and project.deleted_at is None


async def live_project_ids_for_asset(session: AsyncSession, asset_id: int) -> list[int]:
    """Projects (not deleted) the Asset currently belongs to."""
    from database import ProjectAsset

    rows = await session.scalars(
        select(ProjectAsset.project_id)
        .join(Project, Project.id == ProjectAsset.project_id)
        .where(
            ProjectAsset.asset_id == asset_id,
            ProjectAsset.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        )
        .order_by(ProjectAsset.project_id)
    )
    return list(dict.fromkeys(rows))


async def live_project_ids_for_media(session: AsyncSession, media_id: int) -> list[int]:
    from asset_association_service import asset_for_media

    asset = await asset_for_media(session, media_id)
    if asset is None:
        return []
    return await live_project_ids_for_asset(session, asset.id)


async def attach_media_to_project(
    session: AsyncSession, project_id: Optional[int], media_id: int
) -> None:
    """Put newly created (or newly promoted) media into a project.

    This is the one call every creation path should make when it knows the
    project context. It attaches canonically when the media already backs an
    Asset, and otherwise stages the intent so promotion attaches it later.
    ``None`` and deleted projects are a no-op, so callers can pass the
    context through unconditionally.
    """
    if project_id is None or not await is_live_project(session, project_id):
        return
    from asset_association_service import asset_for_media, attach_asset_to_project

    asset = await asset_for_media(session, media_id)
    if asset is not None:
        await attach_asset_to_project(session, project_id, asset.id)
        # Consume any staging edge left by an earlier step/build.
        staged = await session.scalar(
            select(ProjectMedia).where(
                ProjectMedia.project_id == project_id,
                ProjectMedia.media_id == media_id,
            )
        )
        if staged is not None:
            await session.delete(staged)
        await session.flush()
        return

    # Some generation pipelines know project context before disposition. Keep
    # that intent only as a temporary edge; promotion consumes it into
    # ProjectAsset. It is never used by project browsers or counts.
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


async def attach_media_to_projects(
    session: AsyncSession, project_ids, media_id: int
) -> None:
    for project_id in dict.fromkeys(pid for pid in project_ids if pid is not None):
        await attach_media_to_project(session, project_id, media_id)


async def current_media_ids_for_assets(session: AsyncSession, asset_ids) -> list[int]:
    from database import Asset, AssetRevision

    ids = [a for a in dict.fromkeys(asset_ids) if a is not None]
    if not ids:
        return []
    rows = await session.scalars(
        select(AssetRevision.primary_media_id)
        .join(Asset, Asset.current_revision_id == AssetRevision.id)
        .where(Asset.id.in_(ids))
    )
    return [m for m in rows if m is not None]


async def broadcast_project_assets_changed_for_assets(
    session: AsyncSession,
    project_id: int,
    asset_ids,
    *,
    action: str,
) -> None:
    asset_ids = list(dict.fromkeys(a for a in asset_ids if a is not None))
    if not asset_ids:
        return
    media_ids = await current_media_ids_for_assets(session, asset_ids)
    await broadcast_project_assets_changed(
        project_id, asset_ids=asset_ids, media_ids=media_ids, action=action
    )


async def broadcast_project_assets_changed(
    project_id: int,
    *,
    asset_ids=(),
    media_ids=(),
    action: str,
) -> None:
    """Tell clients a project's membership changed ("added" or "removed")."""
    asset_ids = [int(a) for a in dict.fromkeys(asset_ids) if a is not None]
    media_ids = [int(m) for m in dict.fromkeys(media_ids) if m is not None]
    if not asset_ids and not media_ids:
        return
    from utils.websocket import ws_manager

    try:
        await ws_manager.broadcast(
            "project_assets_changed",
            {
                "project_id": project_id,
                "asset_ids": asset_ids,
                "media_ids": media_ids,
                "action": action,
            },
        )
    except Exception as exc:  # pragma: no cover - broadcast is best effort
        log.warning(f"project_assets_changed broadcast failed: {type(exc).__name__}")


async def remove_media_from_project(session: AsyncSession, project_id: int, media_id: int) -> bool:
    from asset_association_service import asset_for_media, detach_asset_from_project

    asset = await asset_for_media(session, media_id)
    if asset is not None:
        return await detach_asset_from_project(session, project_id, asset.id)

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



PROJECT_NONE = "none"


def parse_project_filter(value) -> int | str | None:
    """Parse a list endpoint's ``project_id`` query value.

    Returns ``None`` when absent, ``"none"`` for items with no project, or the
    project id. Anything else is a 422.
    """
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    if text in (PROJECT_NONE, "null"):
        return PROJECT_NONE
    try:
        return int(text)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422, detail="project_id must be a project id or 'none'"
        )
