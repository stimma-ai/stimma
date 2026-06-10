"""
API routes for profile management.
"""
import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from core.logging import get_logger

from database_registry import get_database_registry
from core.profile_context import get_current_profile
from config import get_settings

log = get_logger(__name__)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


# --- PIN Management Models ---

class VerifyPinRequest(BaseModel):
    pin: str


class SetPinRequest(BaseModel):
    current_pin: Optional[str] = None  # Required if PIN already set
    new_pin: Optional[str] = None  # None to remove PIN


class PinSettingsRequest(BaseModel):
    pin_idle_timeout_minutes: int


class ReorderProfilesRequest(BaseModel):
    profile_ids: list[str]  # Ordered list of all profile IDs


@router.get("")
async def list_profiles():
    """
    List all available profiles.

    Returns list of profile objects with id, name, database, db_guid, has_pin, and pin_idle_timeout_minutes fields.
    """
    registry = get_database_registry()
    profiles = registry.list_profiles()
    settings = get_settings()

    # Add db_guid and PIN info to each profile
    for profile in profiles:
        try:
            profile["db_guid"] = registry.get_db_guid(profile["id"])
        except Exception:
            profile["db_guid"] = None  # Database not yet initialized

        # Add PIN info (without exposing hash)
        profile_config = settings.get_profile(profile["id"])
        if profile_config:
            profile["has_pin"] = profile_config.pin_hash is not None
            profile["pin_idle_timeout_minutes"] = profile_config.pin_idle_timeout_minutes
        else:
            profile["has_pin"] = False
            profile["pin_idle_timeout_minutes"] = 30

    return {"profiles": profiles}


@router.get("/current")
async def get_current():
    """
    Get the current profile from the request context.

    This is useful for the frontend to verify which profile
    is currently active. Includes db_guid for URL construction.
    """
    profile_id = get_current_profile()
    log.debug(f"/api/profiles/current - profile_id from context: {profile_id}")
    registry = get_database_registry()
    profiles = {p['id']: p for p in registry.list_profiles()}
    profile = profiles.get(profile_id)
    if profile:
        try:
            profile["db_guid"] = registry.get_db_guid(profile_id)
        except Exception:
            profile["db_guid"] = None
        return profile
    return {"id": profile_id, "name": "Unknown", "database": "unknown", "db_guid": None}


@router.get("/{profile_id}")
async def get_profile(profile_id: str):
    """
    Get details for a specific profile.
    """
    registry = get_database_registry()
    config = registry.get_profile_config(profile_id)
    if not config:
        return {"error": f"Profile not found: {profile_id}"}, 404

    try:
        db_guid = registry.get_db_guid(profile_id)
    except Exception:
        db_guid = None

    return {
        "id": config.id,
        "name": config.name,
        "database": config.database,
        "db_guid": db_guid,
        "folders": [{"path": f.path, "readonly": f.readonly, "allow_generate": f.allow_generate} for f in config.folders],
        "markers": [{"name": m.name, "color": m.color} for m in config.markers],
    }


@router.get("/{profile_id}/folders")
async def get_profile_folders(profile_id: str):
    """
    Get the folders configured for a specific profile.
    """
    settings = get_settings()
    folders = settings.get_folders_for_profile(profile_id)
    return {
        "folders": [
            {
                "path": f.path,
                "readonly": f.readonly,
                "allow_generate": f.allow_generate,
                "refresh_interval_seconds": f.refresh_interval_seconds,
            }
            for f in folders
        ]
    }


@router.get("/{profile_id}/generation-folders")
async def get_profile_generation_folders(profile_id: str):
    """
    Get the folders that allow generation for a specific profile.
    """
    settings = get_settings()
    folders = settings.get_generation_folders_for_profile(profile_id)
    return {
        "folders": [
            {
                "path": f.path,
                "readonly": f.readonly,
                "allow_generate": f.allow_generate,
            }
            for f in folders
        ]
    }


