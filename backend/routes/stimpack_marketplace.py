"""
Stimpack marketplace routes — proxies to stimma.ai cloud API for marketplace operations.

Handles: browse, detail, install, publish, check-updates, update, mine.
"""
from fastapi import APIRouter, HTTPException

import httpx

from config import get_settings
from core.logging import get_logger
from core.profile_context import get_current_profile
from firebase_auth import get_valid_id_token as get_id_token
from privacy_lockdown import disabled_message, is_privacy_lockdown_enabled

router = APIRouter(prefix="/api/stimpack-marketplace", tags=["stimpack-marketplace"])
log = get_logger(__name__)
DEFAULT_AUTO_INSTALL_STIMPACKS = ("prompt-engineering", "layout-design", "tool-selection")


def _stimpacks_api():
    # Keep agent v2 tool registration off the backend startup path. Importing
    # agent.v2.stimpacks executes agent.v2.__init__, which imports the tool package.
    from agent.v2 import stimpacks
    return stimpacks


def _cloud_base() -> str:
    return f"{get_settings().cloud.base_url}/api/stimpacks"


async def _cloud_get(path: str, params: dict | None = None, auth: bool = True) -> dict:
    """Make authenticated GET request to cloud stimpacks API."""
    if is_privacy_lockdown_enabled():
        raise HTTPException(status_code=403, detail=disabled_message("Marketplace stimpacks"))
    headers = {}
    if auth:
        token = await get_id_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{_cloud_base()}{path}",
            params=params,
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()


async def _cloud_post(path: str, data: dict | None = None, auth: bool = True) -> dict:
    """Make authenticated POST request to cloud stimpacks API."""
    if is_privacy_lockdown_enabled():
        raise HTTPException(status_code=403, detail=disabled_message("Marketplace stimpacks"))
    headers = {}
    if auth:
        token = await get_id_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{_cloud_base()}{path}",
            json=data,
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()


# --- Browse / Detail ---

@router.get("/browse")
async def browse_marketplace(
    q: str = "",
    tags: str = "",
    sort: str = "popular",
    nsfw: bool = False,
    autoInstall: bool = False,
    page: int = 1,
    limit: int = 20,
):
    """Browse marketplace stimpacks (proxied to cloud)."""
    if is_privacy_lockdown_enabled():
        raise HTTPException(status_code=403, detail=disabled_message("Marketplace stimpacks"))
    params = {"sort": sort, "page": str(page), "limit": str(limit)}
    if q:
        params["q"] = q
    if tags:
        params["tags"] = tags
    if nsfw:
        params["nsfw"] = "true"
    if autoInstall:
        params["autoInstall"] = "true"
    return await _cloud_get("", params=params, auth=False)


@router.get("/detail/{name}")
async def get_marketplace_detail(name: str):
    """Get stimpack detail from marketplace (proxied to cloud)."""
    if is_privacy_lockdown_enabled():
        raise HTTPException(status_code=403, detail=disabled_message("Marketplace stimpacks"))
    return await _cloud_get(f"/{name}", auth=False)


# --- Install ---

@router.post("/install/{name}")
async def install_from_marketplace(name: str):
    """Download and install a stimpack from the marketplace."""
    if is_privacy_lockdown_enabled():
        raise HTTPException(status_code=403, detail=disabled_message("Marketplace stimpacks"))
    profile_id = get_current_profile()
    stimpacks_api = _stimpacks_api()

    # Check if already installed
    installed = stimpacks_api.list_installed_stimpacks(profile_id=profile_id)
    for s in installed:
        if s.name == name:
            raise HTTPException(status_code=409, detail=f"Stimpack '{name}' is already installed")

    # Get stimpack detail from cloud
    detail = await _cloud_get(f"/{name}", auth=False)
    if not detail or detail.get("status") != "approved":
        raise HTTPException(status_code=404, detail="Stimpack not found or not approved")

    # Download zip
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{_cloud_base()}/{name}/download",
            timeout=60.0,
        )
        response.raise_for_status()
        zip_bytes = response.content

    # Install locally
    current_version = detail.get("currentVersion") or 1
    info = stimpacks_api.install_stimpack_from_zip_bytes(
        zip_bytes,
        profile_id=profile_id,
        marketplace_meta={
            "stimpackId": detail["id"],
            "name": name,
            "version": current_version,
            "versionId": detail.get("currentVersionId", ""),
            "author": detail.get("authorUsername", ""),
            "authorAvatarKey": detail.get("authorAvatarKey", ""),
            "autoEnable": detail.get("autoEnable", False),
        },
    )

    if not info:
        raise HTTPException(status_code=500, detail="Failed to install stimpack")

    # Record install on cloud (fire-and-forget)
    try:
        await _cloud_post(f"/{name}/install", {"versionId": detail.get("currentVersionId")})
    except Exception:
        pass  # Don't fail the install if tracking fails

    from telemetry import get_telemetry_client
    get_telemetry_client().track("stimpack_marketplace_installed", {"stimpackName": name}, category="stimpacks")

    return {
        "name": info.name,
        "display_name": info.display_name,
        "description": info.description,
        "author": info.author,
        "tags": info.tags,
        "tier": info.tier,
        "marketplace_version": info.marketplace.version if info.marketplace else None,
        "marketplace_author": info.marketplace.author if info.marketplace else None,
    }


# --- Check Updates ---

