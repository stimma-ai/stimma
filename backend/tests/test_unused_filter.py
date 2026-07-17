"""
Tests for the Unused ("dead end") asset filter.

An asset is Unused when it is a generated leaf nobody ever did anything with:
- no lineage child belonging to a live asset (and no bare-media children)
- not embedded in / linked from a live container revision
- no live marker (non-suppressed), tag, board, or project membership
- not created by, or referenced from, a live chat
- only a single live revision
"""

from datetime import datetime

from httpx import AsyncClient
from sqlalchemy import select

from database import (
    Asset,
    AssetMarker,
    AssetRevision,
    AssetTag,
    Chat,
    ChatItem,
    ContainerMember,
    Marker,
    MediaLineage,
    Tag,
)
from tests.helpers.media import create_media_item


async def _make_asset(session, **kwargs):
    """Create a materialized generated asset; returns (media, asset_id)."""
    kwargs.setdefault("generation_metadata", '{"prompt": "test", "source": "stimma"}')
    media = await create_media_item(session, materialize_asset=True, **kwargs)
    asset_id = await session.scalar(
        select(AssetRevision.asset_id).where(AssetRevision.primary_media_id == media.id)
    )
    assert asset_id is not None
    return media, asset_id


async def _trash_asset(session, asset_id):
    asset = await session.get(Asset, asset_id)
    asset.state = "trashed"
    asset.deleted_at = datetime.utcnow()
    await session.commit()


async def _browse_ids(client: AsyncClient, **params) -> set[int]:
    response = await client.get(
        "/api/assets/browse", params={"page_size": 200, **params}
    )
    assert response.status_code == 200
    return {item["asset_id"] for item in response.json()["items"]}


