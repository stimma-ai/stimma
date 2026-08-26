"""Legacy refresh-token migration.

Before the bundle id was forwarded to the backend sidecar, official builds
stored their cloud refresh token under the debug bundle id's credential key.
_get_refresh_token() migrates that token to the current key on first miss so
the bundle-id fix doesn't sign every existing user out.
"""

from typing import Optional

import pytest

import auth_storage
from app_context import (
    BUNDLE_ID_DEBUG,
    BUNDLE_ID_STABLE,
    get_bundle_id,
    get_sandbox,
    set_app_context,
)


class StubStore:
    backend_name = "stub"

    def __init__(self, current: Optional[str] = None, legacy: Optional[str] = None):
        self.current = current
        self.legacy = legacy

    def get_refresh_token(self) -> Optional[str]:
        return self.current

    def set_refresh_token(self, token: str) -> None:
        self.current = token

    def clear_refresh_token(self) -> None:
        self.current = None

    def get_legacy_refresh_token(self) -> Optional[str]:
        return self.legacy

    def clear_legacy_refresh_token(self) -> None:
        self.legacy = None


@pytest.fixture
def restore_app_context():
    bundle_id, sandbox = get_bundle_id(), get_sandbox()
    yield
    set_app_context(bundle_id, sandbox)


@pytest.fixture
def isolated_storage(monkeypatch, restore_app_context):
    monkeypatch.setattr(auth_storage, "_memory_refresh_token", None)
    monkeypatch.setattr(auth_storage, "_get_file_fallback_store", lambda: None)

    def use(store: StubStore) -> StubStore:
        monkeypatch.setattr(auth_storage, "_get_token_store", lambda: store)
        return store

    return use


def test_migrates_legacy_token_on_official_bundle(isolated_storage):
    set_app_context(BUNDLE_ID_STABLE)
    store = isolated_storage(StubStore(current=None, legacy="legacy-token"))

    assert auth_storage._get_refresh_token() == "legacy-token"
    # Re-saved under the current key, legacy entry removed.
    assert store.current == "legacy-token"
    assert store.legacy is None


def test_current_key_wins_without_migration(isolated_storage):
    set_app_context(BUNDLE_ID_STABLE)
    store = isolated_storage(StubStore(current="current-token", legacy="stale-token"))

    assert auth_storage._get_refresh_token() == "current-token"
    assert store.legacy == "stale-token"  # untouched


def test_no_migration_on_debug_bundle(isolated_storage):
    set_app_context(BUNDLE_ID_DEBUG)
    store = isolated_storage(StubStore(current=None, legacy="legacy-token"))

    assert auth_storage._get_refresh_token() is None
    assert store.legacy == "legacy-token"


def test_clear_also_removes_legacy_key(isolated_storage):
    set_app_context(BUNDLE_ID_STABLE)
    store = isolated_storage(StubStore(current="current-token", legacy="legacy-token"))

    auth_storage._clear_refresh_token()
    # Sign-out must clear both keys, or the next launch would resurrect the
    # session through the migration path.
    assert store.current is None
    assert store.legacy is None
