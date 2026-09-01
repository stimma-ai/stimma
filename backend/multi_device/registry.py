"""Cloud device-registry client.

Registers this install with the account's registry and reads back its peers.
Sibling of ``cloud_events.py``: same account credentials, same "the cloud is
a nudge, not a source of truth" posture.

The registry is DISCOVERY ONLY. It learns where a device can be reached and
what its TLS fingerprint is; media and asset bytes never pass through it.

Registration is FUNCTIONAL data, not analytics, so it is deliberately not
gated on telemetry consent — multi-device has to work with telemetry off.
Privacy Lockdown still disables it, because lockdown disables sign-in.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from cloud_runtime import cloud_access_headers
from config import get_settings
from core.logging import get_logger
from privacy_lockdown import is_privacy_lockdown_enabled

from .identity import is_tailscale_address, local_addresses

log = get_logger(__name__)

HEARTBEAT_INTERVAL_S = 120
_heartbeat_task: Optional[asyncio.Task] = None


def build_routes(port: int) -> list[dict]:
    """Route candidates for this host, LAN first then tailnet.

    Order is the connect order on the other side: a LAN link is faster and
    lower-latency than going out over the tailnet to reach the same machine.
    """
    lan: list[dict] = []
    tailscale: list[dict] = []
    for addr in local_addresses():
        entry = {"kind": "tailscale" if is_tailscale_address(addr) else "lan", "host": addr, "port": port}
        (tailscale if entry["kind"] == "tailscale" else lan).append(entry)
    return (lan + tailscale)[:8]  # registry bounds the list at 8


async def _cloud_headers() -> Optional[dict]:
    """Account token plus, when configured, Cloudflare Access service-token
    headers — private cloud targets sit behind Access and would otherwise
    answer every call with a login redirect."""
    from firebase_auth import get_valid_id_token

    token = await get_valid_id_token()
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        **cloud_access_headers(),
    }


def _base_url() -> str:
    return get_settings().cloud.base_url.rstrip("/")


async def register(
    *,
    device_id: str,
    name: str,
    platform: str,
    serving: bool,
    routes: list[dict],
    cert_fingerprint: Optional[str],
    channel: Optional[str] = None,
    sandbox: Optional[str] = None,
    app_version: Optional[str] = None,
) -> Optional[list[dict]]:
    """Upsert this device; returns the account's other devices, or None."""
    if is_privacy_lockdown_enabled():
        return None

    headers = await _cloud_headers()
    if not headers:
        log.debug("multi-device: not signed in, skipping registration")
        return None

    payload = {
        "deviceId": device_id,
        "name": name,
        "platform": platform,
        # Channel and sandbox travel with the device because a debug or
        # sandboxed install is a DIFFERENT LIBRARY on the same machine.
        # Without them two rows look identical and you can connect to the
        # wrong one and wonder where your assets went.
        "channel": channel,
        "sandbox": sandbox,
        "serving": serving,
        "routes": routes,
        "certFingerprint": cert_fingerprint,
        "appVersion": app_version,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{_base_url()}/api/devices/register", headers=headers, json=payload
            )
            response.raise_for_status()
            return response.json().get("devices", [])
    except Exception as exc:
        # Discovery being briefly unavailable is not an error worth surfacing:
        # an established link keeps working, and the next heartbeat retries.
        log.warning("multi-device: registration failed", error=str(exc))
        return None


async def list_devices() -> Optional[list[dict]]:
    if is_privacy_lockdown_enabled():
        return None
    headers = await _cloud_headers()
    if not headers:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{_base_url()}/api/devices", headers=headers)
            response.raise_for_status()
            return response.json().get("devices", [])
    except Exception as exc:
        log.warning("multi-device: device list failed", error=str(exc))
        return None


async def remove_device(device_id: str) -> bool:
    headers = await _cloud_headers()
    if not headers:
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.delete(
                f"{_base_url()}/api/devices/{device_id}", headers=headers
            )
            return response.status_code == 200
    except Exception as exc:
        log.warning("multi-device: device removal failed", error=str(exc))
        return False


def start_heartbeat(register_now) -> None:
    """Keep last_seen fresh (and routes current) while serving."""
    global _heartbeat_task
    stop_heartbeat()

    async def loop() -> None:
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL_S)
                await register_now()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("multi-device: heartbeat failed", error=str(exc))

    _heartbeat_task = asyncio.create_task(loop())


def stop_heartbeat() -> None:
    global _heartbeat_task
    if _heartbeat_task is not None:
        _heartbeat_task.cancel()
        _heartbeat_task = None
