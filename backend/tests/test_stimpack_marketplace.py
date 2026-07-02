from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from routes import stimpack_marketplace


pytestmark = pytest.mark.asyncio


def _patch_avatar_route(monkeypatch, response_factory):
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["timeout"] = timeout
            return response_factory(url)

    monkeypatch.setattr(
        stimpack_marketplace,
        "get_settings",
        lambda: SimpleNamespace(cloud=SimpleNamespace(base_url="https://dev.stimma.ai/")),
    )
    monkeypatch.setattr(stimpack_marketplace, "with_cloud_access_headers", lambda: {"X-Test": "ok"})
    monkeypatch.setattr(stimpack_marketplace, "is_privacy_lockdown_enabled", lambda: False)
    monkeypatch.setattr(stimpack_marketplace.httpx, "AsyncClient", FakeAsyncClient)
    return captured


async def test_author_avatar_preserves_stored_avatars_prefix(monkeypatch):
    def response_factory(url: str):
        return httpx.Response(
            200,
            content=b"avatar-bytes",
            headers={"content-type": "image/webp"},
            request=httpx.Request("GET", url),
        )

    captured = _patch_avatar_route(monkeypatch, response_factory)

    response = await stimpack_marketplace.get_author_avatar("avatars/user-123/1775235946137")

    assert captured["url"] == "https://dev.stimma.ai/api/avatars/avatars/user-123/1775235946137"
    assert captured["headers"] == {"X-Test": "ok"}
    assert captured["timeout"] == 30.0
    assert response.body == b"avatar-bytes"
    assert response.media_type == "image/webp"


async def test_author_avatar_strips_full_api_avatar_path(monkeypatch):
    def response_factory(url: str):
        return httpx.Response(200, content=b"ok", request=httpx.Request("GET", url))

    captured = _patch_avatar_route(monkeypatch, response_factory)

    await stimpack_marketplace.get_author_avatar("/api/avatars/avatars/user-123/1775235946137")

    assert captured["url"] == "https://dev.stimma.ai/api/avatars/avatars/user-123/1775235946137"


async def test_author_avatar_returns_clean_404_for_missing_cloud_avatar(monkeypatch):
    def response_factory(url: str):
        return httpx.Response(404, request=httpx.Request("GET", url))

    captured = _patch_avatar_route(monkeypatch, response_factory)

    with pytest.raises(HTTPException) as exc_info:
        await stimpack_marketplace.get_author_avatar("avatars/missing")

    assert captured["url"] == "https://dev.stimma.ai/api/avatars/avatars/missing"
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Avatar not found"