# --- PIN Management Endpoints ---

@router.get("/{profile_id}/pin-status")
async def get_pin_status(profile_id: str):
    """
    Get PIN status for a profile.

    Returns whether PIN is set and the idle timeout setting.
    """
    settings = get_settings()
    profile_config = settings.get_profile(profile_id)
    if not profile_config:
        raise HTTPException(status_code=404, detail=f"Profile not found: {profile_id}")

    return {
        "has_pin": profile_config.pin_hash is not None,
        "pin_idle_timeout_minutes": profile_config.pin_idle_timeout_minutes
    }


@router.post("/{profile_id}/verify-pin")
async def verify_pin(profile_id: str, request: VerifyPinRequest):
    """
    Verify a PIN for a profile.

    Returns success if PIN matches, 401 if invalid.
    Used by frontend to validate PIN before caching.
    """
    settings = get_settings()
    profile_config = settings.get_profile(profile_id)
    if not profile_config:
        raise HTTPException(status_code=404, detail=f"Profile not found: {profile_id}")

    if not profile_config.pin_hash:
        # No PIN set - always valid
        return {"valid": True}

    # Verify PIN
    try:
        is_valid = bcrypt.checkpw(
            request.pin.encode('utf-8'),
            profile_config.pin_hash.encode('utf-8')
        )
    except Exception:
        is_valid = False

    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid PIN")

    # PIN lock usage — never the PIN itself.
    from telemetry import get_telemetry_client
    get_telemetry_client().track("profile_unlocked", category="settings")

    return {"valid": True}


