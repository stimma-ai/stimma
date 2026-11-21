"""Server-side marketplace sync: who it runs for, lockdown, and the pass itself."""
from types import SimpleNamespace

import pytest

import stimpack_sync
from core import middleware
from core.profile_context import get_current_profile
from routes import stimpack_marketplace as market


pytestmark = pytest.mark.asyncio


def _profiles(monkeypatch, *profiles):
    import config
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(profiles=list(profiles)))


async def test_eligible_profiles_are_pinless_or_unlocked(monkeypatch):
    _profiles(
        monkeypatch,
        SimpleNamespace(id="open", pin_hash=None, pin_idle_timeout_minutes=30),
        SimpleNamespace(id="locked", pin_hash="h1", pin_idle_timeout_minutes=30),
        SimpleNamespace(id="unlocked", pin_hash="h2", pin_idle_timeout_minutes=30),
        SimpleNamespace(id="idle", pin_hash="h3", pin_idle_timeout_minutes=5),
        SimpleNamespace(id="pin-changed", pin_hash="new", pin_idle_timeout_minutes=30),
    )
    now = middleware.time.monotonic()
    monkeypatch.setattr(middleware, "_pin_last_verified", {
        "unlocked": ("h2", now - 60),
        "idle": ("h3", now - 6 * 60),  # past its idle timeout: locked again
        "pin-changed": ("old", now),  # verified against a PIN that no longer applies
    })
    assert stimpack_sync.eligible_profile_ids() == ["open", "unlocked"]


async def test_sync_profile_installs_then_updates_in_profile_scope(monkeypatch):
    calls = []
    monkeypatch.setattr(stimpack_sync, "is_privacy_lockdown_enabled", lambda: False)

    async def auto_install():
        calls.append(("auto-install", get_current_profile()))
        return {"installed": ["stimma-essentials"]}

    async def check_updates():
        calls.append(("check", get_current_profile()))
        return {"updates": [{"name": "stimma-docs", "newVersion": 4}, {"name": "broken"}]}

    async def update(name):
        calls.append(("update", name, get_current_profile()))
        if name == "broken":
            raise RuntimeError("download failed")
        return {}

    monkeypatch.setattr(market, "run_auto_install", auto_install)
    monkeypatch.setattr(market, "check_updates", check_updates)
    monkeypatch.setattr(market, "update_from_marketplace", update)
    result = await stimpack_sync.sync_profile("p1")
    assert result == {"installed": ["stimma-essentials"], "updated": ["stimma-docs"], "changed": True}
    assert calls == [
        ("auto-install", "p1"), ("check", "p1"),
        ("update", "stimma-docs", "p1"), ("update", "broken", "p1"),
    ]


async def test_sync_does_nothing_under_privacy_lockdown(monkeypatch):
    monkeypatch.setattr(stimpack_sync, "is_privacy_lockdown_enabled", lambda: True)

    async def boom(*a, **k):
        raise AssertionError("no cloud calls under lockdown")

    monkeypatch.setattr(market, "run_auto_install", boom)
    monkeypatch.setattr(market, "check_updates", boom)
    assert await stimpack_sync.sync_profile("p1") == {"installed": [], "updated": [], "changed": False}
    monkeypatch.setattr(market, "is_privacy_lockdown_enabled", lambda: True)
    assert (await market.sync_marketplace_stimpacks())["changed"] is False


async def test_interval_is_hours_apart():
    assert stimpack_sync.SYNC_INTERVAL_SECONDS >= 60 * 60
