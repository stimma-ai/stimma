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
from core.listener import port as loopback_port
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


class Rename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)


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
                "created_at": client.created_at.isoformat() + "Z",
                "last_used_at": client.last_used_at.isoformat() + "Z"
                if client.last_used_at
                else None,
            }
            for client in sorted(clients, key=lambda c: c.created_at)
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
    # ``endpoint`` is this backend's own loopback listener, which only helps a
    # caller on the same machine (dev). The desktop app
    # joins ``path`` to its own origin instead: the shell's loopback proxy,
    # which forwards to whichever install the window is on. That is the only
    # address that works when the app is driving a remote Stimma Server,
    # whose backend listens on loopback behind a TLS device gate.
    path = f"/mcp/profiles/{profile_id}"
    return {
        "id": client.id,
        "name": client.name,
        "connection": {
            "version": 1,
            "profile_id": profile_id,
            "credential": credential,
            "path": path,
            "endpoint": f"http://127.0.0.1:{loopback_port()}{path}",
        },
    }


@router.post("/lock")
async def lock():
    await revoke(get_current_profile())
    return {"locked": True}


@router.patch("/clients/{client_id}")
async def rename(client_id: str, body: Rename, session=Depends(get_db_session)):
    from fastapi import HTTPException

    client = await session.get(McpClient, client_id)
    if not client or client.deleted_at or client.installation != installation_id():
        raise HTTPException(404, "Connection not found.")
    client.name = body.name.strip() or client.name
    await session.commit()
    return {"id": client.id, "name": client.name}


@router.delete("/clients/{client_id}")
async def disconnect(client_id: str, session=Depends(get_db_session)):
    client = await session.get(McpClient, client_id)
    if client:
        client.deleted_at = datetime.utcnow()
        await session.commit()
        await revoke(get_current_profile(), client_id)
    return {"disconnected": True}