@router.patch("/{profile_id}/pin")
async def set_pin(profile_id: str, request: SetPinRequest):
    """
    Set, change, or remove PIN for a profile.

    - To set PIN (first time): provide new_pin only
    - To change PIN: provide current_pin and new_pin
    - To remove PIN: provide current_pin and new_pin=null

    Updates config.yaml and reloads settings.
    """
    from ruamel.yaml import YAML
    from config import reload_settings
    import app_dirs

    settings = get_settings()
    profile_config = settings.get_profile(profile_id)
    if not profile_config:
        raise HTTPException(status_code=404, detail=f"Profile not found: {profile_id}")

    # If PIN already set, verify current PIN
    if profile_config.pin_hash:
        if not request.current_pin:
            raise HTTPException(status_code=400, detail="Current PIN required to change PIN")
        try:
            is_valid = bcrypt.checkpw(
                request.current_pin.encode('utf-8'),
                profile_config.pin_hash.encode('utf-8')
            )
        except Exception:
            is_valid = False
        if not is_valid:
            raise HTTPException(status_code=401, detail="Current PIN is incorrect")

    # Hash new PIN or set to null
    new_hash = None
    if request.new_pin:
        if len(request.new_pin) < 4 or len(request.new_pin) > 20:
            raise HTTPException(status_code=400, detail="PIN must be 4-20 characters")
        new_hash = bcrypt.hashpw(request.new_pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    # Update config.yaml
    yaml_parser = YAML()
    yaml_parser.preserve_quotes = True
    yaml_parser.width = 120

    config_path = app_dirs.get_config_path()
    with open(config_path, 'r') as f:
        data = yaml_parser.load(f)

    # Find and update the profile
    for profile in data.get('profiles', []):
        if profile.get('id') == profile_id:
            if new_hash:
                profile['pin_hash'] = new_hash
            elif 'pin_hash' in profile:
                del profile['pin_hash']
            break

    # Write back
    import tempfile
    import os
    import config_writer
    config_writer._app_initiated_write = True
    config_dir = config_path.parent
    fd, temp_path = tempfile.mkstemp(suffix='.yaml', dir=config_dir)
    try:
        with os.fdopen(fd, 'w') as f:
            yaml_parser.dump(data, f)
        os.replace(temp_path, config_path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise

    # Reload settings
    reload_settings()

    # Clear PIN verification cache for this profile
    from core.middleware import clear_pin_cache
    clear_pin_cache(profile_id)

    from telemetry import get_telemetry_client
    get_telemetry_client().track(
        "profile_pin_set" if new_hash else "profile_pin_removed",
        category="settings",
    )

    return {
        "success": True,
        "has_pin": new_hash is not None
    }


@router.post("/reorder")
async def reorder_profiles(request: ReorderProfilesRequest):
    """
    Reorder profiles by providing an ordered list of profile IDs.

    Updates config.yaml with profiles in the new order.
    """
    from ruamel.yaml import YAML
    from config import reload_settings
    import app_dirs

    settings = get_settings()

    # Validate all profile IDs exist
    existing_ids = {p.id for p in settings.profiles}
    requested_ids = set(request.profile_ids)

    if existing_ids != requested_ids:
        missing = existing_ids - requested_ids
        extra = requested_ids - existing_ids
        errors = []
        if missing:
            errors.append(f"Missing profile IDs: {missing}")
        if extra:
            errors.append(f"Unknown profile IDs: {extra}")
        raise HTTPException(status_code=400, detail="; ".join(errors))

    # Update config.yaml
    yaml_parser = YAML()
    yaml_parser.preserve_quotes = True
    yaml_parser.width = 120

    config_path = app_dirs.get_config_path()
    with open(config_path, 'r') as f:
        data = yaml_parser.load(f)

    # Create a map of profile id to profile data
    profile_map = {p.get('id'): p for p in data.get('profiles', [])}

    # Reorder profiles according to request
    data['profiles'] = [profile_map[pid] for pid in request.profile_ids]

    # Write back
    import tempfile
    import os
    import config_writer
    config_writer._app_initiated_write = True
    config_dir = config_path.parent
    fd, temp_path = tempfile.mkstemp(suffix='.yaml', dir=config_dir)
    try:
        with os.fdopen(fd, 'w') as f:
            yaml_parser.dump(data, f)
        os.replace(temp_path, config_path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise

    # Reload settings
    reload_settings()

    return {"success": True, "order": request.profile_ids}


@router.patch("/{profile_id}/pin-settings")
async def update_pin_settings(profile_id: str, request: PinSettingsRequest):
    """
    Update PIN settings (idle timeout) for a profile.

    Does not require current PIN - only controls timeout duration.
    """
    from ruamel.yaml import YAML
    from config import reload_settings
    import app_dirs

    settings = get_settings()
    profile_config = settings.get_profile(profile_id)
    if not profile_config:
        raise HTTPException(status_code=404, detail=f"Profile not found: {profile_id}")

    if request.pin_idle_timeout_minutes < 1 or request.pin_idle_timeout_minutes > 1440:
        raise HTTPException(status_code=400, detail="Timeout must be 1-1440 minutes")

    # Update config.yaml
    yaml_parser = YAML()
    yaml_parser.preserve_quotes = True
    yaml_parser.width = 120

    config_path = app_dirs.get_config_path()
    with open(config_path, 'r') as f:
        data = yaml_parser.load(f)

    # Find and update the profile
    for profile in data.get('profiles', []):
        if profile.get('id') == profile_id:
            profile['pin_idle_timeout_minutes'] = request.pin_idle_timeout_minutes
            break

    # Write back
    import tempfile
    import os
    import config_writer
    config_writer._app_initiated_write = True
    config_dir = config_path.parent
    fd, temp_path = tempfile.mkstemp(suffix='.yaml', dir=config_dir)
    try:
        with os.fdopen(fd, 'w') as f:
            yaml_parser.dump(data, f)
        os.replace(temp_path, config_path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise

    # Reload settings
    reload_settings()

    return {
        "success": True,
        "pin_idle_timeout_minutes": request.pin_idle_timeout_minutes
    }
