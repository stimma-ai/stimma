"""Recipe DB helpers. Thin wrappers around the main Recipe table."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Recipe


async def get_recipe_or_404(session: AsyncSession, recipe_id: int) -> Recipe:
    result = await session.execute(
        select(Recipe).where(Recipe.id == recipe_id, Recipe.deleted_at.is_(None))
    )
    recipe = result.scalar_one_or_none()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


async def get_recipe_including_deleted(session: AsyncSession, recipe_id: int) -> Optional[Recipe]:
    result = await session.execute(select(Recipe).where(Recipe.id == recipe_id))
    return result.scalar_one_or_none()