class TestUnusedFilter:
    async def test_plain_generated_asset_is_unused(self, client, db_session):
        async with db_session() as session:
            _, asset_id = await _make_asset(session)

        assert asset_id in await _browse_ids(client, is_unused=True)
        assert asset_id not in await _browse_ids(client, is_unused=False)
        # No filter returns it either way
        assert asset_id in await _browse_ids(client)

    async def test_imported_asset_is_never_unused(self, client, db_session):
        async with db_session() as session:
            # No generation metadata => imported payload (user's own file)
            _, asset_id = await _make_asset(session, generation_metadata=None)

        assert asset_id not in await _browse_ids(client, is_unused=True)
        assert asset_id in await _browse_ids(client, is_unused=False)

    async def test_tagged_asset_is_not_unused(self, client, db_session):
        async with db_session() as session:
            _, asset_id = await _make_asset(session)
            tag = Tag(tag_text=f"unused-test-{asset_id}")
            session.add(tag)
            await session.flush()
            session.add(AssetTag(asset_id=asset_id, tag_id=tag.id))
            await session.commit()

        assert asset_id not in await _browse_ids(client, is_unused=True)
        assert asset_id in await _browse_ids(client, is_unused=False)

    async def test_soft_deleted_tag_does_not_protect(self, client, db_session):
        async with db_session() as session:
            _, asset_id = await _make_asset(session)
            tag = Tag(tag_text=f"unused-deleted-{asset_id}")
            session.add(tag)
            await session.flush()
            session.add(
                AssetTag(asset_id=asset_id, tag_id=tag.id, deleted_at=datetime.utcnow())
            )
            await session.commit()

        assert asset_id in await _browse_ids(client, is_unused=True)

    async def test_marker_protects_but_suppressed_does_not(self, client, db_session):
        async with db_session() as session:
            _, marked_id = await _make_asset(session)
            _, suppressed_id = await _make_asset(session)
            marker = Marker(
                name=f"unused-marker-{marked_id}", icon_svg="<svg/>", color="#fff"
            )
            session.add(marker)
            await session.flush()
            session.add(
                AssetMarker(asset_id=marked_id, marker_id=marker.id, source="manual")
            )
            session.add(
                AssetMarker(
                    asset_id=suppressed_id, marker_id=marker.id, source="suppressed"
                )
            )
            await session.commit()

        unused = await _browse_ids(client, is_unused=True)
        assert marked_id not in unused
        assert suppressed_id in unused

    async def test_lineage_child_liveness_controls_unused(self, client, db_session):
        async with db_session() as session:
            parent, parent_asset_id = await _make_asset(session)
            child, child_asset_id = await _make_asset(session)
            session.add(
                MediaLineage(
                    media_id=child.id,
                    source_media_id=parent.id,
                    source_order=0,
                    task_type="image-to-image",
                    relationship_type="derived",
                )
            )
            await session.commit()

        # Live child protects the parent; the child itself is the unused leaf
        unused = await _browse_ids(client, is_unused=True)
        assert parent_asset_id not in unused
        assert child_asset_id in unused

        # Trashing the child releases the parent back to unused
        async with db_session() as session:
            await _trash_asset(session, child_asset_id)

        assert parent_asset_id in await _browse_ids(client, is_unused=True)

    async def test_bare_media_child_protects_parent(self, client, db_session):
        async with db_session() as session:
            parent, parent_asset_id = await _make_asset(session)
            # Bare contextual media child (no asset): conservatively protects the parent
            bare_child = await create_media_item(session, materialize_asset=False)
            session.add(
                MediaLineage(
                    media_id=bare_child.id,
                    source_media_id=parent.id,
                    source_order=0,
                    task_type="image-to-image",
                    relationship_type="derived",
                )
            )
            await session.commit()

        assert parent_asset_id not in await _browse_ids(client, is_unused=True)

    async def test_chat_reference_protects_until_chat_deleted(self, client, db_session):
        async with db_session() as session:
            _, asset_id = await _make_asset(session)
            chat = Chat(name="Unused filter test chat")
            session.add(chat)
            await session.flush()
            chat_id = chat.id
            session.add(
                ChatItem(chat_id=chat_id, item_type="generated_media", asset_id=asset_id)
            )
            await session.commit()

        assert asset_id not in await _browse_ids(client, is_unused=True)

        async with db_session() as session:
            chat = await session.get(Chat, chat_id)
            chat.deleted_at = datetime.utcnow()
            await session.commit()

        assert asset_id in await _browse_ids(client, is_unused=True)

    async def test_chat_json_asset_ids_reference_protects(self, client, db_session):
        async with db_session() as session:
            _, asset_id = await _make_asset(session)
            chat = Chat(name="Unused filter json ref chat")
            session.add(chat)
            await session.flush()
            session.add(
                ChatItem(
                    chat_id=chat.id,
                    item_type="assistant_message",
                    asset_ids=f"[{asset_id}]",
                )
            )
            await session.commit()

        assert asset_id not in await _browse_ids(client, is_unused=True)

    async def test_chat_created_media_protects(self, client, db_session):
        async with db_session() as session:
            chat = Chat(name="Unused filter creator chat")
            session.add(chat)
            await session.flush()
            chat_item = ChatItem(chat_id=chat.id, item_type="generated_media")
            session.add(chat_item)
            await session.flush()

            media, asset_id = await _make_asset(session)
            media.chat_item_id = chat_item.id
            await session.commit()

        assert asset_id not in await _browse_ids(client, is_unused=True)

    async def test_live_container_membership_protects(self, client, db_session):
        async with db_session() as session:
            _, member_asset_id = await _make_asset(session)
            container_media, container_asset_id = await _make_asset(
                session, file_format="stimmaset.json"
            )
            container_revision_id = await session.scalar(
                select(AssetRevision.id).where(
                    AssetRevision.primary_media_id == container_media.id
                )
            )
            session.add(
                ContainerMember(
                    container_revision_id=container_revision_id,
                    linked_asset_id=member_asset_id,
                    member_order=0,
                )
            )
            await session.commit()

        assert member_asset_id not in await _browse_ids(client, is_unused=True)

        # Trashing the container releases the member
        async with db_session() as session:
            await _trash_asset(session, container_asset_id)

        assert member_asset_id in await _browse_ids(client, is_unused=True)

    async def test_multiple_revisions_protect(self, client, db_session):
        async with db_session() as session:
            media, asset_id = await _make_asset(session)
            revision_media = await create_media_item(session, materialize_asset=False)
            first_revision_id = await session.scalar(
                select(AssetRevision.id).where(
                    AssetRevision.primary_media_id == media.id
                )
            )
            session.add(
                AssetRevision(
                    asset_id=asset_id,
                    parent_revision_id=first_revision_id,
                    primary_media_id=revision_media.id,
                    revision_number=2,
                )
            )
            await session.commit()

        assert asset_id not in await _browse_ids(client, is_unused=True)

    async def test_filter_counts_include_unused(self, client, db_session):
        async with db_session() as session:
            _, asset_id = await _make_asset(session)

        response = await client.get("/api/assets/filter-counts")
        assert response.status_code == 200
        data = response.json()
        assert "unused" in data
        assert data["unused"] >= 1

    async def test_browse_ids_endpoint_honors_unused(self, client, db_session):
        async with db_session() as session:
            _, unused_asset_id = await _make_asset(session)
            _, tagged_asset_id = await _make_asset(session)
            tag = Tag(tag_text=f"unused-ids-{tagged_asset_id}")
            session.add(tag)
            await session.flush()
            session.add(AssetTag(asset_id=tagged_asset_id, tag_id=tag.id))
            await session.commit()

        response = await client.get(
            "/api/assets/browse/ids", params={"is_unused": "true"}
        )
        assert response.status_code == 200
        ids = set(response.json()["ids"])
        assert unused_asset_id in ids
        assert tagged_asset_id not in ids
