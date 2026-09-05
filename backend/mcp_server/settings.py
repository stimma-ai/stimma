"""Owner-facing MCP setup routes, protected by existing profile/PIN middleware."""

from datetime import datetime
import hashlib
import secrets
import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from core.dependencies import get_db_session
from core.profile_context import get_current_profile
from config import get_settings
from .access import access, installation_id
from .models import McpClient
from .jobs import revoke

router = APIRouter(prefix="/api/mcp", tags=["mcp-settings"])


class Enable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class Connect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Assistant", min_length=1, max_length=80)


@router.get("/settings")
async def settings(session=Depends(get_db_session)):
    profile = get_settings().get_profile(get_current_profile())
    clients = (
        await session.scalars(
            select(McpClient).where(
                McpClient.deleted_at.is_(None),
                McpClient.installation == installation_id(),
            )
        )
    ).all()
    return {
        "enabled": profile.mcp_enabled,
        "profile_id": profile.id,
        "profile_name": profile.name,
        "idle_timeout_minutes": profile.pin_idle_timeout_minutes,
        "clients": [
            {
                "id": client.id,
                "name": client.name,
                "unlocked": bool(
                    access.unlocks.get((profile.id, client.id))
                    and __import__("time").time()
                    - access.unlocks[profile.id, client.id].last_activity
                    < max(1, profile.pin_idle_timeout_minutes) * 60
                ),
                "last_use": access.unlocks[(profile.id, client.id)].last_activity
                if (profile.id, client.id) in access.unlocks
                else None,
            }
            for client in clients
        ],
    }


@router.put("/settings")
async def enable(body: Enable):
    from config_writer import patch_profile_section
    from config import reload_settings

    profile_id = get_current_profile()
    patch_profile_section(profile_id, "mcp_enabled", body.enabled)
    reload_settings()
    if not body.enabled:
        await revoke(profile_id)
    return {"enabled": body.enabled}


@router.post("/clients")
async def connect(body: Connect, session=Depends(get_db_session)):
    profile_id = get_current_profile()
    profile = get_settings().get_profile(profile_id)
    if not profile.mcp_enabled:
        from fastapi import HTTPException

        raise HTTPException(409, "Enable MCP for this profile first.")
    credential = secrets.token_urlsafe(32)
    client = McpClient(
        id=uuid.uuid4().hex,
        name=body.name,
        credential_hash=hashlib.sha256(credential.encode()).hexdigest(),
        installation=installation_id(),
    )
    session.add(client)
    await session.commit()
    return {
        "id": client.id,
        "name": client.name,
        "connection": {
            "version": 1,
            "alias": f"{profile_id}-{client.id[:8]}",
            "profile_id": profile_id,
            "credential": credential,
            "endpoint": f"http://127.0.0.1:{get_settings().server.port}/mcp/profiles/{profile_id}",
        },
    }


@router.post("/lock")
async def lock():
    await revoke(get_current_profile())
    return {"locked": True}


@router.delete("/clients/{client_id}")
async def disconnect(client_id: str, session=Depends(get_db_session)):
    client = await session.get(McpClient, client_id)
    if client:
        client.deleted_at = datetime.utcnow()
        await session.commit()
        await revoke(get_current_profile(), client_id)
    return {"disconnected": True}


class ShareContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_ids: list[int] = Field(min_length=1, max_length=200)


@router.post("/context")
async def share_context(body: ShareContext, session=Depends(get_db_session)):
    from .ui_context import share
    from .access import McpError
    from fastapi import HTTPException

    try:
        result = await share(get_current_profile(), body.asset_ids, session)
        return {
            "shared": True,
            "count": len(result["targets"]),
            "expires_at": result["expires_at"],
        }
    except McpError as exc:
        raise HTTPException(409, exc.message) from None
