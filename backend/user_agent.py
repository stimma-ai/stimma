"""
User-Agent helper for requests to Stimma's own infrastructure.

Format (and the ONLY place the install ID ever leaves the machine):

    Stimma/<version> (<os>; <arch>; <branch>) install/<install_id>

Used on every backend request to our infra: telemetry, compliance/region,
feature flags, app/version (update check), and the cloud API. Server-side,
UA parsing is the single place identity/platform is read — request bodies
carry no install ID.

The install identifier is a random UUID, generated once per install and
persisted in config. It is disclosed in the privacy policy as used for
abuse prevention and service operation.
"""
import json
import os
import platform
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from core.logging import get_logger

log = get_logger(__name__)

_install_id: Optional[str] = None
_app_version: Optional[str] = None
_app_branch: Optional[str] = None


def get_os() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macos"
    elif system == "Windows":
        return "windows"
    return "linux"


def get_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "x64"
    return machine or "unknown"


def _read_tauri_conf() -> dict:
    """Read tauri.conf.json (available in source checkouts only)."""
    try:
        conf_path = Path(__file__).parent.parent / "src-tauri" / "tauri.conf.json"
        if conf_path.exists():
            return json.loads(conf_path.read_text())
    except Exception:
        pass
    return {}


def get_app_version() -> str:
    """Best-effort app version string.

    Resolution order: ``STIMMA_APP_VERSION`` env (set by the Tauri shell
    from its bundled version), tauri.conf.json (source checkouts), git
    short SHA for dev checkouts, else ``0.0.0``.
    """
    global _app_version
    if _app_version:
        return _app_version

    env_version = os.environ.get("STIMMA_APP_VERSION", "").strip()
    if env_version:
        _app_version = env_version
        return _app_version

    conf_version = _read_tauri_conf().get("version")
    from app_context import get_bundle_id, BUNDLE_ID_STABLE
    if get_bundle_id() != BUNDLE_ID_STABLE:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=Path(__file__).parent.parent,
            )
            if result.returncode == 0:
                _app_version = f"0.0.0-{result.stdout.strip()}"
                return _app_version
        except Exception:
            pass

    _app_version = conf_version or "0.0.0"
    return _app_version


def get_app_branch() -> str:
    """Release branch: ``production`` | ``beta`` | ``alpha`` | ``dev``.

    Derived from the bundle ID (patched per channel by release CI).
    Source builds and the debug channel report ``dev``.
    """
    global _app_branch
    if _app_branch:
        return _app_branch

    from app_context import get_bundle_id, BUNDLE_ID_STABLE
    bundle_id = get_bundle_id()
    if bundle_id == BUNDLE_ID_STABLE:
        branch = "production"
    elif bundle_id == f"{BUNDLE_ID_STABLE}.beta":
        branch = "beta"
    elif bundle_id == f"{BUNDLE_ID_STABLE}.alpha":
        branch = "alpha"
    else:
        branch = "dev"

    # Source builds are always 'dev' regardless of bundle id.
    from distribution import is_official
    if not is_official():
        branch = "dev"

    _app_branch = branch
    return _app_branch


def ensure_install_id() -> str:
    """Return the per-install UUID, generating and persisting it if needed."""
    global _install_id
    if _install_id:
        return _install_id

    try:
        from config import get_settings
        settings = get_settings()
        if settings.telemetry.install_id:
            _install_id = settings.telemetry.install_id
            return _install_id
    except Exception:
        pass

    new_id = str(uuid.uuid4())
    _install_id = new_id

    try:
        import config_writer
        from config import get_settings
        telemetry = get_settings().telemetry
        section = telemetry.model_dump()
        section["install_id"] = new_id
        config_writer.patch_global_section("telemetry", section)
        log.info("install_id generated")
    except Exception as e:
        log.info(f"failed to persist install_id: {e}")

    return new_id


def user_agent() -> str:
    """The Stimma User-Agent: exactly version/os/arch/branch/install-id."""
    return (
        f"Stimma/{get_app_version()} "
        f"({get_os()}; {get_arch()}; {get_app_branch()}) "
        f"install/{ensure_install_id()}"
    )


def ua_headers() -> dict:
    """Headers dict carrying the Stimma User-Agent."""
    return {"User-Agent": user_agent()}
