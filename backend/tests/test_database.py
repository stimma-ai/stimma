"""Tests for the Database class (database.py)."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import Base, Database


@pytest.fixture
def db_path(tmp_path):
    """Return a path for a temp database file."""
    return str(tmp_path / "test.db")


@pytest.fixture
async def db(db_path):
    """Create a Database instance with tables created, then dispose after test."""
    database = Database(db_path)
    # Create all ORM tables (including _meta)
    async with database.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield database
    await database.async_engine.dispose()


class TestDatabaseInit:
    """Tests for Database construction."""

    def test_engine_url(self, db_path):
        """Engine URL contains the database path."""
        database = Database(db_path)
        assert str(database.async_engine.url) == f"sqlite+aiosqlite:///{db_path}"

    def test_session_maker_expire_on_commit(self, db_path):
        """Session maker has expire_on_commit=False."""
        database = Database(db_path)
        assert database.async_session_maker.kw.get("expire_on_commit") is False


class TestInitDb:
    """Tests for init_db() — WAL mode, PRAGMA, and GUID generation."""

    async def test_wal_mode(self, db):
        """init_db sets WAL journal mode."""
        await db.init_db()
        async with db.async_engine.connect() as conn:
            result = await conn.execute(text("PRAGMA journal_mode"))
            assert result.scalar() == "wal"

    async def test_busy_timeout(self, db):
        """init_db sets busy_timeout to 30000ms."""
        await db.init_db()
        async with db.async_engine.connect() as conn:
            result = await conn.execute(text("PRAGMA busy_timeout"))
            assert result.scalar() == 30000

    async def test_guid_generated(self, db):
        """init_db generates an 8-char GUID."""
        await db.init_db()
        guid = db.db_guid
        assert isinstance(guid, str)
        assert len(guid) == 8

    async def test_guid_stored_in_meta(self, db):
        """GUID is persisted in the _meta table."""
        await db.init_db()
        async with db.async_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT value FROM _meta WHERE key = 'db_guid'")
            )
            assert result.scalar() == db.db_guid

    async def test_guid_idempotent(self, db):
        """Calling init_db twice reuses the same GUID."""
        await db.init_db()
        first_guid = db.db_guid
        await db.init_db()
        assert db.db_guid == first_guid


class TestDbGuidProperty:
    """Tests for the db_guid property."""

    def test_raises_before_init(self, db_path):
        """Accessing db_guid before init_db raises RuntimeError."""
        database = Database(db_path)
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = database.db_guid


class TestGetSession:
    """Tests for get_session()."""

    async def test_yields_async_session(self, db):
        """get_session yields an AsyncSession."""
        await db.init_db()
        async for session in db.get_session():
            assert isinstance(session, AsyncSession)

    async def test_session_can_query(self, db):
        """Session can execute queries against the database."""
        await db.init_db()
        async for session in db.get_session():
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1


class TestSavepointWrites:
    """A write inside begin_nested() must wait for the lock, not fail at once."""

    async def test_write_after_read_in_savepoint_survives_concurrent_commit(self, db):
        """Another connection committing between the read and the write is not fatal.

        pysqlite opens no transaction before a SAVEPOINT, so SQLite starts a
        deferred one there. A read inside it pins a WAL snapshot; once another
        connection commits, upgrading that snapshot to a write fails at once with
        "database is locked" and the busy timeout never applies.
        """
        await db.init_db()
        async with db.async_engine.begin() as conn:
            await conn.execute(text("CREATE TABLE savepoint_probe (v INTEGER)"))

        async def other_writer():
            async with db.async_session_maker() as other:
                await other.execute(text("INSERT INTO _meta (key, value) VALUES ('probe', '1')"))
                await other.commit()

        async with db.async_session_maker() as session:
            async with session.begin_nested():
                await session.execute(text("SELECT count(*) FROM savepoint_probe"))
                # Another connection writes while this savepoint is open. It either
                # commits now (the old failure) or waits for our commit.
                writer = asyncio.create_task(other_writer())
                await asyncio.sleep(0.3)
                await session.execute(text("INSERT INTO savepoint_probe (v) VALUES (1)"))
            # The outer transaction keeps working after the savepoint, too.
            await session.execute(text("INSERT INTO savepoint_probe (v) VALUES (2)"))
            await session.commit()
        await asyncio.wait_for(writer, timeout=10)

        async with db.async_engine.connect() as conn:
            result = await conn.execute(text("SELECT count(*) FROM savepoint_probe"))
            assert result.scalar() == 2
            result = await conn.execute(text("SELECT value FROM _meta WHERE key = 'probe'"))
            assert result.scalar() == "1"

    async def test_rolled_back_savepoint_releases_the_write_lock(self, db):
        """A savepoint that fails before writing does not keep other writers waiting."""
        await db.init_db()
        async with db.async_engine.begin() as conn:
            await conn.execute(text("CREATE TABLE savepoint_probe (v INTEGER)"))

        async with db.async_session_maker() as session:
            with pytest.raises(RuntimeError):
                async with session.begin_nested():
                    await session.execute(text("SELECT count(*) FROM savepoint_probe"))
                    raise RuntimeError("caller error before any write")

            # The session stays open, as an agent's does between commits.
            async with db.async_session_maker() as other:
                await other.execute(text("INSERT INTO _meta (key, value) VALUES ('probe', '1')"))
                await asyncio.wait_for(other.commit(), timeout=5)

            await session.execute(text("SELECT count(*) FROM savepoint_probe"))
            await session.execute(text("INSERT INTO savepoint_probe (v) VALUES (1)"))
            await session.commit()

        async with db.async_engine.connect() as conn:
            result = await conn.execute(text("SELECT count(*) FROM savepoint_probe"))
            assert result.scalar() == 1
