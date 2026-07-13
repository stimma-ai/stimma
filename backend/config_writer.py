"""
Config writing utilities with atomic writes and comment preservation.

Uses ruamel.yaml to preserve comments and formatting in the config file.
"""
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ruamel.yaml import YAML

import app_dirs


# Flag to suppress "Config Reloaded" toast when the app itself wrote the config.
# Set by _atomic_write_config, checked/cleared by watch_config_file in app.py.
_app_initiated_write = False


def get_config_path() -> Path:
    """Get the path to the config file."""
    return app_dirs.get_config_path()


def backup_config() -> Optional[Path]:
    """Create a timestamped backup of the current config file.

    Returns:
        Path to the backup file, or None if no config exists.
    """
    config_path = get_config_path()
    if not config_path.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = config_path.with_suffix(f".{timestamp}.bak")
    shutil.copy2(config_path, backup_path)
    return backup_path


def _load_config_yaml() -> tuple[Any, YAML]:
    """Load config file with ruamel.yaml for comment preservation.

    Returns:
        Tuple of (config data, yaml instance for writing back).
    """
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 120  # Prevent line wrapping

    config_path = get_config_path()
    with open(config_path, 'r') as f:
        data = yaml.load(f)

    return data, yaml


def _atomic_write_config(data: Any, yaml: YAML) -> None:
    """Atomically write config data to file.

    1. Write to temp file in same directory
    2. Backup existing config to config.yaml.bak
    3. Atomic rename temp to config.yaml
    """
    global _app_initiated_write
    _app_initiated_write = True
    config_path = get_config_path()
    config_dir = config_path.parent

    # Write to temp file in same directory (for atomic rename)
    fd, temp_path = tempfile.mkstemp(suffix='.yaml', dir=config_dir)
    try:
        with os.fdopen(fd, 'w') as f:
            yaml.dump(data, f)

        # Backup existing config
        backup_path = config_path.with_suffix('.yaml.bak')
        if config_path.exists():
            shutil.copy2(config_path, backup_path)

        # Atomic rename
        os.replace(temp_path, config_path)
    except Exception:
        # Clean up temp file on error
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def _find_profile_index(data: Any, profile_id: str) -> Optional[int]:
    """Find the index of a profile in the profiles list."""
    profiles = data.get('profiles', [])
    for i, profile in enumerate(profiles):
        if profile.get('id') == profile_id:
            return i
    return None


def patch_profile_section(profile_id: str, section: str, value: Any) -> None:
    """Update a specific section of a profile's config.

    Args:
        profile_id: The profile ID to update.
        section: The section name (e.g., 'folders', 'markers').
        value: The new value for the section.

    Raises:
        ValueError: If the profile is not found.
    """
    data, yaml = _load_config_yaml()

    profile_idx = _find_profile_index(data, profile_id)
    if profile_idx is None:
        raise ValueError(f"Profile '{profile_id}' not found in config")

    # Update the section
    data['profiles'][profile_idx][section] = value

    _atomic_write_config(data, yaml)


def remove_profile_section(profile_id: str, section: str) -> bool:
    """Remove an internal profile section after its migration is complete."""
    data, yaml = _load_config_yaml()
    profile_idx = _find_profile_index(data, profile_id)
    if profile_idx is None:
        return False
    profile = data['profiles'][profile_idx]
    if section not in profile:
        return False
    profile.pop(section)
    _atomic_write_config(data, yaml)
    return True


def patch_global_section(section: str, value: Any) -> None:
    """Update a global (non-profile) section of the config.

    Args:
        section: The section name (e.g., 'face_detection', 'clip', 'captioning').
        value: The new value for the section.
    """
    data, yaml = _load_config_yaml()

    # Update the section
    data[section] = value

    _atomic_write_config(data, yaml)


def update_tool_provider(provider_id: str, updates: Dict[str, Any]) -> None:
    """Update a specific tool provider's configuration.

    Args:
        provider_id: The provider ID to update.
        updates: Dictionary of fields to update (e.g., {'api_key': 'xxx'}).

    Raises:
        ValueError: If the provider is not found.
    """
    data, yaml = _load_config_yaml()

    providers = data.get('tool_providers', [])
    provider_idx = None
    for i, provider in enumerate(providers):
        if provider.get('id') == provider_id:
            provider_idx = i
            break

    if provider_idx is None:
        raise ValueError(f"Tool provider '{provider_id}' not found in config")

    # Update only the specified fields
    for key, value in updates.items():
        data['tool_providers'][provider_idx][key] = value

    _atomic_write_config(data, yaml)


