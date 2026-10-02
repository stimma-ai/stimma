"""A project is its own small world: what you make in it lands in it.

Covers the backend half of the project-world contract: uploads and editor
saves attach to the project, top-level lists can ask for unscoped items only,
search labels results with their project, membership changes are broadcast,
and moving boards brings their assets along.
"""

import io

import pytest
from PIL import Image
from sqlalchemy import select

from database import ProjectAsset
from tests.helpers.media import create_media_item, create_test_media, generate_test_image


def _png_bytes(size=(16, 16), color=(10, 200, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def broadcasts(monkeypatch):
    """Capture every websocket broadcast made through the shared manager."""
    import utils.websocket as ws_module

    captured: list[tuple[str, dict]] = []

    async def record(event, data, *args, **kwargs):
        captured.append((event, data))

    monkeypatch.setattr(ws_module.ws_manager, "broadcast", record)
    return captured


def _events(captured, name):
    return [data for event, data in captured if event == name]


async def _project(client, name="P"):
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 200
    return response.json()["id"]


async def _project_media_ids(client, project_id):
    body = (await client.get(
        f"/api/assets/browse?project_id={project_id}&page_size=200"
    )).json()
    return {item["media_id"] for item in body["items"]}


async def _project_asset_rows(db_session, asset_id):
    async with db_session() as session:
        return set(await session.scalars(
            select(ProjectAsset.project_id).where(
                ProjectAsset.asset_id == asset_id,
                ProjectAsset.deleted_at.is_(None),
            )
        ))


class TestReferenceUploads:
    @pytest.mark.parametrize(
        "path,filename,mime",
        [("/api/generate/upload-reference", "ref.png", "image/png")],
    )
    async def test_upload_reference_attaches_to_project(self, client, path, filename, mime):
        project_id = await _project(client, "Uploads")
        response = await client.post(
            path,
            files={"file": (filename, _png_bytes(), mime)},
            data={"project_id": str(project_id)},
        )
        assert response.status_code == 200, response.text
        media_id = response.json()["media_id"]
        assert media_id in await _project_media_ids(client, project_id)

    async def test_upload_reference_without_project_stays_unfiled(self, client):
        response = await client.post(
            "/api/generate/upload-reference",
            files={"file": ("plain.png", _png_bytes(color=(1, 2, 3)), "image/png")},
        )
        assert response.status_code == 200, response.text
        media_id = response.json()["media_id"]
        unfiled = (await client.get("/api/assets/browse?scope=unfiled&page_size=200")).json()
        assert media_id in {item["media_id"] for item in unfiled["items"]}

    @pytest.mark.parametrize(
        "path",
        [
            "/api/generate/upload-reference",
            "/api/generate/upload-reference-video",
            "/api/generate/upload-reference-audio",
        ],
    )
    async def test_upload_reference_rejects_missing_project(self, client, path):
        response = await client.post(
            path,
            files={"file": ("ref.png", _png_bytes(), "image/png")},
            data={"project_id": "999999"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Project not found"

    async def test_upload_reference_rejects_deleted_project(self, client):
        project_id = await _project(client, "Gone")
        assert (await client.delete(f"/api/projects/{project_id}")).status_code == 200
        response = await client.post(
            "/api/generate/upload-reference",
            files={"file": ("ref.png", _png_bytes(), "image/png")},
            data={"project_id": str(project_id)},
        )
        assert response.status_code == 404

    async def test_unmaterialized_reference_joins_project_when_promoted(self, client, db_session):
        project_id = await _project(client, "Staged")
        response = await client.post(
            "/api/generate/upload-reference",
            files={"file": ("staged.png", _png_bytes(color=(9, 9, 9)), "image/png")},
            data={"project_id": str(project_id), "materialize_asset": "false"},
        )
        assert response.status_code == 200, response.text
        media_id = response.json()["media_id"]
        assert media_id not in await _project_media_ids(client, project_id)

        from asset_association_service import mirror_media_associations_to_asset
        from asset_service import create_asset_from_media

        async with db_session() as session:
            asset = await create_asset_from_media(session, media_id=media_id)
            await mirror_media_associations_to_asset(session, media_id=media_id, asset_id=asset.id)
            await session.commit()
        assert media_id in await _project_media_ids(client, project_id)


class TestSaveAsNew:
    async def _asset(self, db_session, tmp_path, name):
        from asset_service import create_asset_from_media

        async with db_session() as session:
            source = tmp_path / f"{name}.png"
            file_hash = generate_test_image(source, width=64, height=32)
            media = await create_media_item(
                session, file_path=source, file_hash=file_hash, width=64, height=32
            )
            asset = await create_asset_from_media(session, media_id=media.id)
            await session.commit()
            return asset.id, media.id

    async def _save(self, client, asset_id, media_id, **extra):
        document_id = (await client.post(
            "/api/image-stack/open", json={"asset_id": asset_id}
        )).json()["document_id"]
        data = {
            "source_media_id": str(media_id),
            "asset_id": str(asset_id),
            "working_document_id": str(document_id),
            "save_as_new": "true",
            **extra,
        }
        return await client.post(
            "/api/media/save-edit",
            files={"file": ("c.png", _png_bytes((64, 32)), "image/png")},
            data=data,
        )

    async def test_save_as_new_inherits_source_projects(
        self, client, db_session, tmp_path, broadcasts
    ):
        asset_id, media_id = await self._asset(db_session, tmp_path, "inherit")
        p = await _project(client, "Source P")
        q = await _project(client, "Source Q")
        gone = await _project(client, "Source gone")
        for pid in (p, q, gone):
            await client.post(f"/api/assets/batch/projects/{pid}", json={"asset_ids": [asset_id]})
        await client.delete(f"/api/projects/{gone}")

        response = await self._save(client, asset_id, media_id)
        assert response.status_code == 200, response.text
        new_asset = response.json()["asset_id"]
        assert new_asset != asset_id
        assert await _project_asset_rows(db_session, new_asset) == {p, q}
        added = [e for e in _events(broadcasts, "project_assets_changed") if e["asset_ids"] == [new_asset]]
        assert {e["project_id"] for e in added} == {p, q}

    async def test_save_as_new_adds_requested_project(self, client, db_session, tmp_path):
        asset_id, media_id = await self._asset(db_session, tmp_path, "requested")
        p = await _project(client, "Requested")
        response = await self._save(client, asset_id, media_id, project_id=str(p))
        assert response.status_code == 200, response.text
        assert await _project_asset_rows(db_session, response.json()["asset_id"]) == {p}
        # The source wasn't in P and stays out of it.
        assert await _project_asset_rows(db_session, asset_id) == set()

    async def test_save_as_new_rejects_missing_project(self, client, db_session, tmp_path):
        asset_id, media_id = await self._asset(db_session, tmp_path, "missing")
        response = await self._save(client, asset_id, media_id, project_id="999999")
        assert response.status_code == 404


class TestUnfiledScope:
    async def test_unfiled_scope_excludes_live_project_assets(self, client, db_session):
        async with db_session() as session:
            filed, loose, orphaned = await create_test_media(session, count=3)
        p = await _project(client, "Filed")
        gone = await _project(client, "Deleted")
        await client.post(f"/api/projects/{p}/assets", json={"media_ids": [filed.id]})
        await client.post(f"/api/projects/{gone}/assets", json={"media_ids": [orphaned.id]})
        await client.delete(f"/api/projects/{gone}")

        everything = (await client.get("/api/assets/browse?page_size=200")).json()
        all_ids = {item["media_id"] for item in everything["items"]}
        assert {filed.id, loose.id, orphaned.id} <= all_ids

        scoped_all = (await client.get("/api/assets/browse?scope=all&page_size=200")).json()
        assert {item["media_id"] for item in scoped_all["items"]} == all_ids

        unfiled = (await client.get("/api/assets/browse?scope=unfiled&page_size=200")).json()
        unfiled_ids = {item["media_id"] for item in unfiled["items"]}
        assert filed.id not in unfiled_ids
        assert loose.id in unfiled_ids
        assert orphaned.id in unfiled_ids
        assert unfiled["total"] == len(unfiled_ids)

        # A project browse ignores scope.
        in_project = (await client.get(
            f"/api/assets/browse?project_id={p}&scope=unfiled&page_size=200"
        )).json()
        assert {item["media_id"] for item in in_project["items"]} == {filed.id}

        ids = (await client.get("/api/assets/browse/ids?scope=unfiled")).json()["ids"]
        assert len(ids) == len(unfiled_ids)

    async def test_unfiled_scope_applies_to_counts_and_search_groups(self, client, db_session):
        async with db_session() as session:
            filed, loose = await create_test_media(session, count=2)
            filed_media = await session.get(type(filed), filed.id)
            loose_media = await session.get(type(loose), loose.id)
            filed_media.extracted_prompt = "zebracorn filed"
            loose_media.extracted_prompt = "zebracorn loose"
            await session.commit()
        p = await _project(client, "Counted")
        await client.post(f"/api/projects/{p}/assets", json={"media_ids": [filed.id]})

        everything = (await client.get("/api/assets/filter-counts")).json()
        unfiled = (await client.get("/api/assets/filter-counts?scope=unfiled")).json()
        assert unfiled["project_membership"]["any"] == 0
        assert unfiled["media_type"]["images"] == everything["media_type"]["images"] - (
            everything["project_membership"]["any"]
        )

        groups_all = (await client.get("/api/assets/search-groups?q=zebracorn")).json()
        groups_unfiled = (await client.get("/api/assets/search-groups?q=zebracorn&scope=unfiled")).json()

        def ids(body):
            return {item["media_id"] for group in body["groups"] for item in group["items"]}

        assert {filed.id, loose.id} <= ids(groups_all)
        assert loose.id in ids(groups_unfiled)
        assert filed.id not in ids(groups_unfiled)

    async def test_invalid_scope_is_rejected(self, client):
        response = await client.get("/api/assets/browse?scope=bogus")
        assert response.status_code == 422


class TestUnscopedLists:
    async def test_project_id_none_lists_only_unscoped_items(self, client):
        p = await _project(client, "Lists")
        top_chat = (await client.post("/api/chats", json={"name": "top"})).json()
        p_chat = (await client.post("/api/chats", json={"name": "in p", "project_id": p})).json()
        top_board = (await client.post("/api/boards", json={"name": "top"})).json()
        p_board = (await client.post("/api/boards", json={"name": "in p", "project_id": p})).json()
        top_flow = (await client.post("/api/flows", json={"name": "top"})).json()
        p_flow = (await client.post("/api/flows", json={"name": "in p", "project_id": p})).json()
        top_view = (await client.post("/api/saved-views", json={"name": "top", "filters": {}})).json()
        p_view = (await client.post(
            "/api/saved-views", json={"name": "in p", "filters": {}, "project_id": p}
        )).json()

        def ids(body):
            items = body["items"] if isinstance(body, dict) else body
            return {item["id"] for item in items}

        # Chats: no param still lists every project's chats (back-compat).
        chats_default = ids((await client.get("/api/chats?page_size=100")).json())
        assert {top_chat["id"], p_chat["id"]} <= chats_default
        chats_none = ids((await client.get("/api/chats?project_id=none&page_size=100")).json())
        assert top_chat["id"] in chats_none and p_chat["id"] not in chats_none
        previews_none = ids((await client.get("/api/chats/previews?project_id=none&page_size=100")).json())
        assert top_chat["id"] in previews_none and p_chat["id"] not in previews_none
        chats_p = ids((await client.get(f"/api/chats?project_id={p}")).json())
        assert chats_p == {p_chat["id"]}

        for path, top, inner in (
            ("/api/boards", top_board, p_board),
            ("/api/flows", top_flow, p_flow),
        ):
            default = ids((await client.get(path)).json())
            none = ids((await client.get(f"{path}?project_id=none")).json())
            scoped = ids((await client.get(f"{path}?project_id={p}")).json())
            assert top["id"] in default and inner["id"] not in default
            assert none == default
            assert scoped == {inner["id"]}

        views_default = ids((await client.get("/api/saved-views")).json())
        assert {top_view["id"], p_view["id"]} <= views_default
        views_none = ids((await client.get("/api/saved-views?project_id=none")).json())
        assert top_view["id"] in views_none and p_view["id"] not in views_none
        views_zero = ids((await client.get("/api/saved-views?project_id=0")).json())
        assert views_zero == views_none

    async def test_bad_project_filter_is_422(self, client):
        assert (await client.get("/api/chats?project_id=abc")).status_code == 422
        assert (await client.get("/api/boards?project_id=abc")).status_code == 422


class TestSearchProjectNames:
    async def test_global_search_covers_projects_and_names_them(self, client):
        p = await _project(client, "Moonbase")
        await client.post("/api/chats", json={"name": "quokkachat top"})
        await client.post("/api/chats", json={"name": "quokkachat inner", "project_id": p})
        await client.post("/api/boards", json={"name": "quokkaboard", "project_id": p})
        await client.post("/api/flows", json={"name": "quokkaflow", "project_id": p})

        body = (await client.get("/api/search?q=quokka")).json()
        chats = {hit["name"]: hit for hit in body["chats"]}
        assert chats["quokkachat top"]["project_id"] is None
        assert chats["quokkachat top"]["project_name"] is None
        assert chats["quokkachat inner"]["project_id"] == p
        assert chats["quokkachat inner"]["project_name"] == "Moonbase"
        assert body["boards"][0]["project_name"] == "Moonbase"
        assert body["flows"][0]["project_name"] == "Moonbase"

        scoped = (await client.get(f"/api/search?q=quokka&project_id={p}")).json()
        assert {hit["name"] for hit in scoped["chats"]} == {"quokkachat inner"}

    async def test_global_search_skips_deleted_project_items(self, client):
        p = await _project(client, "Doomed")
        await client.post("/api/flows", json={"name": "wombatflow", "project_id": p})
        await client.delete(f"/api/projects/{p}")
        body = (await client.get("/api/search?q=wombatflow")).json()
        assert body["flows"] == []


class TestProjectAssetsChanged:
    async def test_project_routes_broadcast_add_and_remove(self, client, db_session, broadcasts):
        async with db_session() as session:
            (media,) = await create_test_media(session, count=1)
        p = await _project(client, "Broadcast")
        await client.post(f"/api/projects/{p}/assets", json={"media_ids": [media.id]})
        added = _events(broadcasts, "project_assets_changed")[-1]
        assert added["project_id"] == p
        assert added["action"] == "added"
        assert added["media_ids"] == [media.id]
        assert len(added["asset_ids"]) == 1

        await client.delete(f"/api/projects/{p}/assets/{media.id}")
        removed = _events(broadcasts, "project_assets_changed")[-1]
        assert removed == {
            "project_id": p,
            "asset_ids": added["asset_ids"],
            "media_ids": [media.id],
            "action": "removed",
        }

    async def test_asset_routes_broadcast_add_and_remove(self, client, db_session, broadcasts):
        async with db_session() as session:
            first, second = await create_test_media(session, count=2)
        from asset_association_service import asset_for_media

        async with db_session() as session:
            asset_ids = [
                (await asset_for_media(session, first.id)).id,
                (await asset_for_media(session, second.id)).id,
            ]
        p = await _project(client, "Batch")
        await client.post(f"/api/assets/batch/projects/{p}", json={"asset_ids": asset_ids})
        added = _events(broadcasts, "project_assets_changed")[-1]
        assert added["action"] == "added"
        assert set(added["asset_ids"]) == set(asset_ids)
        assert set(added["media_ids"]) == {first.id, second.id}

        response = await client.delete(f"/api/assets/item/{asset_ids[0]}/projects/{p}")
        assert response.status_code == 200
        removed = _events(broadcasts, "project_assets_changed")[-1]
        assert removed["action"] == "removed" and removed["asset_ids"] == [asset_ids[0]]

        response = await client.post(
            f"/api/assets/batch/projects/{p}/remove", json={"asset_ids": asset_ids}
        )
        assert response.json()["removed"] == 1
        removed = _events(broadcasts, "project_assets_changed")[-1]
        assert removed["action"] == "removed" and removed["asset_ids"] == [asset_ids[1]]

    async def test_board_add_broadcasts_project_attach(self, client, db_session, broadcasts):
        async with db_session() as session:
            (media,) = await create_test_media(session, count=1)
        p = await _project(client, "Board add")
        board = (await client.post("/api/boards", json={"name": "B", "project_id": p})).json()
        await client.post(f"/api/boards/{board['id']}/items", json={"media_ids": [media.id]})
        events = _events(broadcasts, "project_assets_changed")
        assert events and events[-1]["project_id"] == p
        assert events[-1]["media_ids"] == [media.id]


class TestBoardMove:
    async def test_moving_board_attaches_assets_and_broadcasts(self, client, db_session, broadcasts):
        async with db_session() as session:
            first, second = await create_test_media(session, count=2)
        board = (await client.post("/api/boards", json={"name": "Movable"})).json()
        await client.post(
            f"/api/boards/{board['id']}/items", json={"media_ids": [first.id, second.id]}
        )
        p = await _project(client, "Destination")
        response = await client.put(f"/api/boards/{board['id']}", json={"project_id": p})
        assert response.status_code == 200, response.text
        assert response.json()["project_id"] == p
        assert {first.id, second.id} <= await _project_media_ids(client, p)

        updated = _events(broadcasts, "board_updated")[-1]
        assert updated["board"]["project_id"] == p
        changed = _events(broadcasts, "project_assets_changed")[-1]
        assert changed["project_id"] == p and set(changed["media_ids"]) == {first.id, second.id}

    async def test_moving_board_to_missing_project_is_404(self, client):
        board = (await client.post("/api/boards", json={"name": "Stuck"})).json()
        response = await client.put(f"/api/boards/{board['id']}", json={"project_id": 999999})
        assert response.status_code == 404
        p = await _project(client, "Deleted target")
        await client.delete(f"/api/projects/{p}")
        response = await client.put(f"/api/boards/{board['id']}", json={"project_id": p})
        assert response.status_code == 404

    async def test_bulk_move_attaches_to_board_project(self, client, db_session):
        async with db_session() as session:
            (media,) = await create_test_media(session, count=1)
        p = await _project(client, "Bulk move")
        board = (await client.post("/api/boards", json={"name": "B", "project_id": p})).json()
        section_id = board["sections"][0]["id"]
        response = await client.post(
            f"/api/boards/{board['id']}/items/bulk-move",
            json={"media_ids": [media.id], "asset_ids": [], "to_section_id": section_id},
        )
        assert response.status_code == 200, response.text
        assert media.id in await _project_media_ids(client, p)
