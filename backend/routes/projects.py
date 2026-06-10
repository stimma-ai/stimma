"""Project routes."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_db_session
from database import Board, BoardSection, Chat, MediaItem, Project, ProjectMedia
from models.api_models import (
    ProjectCreateRequest,
    ProjectResponse,
    ProjectSummaryResponse,
    ProjectUpdateRequest,
)
from project_service import (
    attach_media_to_project,
    get_project_or_404,
    initialize_project_root,
    remove_media_from_project,
)
from utils.websocket import ws_manager

router = APIRouter(prefix="/api/projects", tags=["projects"])


async def _serialize_project(project: Project, session: AsyncSession) -> ProjectResponse:
    chat_count = await session.scalar(
        select(func.count()).select_from(Chat).where(
            Chat.project_id == project.id,
            Chat.deleted_at.is_(None),
        )
    )
    board_count = await session.scalar(
        select(func.count()).select_from(Board).where(
            Board.project_id == project.id,
            Board.deleted_at.is_(None),
        )
    )
    asset_count = await session.scalar(
        select(func.count()).select_from(ProjectMedia).where(ProjectMedia.project_id == project.id)
    )
    return ProjectResponse(
        **project.to_dict(),
        chat_count=chat_count or 0,
        board_count=board_count or 0,
        asset_count=asset_count or 0,
    )


@router.get("", response_model=list[ProjectSummaryResponse])
async def list_projects(session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(
        select(
            Project,
            func.count(func.distinct(Chat.id)).label("chat_count"),
            func.count(func.distinct(Board.id)).label("board_count"),
            func.count(func.distinct(ProjectMedia.media_id)).label("asset_count"),
        )
        .outerjoin(Chat, and_(Chat.project_id == Project.id, Chat.deleted_at.is_(None)))
        .outerjoin(Board, and_(Board.project_id == Project.id, Board.deleted_at.is_(None)))
        .outerjoin(ProjectMedia, ProjectMedia.project_id == Project.id)
        .where(Project.deleted_at.is_(None))
        .group_by(Project.id)
        .order_by(Project.updated_at.desc(), Project.id.desc())
    )
    return [
        ProjectSummaryResponse(
            **project.to_dict(),
            chat_count=chat_count or 0,
            board_count=board_count or 0,
            asset_count=asset_count or 0,
        )
        for project, chat_count, board_count, asset_count in result.all()
    ]


@router.post("", response_model=ProjectResponse)
async def create_project(
    request: ProjectCreateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    project = Project(
        name=(request.name or "").strip(),
        default_model_slug=request.default_model_slug,
    )
    session.add(project)
    await session.flush()
    await initialize_project_root(session, project)
    await session.commit()
    await session.refresh(project)

    from object_hash import salted_hash
    from telemetry import get_telemetry_client
    get_telemetry_client().track("project_created", {
        "projectHash": salted_hash(f"project:{project.id}"),
    }, category="organize")

    return await _serialize_project(project, session)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int, session: AsyncSession = Depends(get_db_session)):
    project = await get_project_or_404(session, project_id)
    return await _serialize_project(project, session)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    request: ProjectUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    project = await get_project_or_404(session, project_id)
    if request.name is not None:
        project.name = request.name.strip()
    if request.additional_instructions is not None:
        project.additional_instructions = request.additional_instructions
    if request.memory is not None:
        project.memory = request.memory
    if request.agent_tool_config is not None:
        import json
        project.agent_tool_config = json.dumps(request.agent_tool_config)
    if request.default_model_slug is not None:
        project.default_model_slug = request.default_model_slug
    project.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(project)
    result = await _serialize_project(project, session)
    await ws_manager.broadcast("project_updated", {"project": result.model_dump()})
    return result


@router.delete("/{project_id}")
async def delete_project(project_id: int, session: AsyncSession = Depends(get_db_session)):
    project = await get_project_or_404(session, project_id)
    deleted_at = datetime.utcnow()

    chat_result = await session.execute(
        select(Chat.id).where(Chat.project_id == project_id, Chat.deleted_at.is_(None))
    )
    deleted_chat_ids = [row[0] for row in chat_result.all()]
    if deleted_chat_ids:
        await session.execute(
            update(Chat)
            .where(Chat.id.in_(deleted_chat_ids))
            .values(deleted_at=deleted_at)
        )

    board_result = await session.execute(
        select(Board.id).where(Board.project_id == project_id, Board.deleted_at.is_(None))
    )
    deleted_board_ids = [row[0] for row in board_result.all()]
    if deleted_board_ids:
        await session.execute(
            update(Board)
            .where(Board.id.in_(deleted_board_ids))
            .values(deleted_at=deleted_at, updated_at=deleted_at)
        )
        await session.execute(
            delete(BoardSection).where(BoardSection.board_id.in_(deleted_board_ids))
        )

    # Remove project_media edges (assets stay in library)
    await session.execute(
        delete(ProjectMedia).where(ProjectMedia.project_id == project_id)
    )

    project.deleted_at = deleted_at
    project.updated_at = deleted_at
    await session.commit()

    for chat_id in deleted_chat_ids:
        await ws_manager.broadcast("chat_deleted", {"chat_id": chat_id})
    for board_id in deleted_board_ids:
        await ws_manager.broadcast("board_deleted", {"board_id": board_id})

    from object_hash import salted_hash
    from telemetry import get_telemetry_client
    get_telemetry_client().track("project_deleted", {
        "projectHash": salted_hash(f"project:{project_id}"),
    }, category="organize")

    return {"status": "success"}


class _ProjectMediaRequest(BaseModel):
    media_ids: list[int]


@router.post("/{project_id}/assets")
async def add_media_to_project(
    project_id: int,
    request: _ProjectMediaRequest,
    session: AsyncSession = Depends(get_db_session),
):
    await get_project_or_404(session, project_id)
    result = await session.execute(
        select(MediaItem.id).where(
            MediaItem.id.in_(request.media_ids),
            MediaItem.deleted_at.is_(None),
        )
    )
    valid_ids = [row[0] for row in result.all()]
    for media_id in valid_ids:
        await attach_media_to_project(session, project_id, media_id)
    await session.commit()
    return {"status": "success", "added": len(valid_ids)}


@router.delete("/{project_id}/assets/{media_id}")
async def remove_project_media(
    project_id: int,
    media_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    await get_project_or_404(session, project_id)
    removed = await remove_media_from_project(session, project_id, media_id)
    await session.commit()
    if not removed:
        raise HTTPException(status_code=404, detail="Asset not in project")
    return {"status": "success"}