def add_tool_provider(provider_config: Dict[str, Any]) -> None:
    """Add a new tool provider to the config.

    Args:
        provider_config: Dictionary with provider configuration.

    Raises:
        ValueError: If a provider with this ID already exists.
    """
    data, yaml = _load_config_yaml()

    providers = data.get('tool_providers', [])
    for provider in providers:
        if provider.get('id') == provider_config.get('id'):
            raise ValueError(f"Tool provider '{provider_config.get('id')}' already exists")

    if 'tool_providers' not in data:
        data['tool_providers'] = []

    data['tool_providers'].append(provider_config)

    _atomic_write_config(data, yaml)


def remove_tool_provider(provider_id: str) -> None:
    """Remove a tool provider from the config.

    Args:
        provider_id: The provider ID to remove.

    Raises:
        ValueError: If the provider is not found.
    """
    data, yaml = _load_config_yaml()

    providers = data.get('tool_providers', [])
    provider_idx = None
    for i, provider in enumerate(providers):
        if provider.get('id') == provider_id:
            provider_idx = i
            break

    if provider_idx is None:
        raise ValueError(f"Tool provider '{provider_id}' not found in config")

    data['tool_providers'].pop(provider_idx)

    _atomic_write_config(data, yaml)


def create_profile(profile_id: str, name: str) -> None:
    """Create a new profile in the config.

    Args:
        profile_id: Unique ID for the profile.
        name: Display name for the profile.

    Raises:
        ValueError: If a profile with this ID already exists.
    """
    data, yaml = _load_config_yaml()

    # Check if profile already exists
    if _find_profile_index(data, profile_id) is not None:
        raise ValueError(f"Profile '{profile_id}' already exists")

    # Create new profile with defaults
    import uuid
    new_profile = {
        'id': profile_id,
        'name': name,
        'folders': [],
        'markers': [
            {'id': f"favorite-{str(uuid.uuid4())[:8]}", 'name': 'favorite', 'icon_svg': 'heroicons:heart', 'color': '#ef4444'},
            {'id': f"library-{str(uuid.uuid4())[:8]}", 'name': 'library', 'icon_svg': 'heroicons:bookmark', 'color': '#3b82f6'},
        ],
    }

    # Ensure profiles list exists
    if 'profiles' not in data:
        data['profiles'] = []

    data['profiles'].append(new_profile)

    _atomic_write_config(data, yaml)


def delete_profile(profile_id: str) -> None:
    """Delete a profile from the config.

    Args:
        profile_id: The profile ID to delete.

    Raises:
        ValueError: If the profile is not found or is the only profile.
    """
    data, yaml = _load_config_yaml()

    profiles = data.get('profiles', [])
    if len(profiles) <= 1:
        raise ValueError("Cannot delete the only remaining profile")

    profile_idx = _find_profile_index(data, profile_id)
    if profile_idx is None:
        raise ValueError(f"Profile '{profile_id}' not found in config")

    del data['profiles'][profile_idx]

    _atomic_write_config(data, yaml)


def rename_profile(profile_id: str, new_name: str) -> None:
    """Rename a profile.

    Args:
        profile_id: The profile ID to rename.
        new_name: The new display name.

    Raises:
        ValueError: If the profile is not found.
    """
    data, yaml = _load_config_yaml()

    profile_idx = _find_profile_index(data, profile_id)
    if profile_idx is None:
        raise ValueError(f"Profile '{profile_id}' not found in config")

    data['profiles'][profile_idx]['name'] = new_name

    _atomic_write_config(data, yaml)


# =============================================================================
# Validation Utilities
# =============================================================================


class ValidationError(Exception):
    """Raised when config validation fails."""
    pass


def validate_folder_path(path: str) -> None:
    """Validate that a folder path exists and is a directory.

    Args:
        path: The folder path to validate.

    Raises:
        ValidationError: If the path is invalid.
    """
    expanded_path = os.path.expanduser(path)
    if not os.path.exists(expanded_path):
        raise ValidationError(f"Path does not exist: {path}")
    if not os.path.isdir(expanded_path):
        raise ValidationError(f"Path is not a directory: {path}")


