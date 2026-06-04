"""
Skill marketplace routes — proxies to stimma.ai cloud API for marketplace operations.

Handles: browse, detail, install, publish, check-updates, update, mine.
"""
from fastapi import APIRouter, HTTPException

import httpx

from config import get_settings
from core.logging import get_logger
from core.profile_context import get_current_profile
from firebase_auth import get_valid_id_token as get_id_token

router = APIRouter(prefix="/api/skill-marketplace", tags=["skill-marketplace"])
log = get_logger(__name__)
DEFAULT_AUTO_INSTALL_SKILLS = ("prompt-engineering", "layout-design", "tool-selection")


def _skills_api():
    # Keep agent v2 tool registration off the backend startup path. Importing
    # agent.v2.skills executes agent.v2.__init__, which imports the tool package.
    from agent.v2 import skills
    return skills


def _cloud_base() -> str:
    return f"{get_settings().cloud.base_url}/api/skills"


async def _cloud_get(path: str, params: dict | None = None, auth: bool = True) -> dict:
    """Make authenticated GET request to cloud skills API."""
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
    """Make authenticated POST request to cloud skills API."""
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
    """Browse marketplace skills (proxied to cloud)."""
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
    """Get skill detail from marketplace (proxied to cloud)."""
    return await _cloud_get(f"/{name}", auth=False)


# --- Install ---

@router.post("/install/{name}")
async def install_from_marketplace(name: str):
    """Download and install a skill from the marketplace."""
    profile_id = get_current_profile()
    skills_api = _skills_api()

    # Check if already installed
    installed = skills_api.list_installed_skills(profile_id=profile_id)
    for s in installed:
        if s.name == name:
            raise HTTPException(status_code=409, detail=f"Skill '{name}' is already installed")

    # Get skill detail from cloud
    detail = await _cloud_get(f"/{name}", auth=False)
    if not detail or detail.get("status") != "approved":
        raise HTTPException(status_code=404, detail="Skill not found or not approved")

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
    info = skills_api.install_skill_from_zip_bytes(
        zip_bytes,
        profile_id=profile_id,
        marketplace_meta={
            "skillId": detail["id"],
            "name": name,
            "version": current_version,
            "versionId": detail.get("currentVersionId", ""),
            "author": detail.get("authorUsername", ""),
            "authorAvatarKey": detail.get("authorAvatarKey", ""),
            "autoEnable": detail.get("autoEnable", False),
        },
    )

    if not info:
        raise HTTPException(status_code=500, detail="Failed to install skill")

    # Record install on cloud (fire-and-forget)
    try:
        await _cloud_post(f"/{name}/install", {"versionId": detail.get("currentVersionId")})
    except Exception:
        pass  # Don't fail the install if tracking fails

    from telemetry import get_telemetry_client
    get_telemetry_client().track("skill_marketplace_installed", {"skillName": name})

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
    """Check if any marketplace-installed skills have newer versions."""
    profile_id = get_current_profile()
    skills_api = _skills_api()

    marketplace_skills = skills_api.get_marketplace_installed_skills(profile_id)
    if not marketplace_skills:
        return {"updates": []}

    installed = [
        {"name": s.name, "version": s.marketplace.version}
        for s in marketplace_skills
        if s.marketplace
    ]

    try:
        result = await _cloud_post("/updates", {"installed": installed}, auth=False)
        return result
    except Exception as e:
        log.warning(f"Failed to check skill updates: {e}")
        return {"updates": []}


# --- Update ---

@router.post("/update/{name}")
async def update_from_marketplace(name: str):
    """Download and update a marketplace-installed skill to the latest version."""
    profile_id = get_current_profile()
    skills_api = _skills_api()

    # Find the installed skill
    installed = skills_api.list_installed_skills(profile_id=profile_id)
    skill = next((s for s in installed if s.name == name and s.marketplace), None)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Community skill '{name}' not found")

    # Get detail
    detail = await _cloud_get(f"/{name}", auth=False)
    if not detail:
        raise HTTPException(status_code=404, detail="Skill not found in library")

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
    info = skills_api.install_skill_from_zip_bytes(
        zip_bytes,
        profile_id=profile_id,
        marketplace_meta={
            "skillId": detail["id"],
            "name": name,
            "version": current_version,
            "versionId": detail.get("currentVersionId", ""),
            "author": detail.get("authorUsername", ""),
            "authorAvatarKey": detail.get("authorAvatarKey", ""),
            "autoEnable": detail.get("autoEnable", False),
        },
    )

    if not info:
        raise HTTPException(status_code=500, detail="Failed to update skill")

    return {
        "name": info.name,
        "display_name": info.display_name,
        "tier": info.tier,
        "marketplace_version": info.marketplace.version if info.marketplace else None,
    }


# --- My Skills ---

@router.get("/mine")
async def list_my_marketplace_skills():
    """List user's own published skills on the marketplace."""
    try:
        return await _cloud_get("/mine")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(status_code=401, detail="Not authenticated")
        raise HTTPException(status_code=500, detail="Failed to list community skills")


# --- Auto-install for new profiles ---

@router.post("/auto-install")
async def run_auto_install():
    """Run auto-install for new profiles. Downloads and installs auto-install skills from cloud."""
    profile_id = get_current_profile()
    skills_api = _skills_api()
    requested_names: list[str] = []
    seen_names: set[str] = set()

    for name in DEFAULT_AUTO_INSTALL_SKILLS:
        if name not in seen_names:
            seen_names.add(name)
            requested_names.append(name)

    try:
        result = await _cloud_get("", params={"autoInstall": "true", "limit": "50"}, auth=False)
        for skill in result.get("skills", []):
            name = skill.get("name")
            if name and name not in seen_names:
                seen_names.add(name)
                requested_names.append(name)
    except Exception as e:
        log.warning(f"Failed to fetch auto-install skill list: {e}")

    pending_names = [
        name for name in requested_names
        if skills_api.should_auto_install_skill(name, profile_id=profile_id)
    ]
    if not pending_names:
        return {"installed": [], "message": "No auto-install skills pending"}

    installed = []
    failed = []
    for name in pending_names:
        try:
            detail = await _cloud_get(f"/{name}", auth=False)
            if not detail or detail.get("status") != "approved":
                raise ValueError("Skill not found or not approved")

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{_cloud_base()}/{name}/download",
                    timeout=60.0,
                )
                response.raise_for_status()
                zip_bytes = response.content

            current_version = detail.get("currentVersion") or 1
            info = skills_api.install_skill_from_zip_bytes(
                zip_bytes,
                profile_id=profile_id,
                marketplace_meta={
                    "skillId": detail["id"],
                    "name": name,
                    "version": current_version,
                    "versionId": detail.get("currentVersionId", ""),
                    "author": detail.get("authorUsername", ""),
                    "authorAvatarKey": detail.get("authorAvatarKey", ""),
                    "autoEnable": detail.get("autoEnable", False),
                },
            )
            if info:
                skills_api.record_auto_installed_skill(name, profile_id=profile_id)
                installed.append(name)
                log.info(f"Auto-installed marketplace skill: {name}")
            else:
                failed.append(name)
        except Exception as e:
            failed.append(name)
            log.warning(f"Failed to auto-install skill {name}: {e}")

    from telemetry import get_telemetry_client
    get_telemetry_client().track("skills_auto_installed", {"count": len(installed), "skills": installed})

    response: dict[str, list[str] | str] = {"installed": installed}
    if failed:
        response["failed"] = failed
    return response
