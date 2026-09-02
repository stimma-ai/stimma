"""Multi-device orchestration: the one place serving state is decided.

Owns the lifecycle that the config toggle, sign-in/out, and startup all
funnel through, so "serving" can never mean three different things in three
places.
"""
from __future__ import annotations

import platform as platform_module
from typing import Optional

from app_context import (
    BUNDLE_ID_BETA,
    BUNDLE_ID_CANARY,
    BUNDLE_ID_DEBUG,
    BUNDLE_ID_STABLE,
    get_bundle_id,
    get_sandbox,
)
from config import get_settings, reload_settings
from config_writer import patch_global_section
from core.logging import get_logger

from . import registry, server
from .auth import revoke_all_sessions
from .identity import cert_fingerprint, ensure_identity

log = get_logger(__name__)

_app = None
# Surfaced in status() so a failure to serve is visible in settings rather
# than silently leaving the toggle looking off.
_serving_error: Optional[str] = None


def set_app(app) -> None:
    """Hand the service the FastAPI app the serving listener should wrap."""
    global _app
    _app = app


_CHANNELS = {
    BUNDLE_ID_STABLE: "production",
    BUNDLE_ID_BETA: "beta",
    BUNDLE_ID_CANARY: "canary",
    BUNDLE_ID_DEBUG: "debug",
}


def channel_name() -> str:
    """Release channel for this install, from its bundle id."""
    bundle = get_bundle_id()
    if bundle in _CHANNELS:
        return _CHANNELS[bundle]
    # Sandboxed dev bundles append a suffix (…debug.mda); fall back to the
    # longest known prefix rather than reporting the whole id.
    for known, name in _CHANNELS.items():
        if bundle.startswith(known + "."):
            return name
    return "unknown"


def sandbox_name() -> str:
    return get_sandbox()


def platform_name() -> str:
    system = platform_module.system().lower()
    if system == "darwin":
        return "darwin"
    if system == "windows":
        return "win32"
    return "linux"


def _patch_multi_device(**changes) -> None:
    """Merge into the multi_device section.

    patch_global_section replaces a section wholesale, so read-modify-write
    the current values rather than dropping the fields we are not setting.
    """
    current = get_settings().multi_device.model_dump()
    current.update(changes)
    patch_global_section("multi_device", current)
    reload_settings()


def ensure_persisted_identity() -> tuple[str, str, str, str]:
    """Identity for this install, minting and saving it on first use."""
    md = get_settings().multi_device
    device_id, name, cert_pem, key_pem = ensure_identity(md)
    if (
        md.device_id != device_id
        or md.device_name != name
        or md.cert_pem != cert_pem
        or md.key_pem != key_pem
    ):
        _patch_multi_device(
            device_id=device_id, device_name=name, cert_pem=cert_pem, key_pem=key_pem
        )
    return device_id, name, cert_pem, key_pem


async def register_now() -> Optional[list[dict]]:
    """Publish current state to the registry and return the account roster.

    When serving is off this is an UNREGISTER: the registry drops our row.
    An install the user has not offered has no business appearing in the
    picker on their other machines, so "not serving" and "not listed" are the
    same state rather than two that can drift apart.
    """
    settings = get_settings()
    md = settings.multi_device
    device_id, name, cert_pem, _key = ensure_persisted_identity()

    serving = server.is_serving()
    routes = registry.build_routes(server.serving_port() or md.port) if serving else []

    return await registry.register(
        device_id=device_id,
        name=name,
        platform=platform_name(),
        channel=channel_name(),
        sandbox=sandbox_name(),
        serving=serving,
        routes=routes,
        cert_fingerprint=cert_fingerprint(cert_pem) if serving else None,
    )


async def apply_serving(enabled: bool) -> dict:
    """Turn serving on or off, persist it, and republish to the registry."""
    global _serving_error
    if _app is None:
        raise RuntimeError("multi-device service has no app")
    _serving_error = None

    device_id, name, cert_pem, key_pem = ensure_persisted_identity()
    md = get_settings().multi_device

    if enabled:
        # Prefer an explicitly configured port, else the one we bound last
        # time, else let the OS choose. Whatever we land on is remembered and
        # published, so the user never arbitrates a port.
        preferred = md.port or md.last_port or 0
        bound = await server.start_serving(_app, cert_pem, key_pem, preferred, device_id)
        if bound != md.last_port:
            _patch_multi_device(last_port=bound)
        registry.start_heartbeat(register_now)
    else:
        await server.stop_serving()
        registry.stop_heartbeat()
        # Stopping serving is one of the two ways to genuinely cut a device
        # off, so it must invalidate the sessions it handed out.
        revoke_all_sessions()

    _patch_multi_device(serving=enabled)

    await register_now()
    await notify_devices_changed()
    return await status()


async def rename(name: str) -> dict:
    """Set this device's display name and republish it."""
    ensure_persisted_identity()
    _patch_multi_device(device_name=name)
    await register_now()
    await notify_devices_changed()
    return await status()


async def notify_devices_changed() -> None:
    """Tell this window the roster moved.

    A nudge, not a payload: Electron holds the cached device list and is the
    one that must re-read it, so the renderer re-asks through Electron rather
    than being handed rows that main would not have seen.
    """
    from utils.websocket import ws_manager

    try:
        await ws_manager.broadcast("multi_device_changed", {}, include_profile=False)
    except Exception as exc:
        log.warning("multi-device: could not broadcast roster change", error=str(exc))


async def status() -> dict:
    settings = get_settings()
    md = settings.multi_device
    device_id, name, cert_pem, _key = ensure_persisted_identity()
    serving = server.is_serving()

    port = server.serving_port() or md.last_port or md.port
    return {
        "deviceId": device_id,
        "deviceName": name,
        "platform": platform_name(),
        "channel": channel_name(),
        "sandbox": sandbox_name(),
        "serving": serving,
        "port": port,
        "routes": registry.build_routes(port) if serving else [],
        "certFingerprint": cert_fingerprint(cert_pem) if serving else None,
        "servingError": _serving_error,
    }


async def start_if_enabled() -> None:
    """Called at startup: resume serving if the user left it on."""
    settings = get_settings()
    if not settings.multi_device.serving:
        # Still register, so a signed-in install is discoverable as a
        # non-serving device and the account knows it exists.
        await register_now()
        return
    try:
        await apply_serving(True)
    except Exception as exc:
        global _serving_error
        _serving_error = str(exc)
        log.error("multi-device: failed to resume serving", error=str(exc))


async def shutdown() -> None:
    registry.stop_heartbeat()
    await server.stop_serving()
