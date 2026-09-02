"""Multi-device HTTP surface (loopback only).

Two consumers:
- The settings UI, for the "Enable Stimma Server" toggle and the server ledger.
- Electron main, which needs the account token and device list to reach a
  remote device, and deliberately never holds account credentials itself.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.logging import get_logger
from multi_device import registry, service

log = get_logger(__name__)

router = APIRouter(prefix="/api/multi-device", tags=["multi-device"])


class ServingRequest(BaseModel):
    enabled: bool


class RenameRequest(BaseModel):
    name: str


@router.get("/status")
async def get_status():
    """This device's own identity and serving state."""
    return await service.status()


@router.post("/serving")
async def set_serving(request: ServingRequest):
    """Flip 'Enable Stimma Server'."""
    try:
        return await service.apply_serving(request.enabled)
    except Exception as exc:
        log.error("multi-device: failed to set serving", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.patch("/name")
async def rename_device(request: RenameRequest):
    """Rename this server.

    The default is the OS hostname, which is not always unique and is rarely
    what the user would call the machine. The new name is republished
    immediately so the other devices' pickers update without waiting for a
    heartbeat.
    """
    name = request.name.strip()
    if not name or len(name) > 128:
        raise HTTPException(status_code=400, detail="Name must be 1-128 characters")
    return await service.rename(name)


@router.get("/devices")
async def get_devices():
    """The account roster, with this install marked.

    Three outcomes, kept apart on purpose. Signed out is not an error: the
    UI's rule is "signed in = the feature exists", so an empty list is exactly
    what the chip needs to hide itself. A registry that did not answer IS an
    error, and saying so is what stops an outage from being read as a
    signed-out account — the caller keeps its cached roster either way, but
    only one of the two is worth investigating.
    """
    try:
        devices = await registry.list_devices()
    except registry.RegistryUnavailable as exc:
        return {
            "devices": [],
            "signedIn": True,
            "registryError": str(exc),
            "selfDeviceId": None,
        }

    if devices is None:
        return {"devices": [], "signedIn": False, "registryError": None, "selfDeviceId": None}

    status = await service.status()
    return {
        "devices": devices,
        "signedIn": True,
        "registryError": None,
        "selfDeviceId": status["deviceId"],
    }


@router.delete("/devices/{device_id}")
async def remove_device(device_id: str):
    """Housekeeping removal from the ledger — not a revoke."""
    if not await registry.remove_device(device_id):
        raise HTTPException(status_code=502, detail="Could not remove device")
    return {"status": "removed", "deviceId": device_id}


@router.post("/refresh")
async def refresh():
    """Re-publish this device and return peers (used after sign-in)."""
    peers = await service.register_now()
    return {"devices": peers or []}


class ConnectRequest(BaseModel):
    deviceId: str


@router.post("/connect-token")
async def connect_token(request: ConnectRequest):
    """Mint a short-lived account token for Electron to bootstrap a session.

    Electron main is the only holder of remote credentials, but the account
    token lives here — this is the one hand-off between them, and it happens
    only on the first connect to a given device.
    """
    from firebase_auth import get_valid_id_token

    token = await get_valid_id_token()
    if not token:
        raise HTTPException(status_code=401, detail="Not signed in")

    status = await service.status()
    return {"idToken": token, "selfDeviceId": status["deviceId"]}
