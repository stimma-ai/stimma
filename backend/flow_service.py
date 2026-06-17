"""Flow DB helpers. Thin wrappers around the main Flow table."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Flow


async def get_flow_or_404(session: AsyncSession, flow_id: int) -> Flow:
    result = await session.execute(
        select(Flow).where(Flow.id == flow_id, Flow.deleted_at.is_(None))
    )
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow


async def get_flow_including_deleted(session: AsyncSession, flow_id: int) -> Optional[Flow]:
    result = await session.execute(select(Flow).where(Flow.id == flow_id))
    return result.scalar_one_or_none()