@router.get("/check-updates")
async def check_updates():
    """Check if any marketplace-installed stimpacks have newer versions."""
    if is_privacy_lockdown_enabled():
        return {"updates": []}
    profile_id = get_current_profile()
    stimpacks_api = _stimpacks_api()

    marketplace_stimpacks = stimpacks_api.get_marketplace_installed_stimpacks(profile_id)
    if not marketplace_stimpacks:
        return {"updates": []}

    installed = [
        {"name": s.name, "version": s.marketplace.version}
        for s in marketplace_stimpacks
        if s.marketplace
    ]

    try:
        result = await _cloud_post("/updates", {"installed": installed}, auth=False)
        return result
    except Exception as e:
        log.warning(f"Failed to check stimpack updates: {e}")
        return {"updates": []}


# --- Update ---

@router.post("/update/{name}")
async def update_from_marketplace(name: str):
    """Download and update a marketplace-installed stimpack to the latest version."""
    if is_privacy_lockdown_enabled():
        raise HTTPException(status_code=403, detail=disabled_message("Marketplace stimpacks"))
    profile_id = get_current_profile()
    stimpacks_api = _stimpacks_api()

    # Find the installed stimpack
    installed = stimpacks_api.list_installed_stimpacks(profile_id=profile_id)
    stimpack = next((s for s in installed if s.name == name and s.marketplace), None)
    if not stimpack:
        raise HTTPException(status_code=404, detail=f"Community stimpack '{name}' not found")

    # Get detail
    detail = await _cloud_get(f"/{name}", auth=False)
    if not detail:
        raise HTTPException(status_code=404, detail="Stimpack not found in library")

    # Download zip
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{_cloud_base()}/{name}/download",
            timeout=60.0,
        )
        response.raise_for_status()
        zip_bytes = response.content

    # Re-install (overwrites existing)
    current_version = detail.get("currentVersion") or 1
    info = stimpacks_api.install_stimpack_from_zip_bytes(
        zip_bytes,
        profile_id=profile_id,
        marketplace_meta={
            "stimpackId": detail["id"],
            "name": name,
            "version": current_version,
            "versionId": detail.get("currentVersionId", ""),
            "author": detail.get("authorUsername", ""),
            "authorAvatarKey": detail.get("authorAvatarKey", ""),
            "autoEnable": detail.get("autoEnable", False),
        },
    )

    if not info:
        raise HTTPException(status_code=500, detail="Failed to update stimpack")

    return {
        "name": info.name,
        "display_name": info.display_name,
        "tier": info.tier,
        "marketplace_version": info.marketplace.version if info.marketplace else None,
    }


# --- My Stimpacks ---

@router.get("/mine")
async def list_my_marketplace_stimpacks():
    """List user's own published stimpacks on the marketplace."""
    if is_privacy_lockdown_enabled():
        raise HTTPException(status_code=403, detail=disabled_message("Marketplace stimpacks"))
    try:
        return await _cloud_get("/mine")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(status_code=401, detail="Not authenticated")
        raise HTTPException(status_code=500, detail="Failed to list community stimpacks")


# --- Auto-install for new profiles ---

@router.post("/auto-install")
async def run_auto_install():
    """Run auto-install for new profiles. Downloads and installs auto-install stimpacks from cloud."""
    if is_privacy_lockdown_enabled():
        return {"installed": [], "message": disabled_message("Marketplace stimpacks")}
    profile_id = get_current_profile()
    stimpacks_api = _stimpacks_api()
    requested_names: list[str] = []
    seen_names: set[str] = set()

    for name in DEFAULT_AUTO_INSTALL_STIMPACKS:
        if name not in seen_names:
            seen_names.add(name)
            requested_names.append(name)

    try:
        result = await _cloud_get("", params={"autoInstall": "true", "limit": "50"}, auth=False)
        for stimpack in result.get("stimpacks", []):
            name = stimpack.get("name")
            if name and name not in seen_names:
                seen_names.add(name)
                requested_names.append(name)
    except Exception as e:
        log.warning(f"Failed to fetch auto-install stimpack list: {e}")

    pending_names = [
        name for name in requested_names
        if stimpacks_api.should_auto_install_stimpack(name, profile_id=profile_id)
    ]
    if not pending_names:
        return {"installed": [], "message": "No auto-install stimpacks pending"}

    installed = []
    failed = []
    for name in pending_names:
        try:
            detail = await _cloud_get(f"/{name}", auth=False)
            if not detail or detail.get("status") != "approved":
                raise ValueError("Stimpack not found or not approved")

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{_cloud_base()}/{name}/download",
                    timeout=60.0,
                )
                response.raise_for_status()
                zip_bytes = response.content

            current_version = detail.get("currentVersion") or 1
            info = stimpacks_api.install_stimpack_from_zip_bytes(
                zip_bytes,
                profile_id=profile_id,
                marketplace_meta={
                    "stimpackId": detail["id"],
                    "name": name,
                    "version": current_version,
                    "versionId": detail.get("currentVersionId", ""),
                    "author": detail.get("authorUsername", ""),
                    "authorAvatarKey": detail.get("authorAvatarKey", ""),
                    "autoEnable": detail.get("autoEnable", False),
                },
            )
            if info:
                stimpacks_api.record_auto_installed_stimpack(name, profile_id=profile_id)
                installed.append(name)
                log.info(f"Auto-installed marketplace stimpack: {name}")
            else:
                failed.append(name)
        except Exception as e:
            failed.append(name)
            log.warning(f"Failed to auto-install stimpack {name}: {e}")

    from telemetry import get_telemetry_client
    get_telemetry_client().track("stimpacks_auto_installed", {"count": len(installed), "stimpacks": installed}, category="stimpacks")

    response: dict[str, list[str] | str] = {"installed": installed}
    if failed:
        response["failed"] = failed
    return response
