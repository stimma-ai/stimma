"""User preferences routes."""
import json
from datetime import datetime
from fastapi import APIRouter, HTTPException, Body, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import UserPreference
from core.dependencies import get_db_session

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


@router.get("/{key}")
async def get_preference(key: str, session: AsyncSession = Depends(get_db_session)):
    """Get a user preference by key."""
    result = await session.execute(
        select(UserPreference).where(UserPreference.key == key)
    )
    pref = result.scalar_one_or_none()

    if not pref:
        raise HTTPException(status_code=404, detail="Preference not found")

    return {"key": pref.key, "value": json.loads(pref.value)}


@router.put("/{key}")
async def set_preference(key: str, value: dict = Body(...), session: AsyncSession = Depends(get_db_session)):
    """Set a user preference."""
    # Check if preference exists
    result = await session.execute(
        select(UserPreference).where(UserPreference.key == key)
    )
    pref = result.scalar_one_or_none()

    if pref:
        # Update existing
        pref.value = json.dumps(value)
        pref.updated_at = datetime.utcnow()
    else:
        # Create new
        pref = UserPreference(
            key=key,
            value=json.dumps(value),
            updated_at=datetime.utcnow()
        )
        session.add(pref)

    await session.commit()
    return {"status": "success", "key": key}