def validate_marker(marker: Dict[str, Any]) -> None:
    """Validate a marker configuration.

    Args:
        marker: Dictionary with name, icon_svg, and color fields.

    Raises:
        ValidationError: If any field is invalid.
    """
    name = marker.get('name', '')
    if not name or not name.strip():
        raise ValidationError("Marker name cannot be empty")

    color = marker.get('color', '')
    if not _is_valid_hex_color(color):
        raise ValidationError(f"Invalid color format: {color}. Must be #RRGGBB")

    icon_svg = marker.get('icon_svg', '')
    if not _is_valid_icon(icon_svg):
        raise ValidationError(
            f"Invalid icon: {icon_svg}. Must be 'heroicons:<name>' or valid SVG"
        )


def validate_parallelism(n: Any) -> None:
    """Validate parallelism value is an integer between 1 and 8.

    Args:
        n: The parallelism value to validate.

    Raises:
        ValidationError: If the value is invalid.
    """
    if not isinstance(n, int):
        raise ValidationError(f"Parallelism must be an integer, got {type(n).__name__}")
    if n < 1 or n > 8:
        raise ValidationError(f"Parallelism must be between 1 and 8, got {n}")


def validate_captioning_parallelism(n: Any) -> None:
    """Validate captioning parallelism value is an integer between 1 and 50.

    Args:
        n: The parallelism value to validate.

    Raises:
        ValidationError: If the value is invalid.
    """
    if not isinstance(n, int):
        raise ValidationError(f"Parallelism must be an integer, got {type(n).__name__}")
    if n < 1 or n > 50:
        raise ValidationError(f"Captioning parallelism must be between 1 and 50, got {n}")


def validate_confidence(value: Any) -> None:
    """Validate confidence threshold is a float between 0.0 and 1.0.

    Args:
        value: The confidence value to validate.

    Raises:
        ValidationError: If the value is invalid.
    """
    if not isinstance(value, (int, float)):
        raise ValidationError(f"Confidence must be a number, got {type(value).__name__}")
    if value < 0.0 or value > 1.0:
        raise ValidationError(f"Confidence must be between 0.0 and 1.0, got {value}")


def validate_max_faces(n: Any) -> None:
    """Validate max faces is an integer between 1 and 50.

    Args:
        n: The max faces value to validate.

    Raises:
        ValidationError: If the value is invalid.
    """
    if not isinstance(n, int):
        raise ValidationError(f"Max faces must be an integer, got {type(n).__name__}")
    if n < 1 or n > 50:
        raise ValidationError(f"Max faces must be between 1 and 50, got {n}")


def validate_folders(folders: List[Dict[str, Any]]) -> None:
    """Validate a list of folder configurations.

    Args:
        folders: List of folder configuration dictionaries.

    Raises:
        ValidationError: If any folder is invalid.
    """
    if not isinstance(folders, list):
        raise ValidationError("Folders must be a list")

    for i, folder in enumerate(folders):
        path = folder.get('path', '')
        if not path:
            raise ValidationError(f"Folder {i + 1}: path cannot be empty")
        validate_folder_path(path)


def validate_markers(markers: List[Dict[str, Any]]) -> None:
    """Validate a list of marker configurations.

    Args:
        markers: List of marker configuration dictionaries.

    Raises:
        ValidationError: If any marker is invalid.
    """
    if not isinstance(markers, list):
        raise ValidationError("Markers must be a list")

    names_seen = set()
    for i, marker in enumerate(markers):
        try:
            validate_marker(marker)
        except ValidationError as e:
            raise ValidationError(f"Marker {i + 1}: {e}")

        name = marker.get('name', '').lower()
        if name in names_seen:
            raise ValidationError(f"Marker {i + 1}: duplicate name '{name}'")
        names_seen.add(name)


def _is_valid_hex_color(color: str) -> bool:
    """Check if a string is a valid hex color (#RRGGBB)."""
    if not color:
        return False
    pattern = r'^#[0-9A-Fa-f]{6}$'
    return bool(re.match(pattern, color))


def _is_valid_icon(icon: str) -> bool:
    """Check if a string is a valid icon reference.

    Valid formats:
    - heroicons:<icon-name> (e.g., 'heroicons:heart')
    - SVG string starting with '<svg'
    """
    if not icon:
        return False

    # Check for heroicons reference
    if icon.startswith('heroicons:'):
        icon_name = icon[len('heroicons:'):]
        return bool(icon_name and icon_name.strip())

    # Check for SVG string
    if icon.strip().lower().startswith('<svg'):
        return True

    return False
