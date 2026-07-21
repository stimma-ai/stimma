"""Tool display identity and durable provider-cache behavior."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from database import Base, CachedProviderTool, Database
from providers.base import ToolDescriptor
from providers.registry import ProviderRegistry
from tool_display import (
    canonical_tool_id,
    expand_tool_id_aliases,
    resolve_tool_display_metadata,
)


def test_comfyui_tool_identity_normalizes_historical_formats():
    canonical = "comfyui:qwen-image"
    assert canonical_tool_id("comfyui:text-to-image:qwen-image") == canonical
    assert (
        canonical_tool_id("builtin:comfyui:image-to-image:qwen-image")
        == canonical
    )
    aliases = set(expand_tool_id_aliases([canonical]))
    assert canonical in aliases
    assert "comfyui:text-to-image:qwen-image" in aliases
    assert "builtin:comfyui:image-to-image:qwen-image" in aliases


@pytest.mark.asyncio
async def test_connected_tool_resolves_legacy_lineage_without_database_cache(
    db_session, monkeypatch
):
    provider = SimpleNamespace(provider_id="comfyui", provider_name="ComfyUI")
    descriptor = ToolDescriptor(
        id="connected-proof",
        name="Connected Proof",
        parameter_schema={},
        output_schema={},
        task_types=["text-to-image", "image-to-image"],
    )
    fake_registry = SimpleNamespace(
        list_all_tools=lambda: [("comfyui:connected-proof", provider, descriptor)]
    )
    monkeypatch.setattr(
        ProviderRegistry,
        "get_instance",
        classmethod(lambda _cls: fake_registry),
    )

    async with db_session() as session:
        resolved = await resolve_tool_display_metadata(
            session,
            ["comfyui:text-to-image:connected-proof"],
        )

    assert resolved["comfyui:text-to-image:connected-proof"] == {
        "canonical_tool_id": "comfyui:connected-proof",
        "name": "Connected Proof",
        "provider_name": "ComfyUI",
        "provider_id": "comfyui",
    }


@pytest.mark.asyncio
async def test_provider_cache_syncs_profiles_and_retires_without_deleting(
    tmp_path, monkeypatch
):
    databases = [
        Database(str(tmp_path / "first.db")),
        Database(str(tmp_path / "second.db")),
    ]
    for database in databases:
        async with database.async_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    registry = ProviderRegistry.get_instance()

    async def session_makers():
        return [database.async_session_maker for database in databases]

    monkeypatch.setattr(registry, "_get_db_session_makers", session_makers)
    provider = SimpleNamespace(provider_id="cache-proof", provider_name="Cache Proof")
    descriptor = ToolDescriptor(
        id="generator",
        name="Cache Proof Generator",
        parameter_schema={},
        output_schema={},
        task_type="text-to-image",
    )

    try:
        await registry._cache_tools_to_db(provider, [descriptor])
        for database in databases:
            async with database.async_session_maker() as session:
                cached = await session.scalar(select(CachedProviderTool))
                assert cached.name == "Cache Proof Generator"
                assert cached.deleted_at is None

        await registry._cache_tools_to_db(provider, [])
        for database in databases:
            async with database.async_session_maker() as session:
                cached = await session.scalar(select(CachedProviderTool))
                assert cached is not None
                assert cached.deleted_at is not None
    finally:
        for database in databases:
            await database.async_engine.dispose()
