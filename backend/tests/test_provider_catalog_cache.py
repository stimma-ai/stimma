"""Startup catalog caching against a real profile database."""

import pytest
from unittest.mock import AsyncMock
from providers.registry import ProviderRegistry
from tests.test_provider_registry import MockProvider, _make_tool


@pytest.mark.asyncio
async def test_tool_cache_batches_reads_and_preserves_retired_descriptors(db_session, monkeypatch):
    """Catalog refresh uses one read and keeps retired tools for lineage."""
    from database import CachedProviderTool
    from sqlalchemy import event, select

    instance = ProviderRegistry()
    monkeypatch.setattr(instance, '_get_db_session_makers', AsyncMock(return_value=[db_session]))
    provider = MockProvider('startup-cache', [_make_tool('first'), _make_tool('second')])
    await instance._cache_tools_to_db(provider, provider._tools)

    async with db_session() as session:
        engine = session.bind.sync_engine
    reads = []

    def record_reads(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith('SELECT') and 'cached_provider_tools' in statement:
            reads.append(statement)

    event.listen(engine, 'before_cursor_execute', record_reads)
    try:
        changed = _make_tool('first')
        changed.name = 'Updated name'
        await instance._cache_tools_to_db(provider, [changed])
    finally:
        event.remove(engine, 'before_cursor_execute', record_reads)
    assert len(reads) == 1

    async with db_session() as session:
        rows = (await session.scalars(select(CachedProviderTool).where(
            CachedProviderTool.provider_id == provider.provider_id
        ))).all()
        cached = {row.tool_id: row for row in rows}
        first_id, second_id = cached['first'].id, cached['second'].id
        assert cached['first'].name == 'Updated name'
        assert cached['first'].deleted_at is None
        assert cached['second'].deleted_at is not None

    await instance._cache_tools_to_db(provider, provider._tools)
    async with db_session() as session:
        rows = (await session.scalars(select(CachedProviderTool).where(
            CachedProviderTool.provider_id == provider.provider_id
        ))).all()
        assert {row.id for row in rows} == {first_id, second_id}
        assert all(row.deleted_at is None for row in rows)
