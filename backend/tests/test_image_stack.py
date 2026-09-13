"""Tests for the op-stack image editor's working-document store.

The document is a directory: steps removed from document.json keep their
payloads, recent undo history is bounded, and cache/ is reconstructible.
"""

import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

import image_stack_service as stack
from database import Asset, AssetMarker, AssetRevision, Marker, MediaItem, WorkingDocument
from tests.helpers.media import create_media_item, generate_test_image


async def _asset(db_session, tmp_path, *, name="base", width=256, height=128):
    """An Asset backed by a real file — save-edit needs a readable source."""
    from asset_service import create_asset_from_media

    async with db_session() as session:
        source = tmp_path / f"{name}.png"
        file_hash = generate_test_image(source, width=width, height=height)
        media = await create_media_item(
            session, file_path=source, file_hash=file_hash, width=width, height=height
        )
        asset = await create_asset_from_media(session, media_id=media.id)
        await session.commit()
        return asset.id, media.id, file_hash


async def _open(client, db_session, tmp_path, name):
    asset_id, media_id, _ = await _asset(db_session, tmp_path, name=name)
    body = (await client.post("/api/image-stack/open", json={"asset_id": asset_id})).json()
    return body["document_id"], body["base"]


def _document(base, edits=None):
    return {
        "format": stack.DOCUMENT_FORMAT,
        "version": stack.DOCUMENT_VERSION,
        "base": base,
        "canvas": {"width": base["width"], "height": base["height"]},
        "edits": edits or [],
    }


def _png_bytes(size=(8, 8), color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class TestOpen:
    async def test_open_creates_the_directory_layout(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        asset_id, media_id, file_hash = await _asset(db_session, tmp_path, name="open-layout")

        response = await client.post("/api/image-stack/open", json={"asset_id": asset_id})
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["base"]["asset_id"] == asset_id
        assert body["base"]["media_id"] == media_id
        assert body["base"]["file_hash"] == file_hash
        assert body["base"]["width"] == 256
        # A fresh asset has no stack yet.
        assert body["document"] is None

        async with db_session() as session:
            document = await session.get(WorkingDocument, body["document_id"])
            assert document.editor_type == stack.EDITOR_TYPE
            directory = Path(document.state_locator)

        assert (directory / "payloads").is_dir()
        assert (directory / "cache").is_dir()

    async def test_reopening_resumes_the_same_document(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        """One stack per asset — this is what makes one-instance-per-asset hold
        across restarts."""
        asset_id, _, _ = await _asset(db_session, tmp_path, name="open-resume")

        first = await client.post("/api/image-stack/open", json={"asset_id": asset_id})
        second = await client.post("/api/image-stack/open", json={"asset_id": asset_id})

        assert first.json()["document_id"] == second.json()["document_id"]

    async def test_open_rejects_a_revision_from_another_asset(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        asset_a, _, _ = await _asset(db_session, tmp_path, name="open-a")
        asset_b, _, _ = await _asset(db_session, tmp_path, name="open-b")
        async with db_session() as session:
            other = await session.get(Asset, asset_b)
            foreign_revision = other.current_revision_id

        response = await client.post(
            "/api/image-stack/open",
            json={"asset_id": asset_a, "revision_id": foreign_revision},
        )
        assert response.status_code == 400


class TestDocument:
    async def test_document_round_trips(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        document_id, base = await _open(client, db_session, tmp_path, "doc-round-trip")
        payload = _document(base, edits=[{
            "id": "01J000000000000000000000AA",
            "class": "patch",
            "enabled": True,
            "label": "Inpaint — collar",
        }])

        write = await client.put(
            f"/api/image-stack/{document_id}/document", json={"document": payload}
        )
        assert write.status_code == 200

        read = await client.get(f"/api/image-stack/{document_id}")
        assert read.json()["document"] == payload

    @pytest.mark.parametrize("label,mutation", [
        ("format", {"format": "something-else"}),
        ("version", {"version": 99}),
        ("edits", {"edits": "not a list"}),
        ("base", {"base": None}),
    ])
    async def test_malformed_documents_are_rejected(
        self, client: httpx.AsyncClient, db_session, tmp_path, label, mutation
    ):
        document_id, base = await _open(client, db_session, tmp_path, f"doc-bad-{label}")
        payload = {**_document(base), **mutation}
        response = await client.put(
            f"/api/image-stack/{document_id}/document", json={"document": payload}
        )
        assert response.status_code == 400

    async def test_unknown_document_is_404(self, client: httpx.AsyncClient):
        assert (await client.get("/api/image-stack/999999")).status_code == 404

class TestJournal:
    async def test_entries_append_and_read_back(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        document_id, _ = await _open(client, db_session, tmp_path, "journal-append")

        await client.post(f"/api/image-stack/{document_id}/journal", json={"entries": [
            {"seq": 1, "action": "add_op", "inverse": {"action": "remove_op", "op_id": "a"}},
            {"seq": 2, "action": "pick_candidate", "inverse": {"action": "pick_candidate"}},
        ]})
        response = await client.post(
            f"/api/image-stack/{document_id}/journal",
            json={"entries": [{"seq": 3, "action": "undo", "inverse": None}]},
        )
        assert response.json()["journal_length"] == 3

        entries = (await client.get(f"/api/image-stack/{document_id}/journal")).json()["entries"]
        assert [e["seq"] for e in entries] == [1, 2, 3]
        # Undo is recorded, not a truncation: entry 2 is still there.
        assert entries[1]["action"] == "pick_candidate"
        assert all("ts" in e for e in entries)

    async def test_entries_without_an_action_are_rejected(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        document_id, _ = await _open(client, db_session, tmp_path, "journal-bad")
        response = await client.post(
            f"/api/image-stack/{document_id}/journal",
            json={"entries": [{"seq": 1}]},
        )
        assert response.status_code == 400

    async def test_journal_is_compacted_to_the_newest_500_entries(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        document_id, _ = await _open(client, db_session, tmp_path, "journal-bounded")
        entries = [
            {"seq": seq, "action": "set_op_param", "inverse": None}
            for seq in range(1, stack.JOURNAL_COMPACT_AT + 1)
        ]

        response = await client.post(
            f"/api/image-stack/{document_id}/journal",
            json={"entries": entries},
        )
        assert response.status_code == 200
        assert response.json()["journal_length"] == stack.JOURNAL_MAX_ENTRIES

        retained = (
            await client.get(f"/api/image-stack/{document_id}/journal")
        ).json()["entries"]
        assert len(retained) == stack.JOURNAL_MAX_ENTRIES
        assert retained[0]["seq"] == stack.JOURNAL_COMPACT_AT - 499
        assert retained[-1]["seq"] == stack.JOURNAL_COMPACT_AT

        async with db_session() as session:
            document = await session.get(WorkingDocument, document_id)
            journal = Path(document.state_locator) / "journal.jsonl"
        assert len(journal.read_text(encoding="utf-8").splitlines()) == 500

    async def test_read_culls_an_existing_oversized_journal_on_demand(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        document_id, _ = await _open(client, db_session, tmp_path, "journal-legacy-large")
        async with db_session() as session:
            document = await session.get(WorkingDocument, document_id)
            journal = Path(document.state_locator) / "journal.jsonl"
        raw_entries = [
            {"seq": seq, "action": "set_op_param"}
            for seq in range(1, stack.JOURNAL_COMPACT_AT + 26)
        ]
        journal.write_text(
            "".join(f"{json.dumps(entry)}\n" for entry in raw_entries),
            encoding="utf-8",
        )

        retained = (
            await client.get(f"/api/image-stack/{document_id}/journal")
        ).json()["entries"]
        assert len(retained) == stack.JOURNAL_MAX_ENTRIES
        assert retained[0]["seq"] == (
            stack.JOURNAL_COMPACT_AT + 26 - stack.JOURNAL_MAX_ENTRIES
        )
        assert retained[-1]["seq"] == stack.JOURNAL_COMPACT_AT + 25
        assert len(journal.read_text(encoding="utf-8").splitlines()) == 500

    async def test_replay_starts_at_the_last_checkpoint(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        document_id, _ = await _open(client, db_session, tmp_path, "journal-checkpoint")
        await client.post(f"/api/image-stack/{document_id}/journal", json={"entries": [
            {"seq": 1, "action": "add_op"},
            {"seq": 2, "action": "checkpoint", "document": {"edits": []}},
            {"seq": 3, "action": "toggle_op"},
        ]})

        entries = (await client.get(f"/api/image-stack/{document_id}/journal")).json()["entries"]
        assert [e["seq"] for e in entries] == [2, 3]

    async def test_a_torn_final_line_does_not_lose_the_log(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        """A crash mid-append leaves a partial line; everything before it stands."""
        document_id, _ = await _open(client, db_session, tmp_path, "journal-torn")
        await client.post(
            f"/api/image-stack/{document_id}/journal",
            json={"entries": [{"seq": 1, "action": "add_op"}]},
        )
        async with db_session() as session:
            document = await session.get(WorkingDocument, document_id)
            journal = Path(document.state_locator) / "journal.jsonl"
        with journal.open("a") as handle:
            handle.write('{"seq": 2, "action": "add_o')

        entries = (await client.get(f"/api/image-stack/{document_id}/journal")).json()["entries"]
        assert [e["seq"] for e in entries] == [1]


class TestPayloads:
    async def test_payload_round_trips(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        document_id, _ = await _open(client, db_session, tmp_path, "payload-round-trip")
        data = _png_bytes()

        upload = await client.post(
            f"/api/image-stack/{document_id}/payloads",
            files={"file": ("mask.png", data, "image/png")},
            data={"name": "01J0-mask.png"},
        )
        assert upload.status_code == 200
        assert upload.json()["ref"] == "payloads/01J0-mask.png"

        fetched = await client.get(f"/api/image-stack/{document_id}/payloads/01J0-mask.png")
        assert fetched.status_code == 200
        assert fetched.content == data
        assert fetched.headers["cache-control"] == "no-cache"

    async def test_overwritten_payload_refetches_latest_bytes(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        """Paint layers keep their ref while each completed stroke rewrites it."""
        document_id, _ = await _open(client, db_session, tmp_path, "payload-overwrite")
        url = f"/api/image-stack/{document_id}/payloads/paint-layer.png"
        first = _png_bytes(color=(255, 0, 0))
        latest = _png_bytes(color=(0, 0, 255))

        for data in (first, latest):
            upload = await client.post(
                f"/api/image-stack/{document_id}/payloads",
                files={"file": ("paint-layer.png", data, "image/png")},
                data={"name": "paint-layer.png"},
            )
            assert upload.status_code == 200

        fetched = await client.get(url)
        assert fetched.status_code == 200
        assert fetched.content == latest
        assert fetched.headers["cache-control"] == "no-cache"

    @pytest.mark.parametrize("label,name", [
        ("traversal", "../escape.png"),
        ("subdir", "sub/dir.png"),
        ("no-extension", "no-extension"),
        ("wrong-extension", "script.svg"),
        ("dotfile", ".hidden.png"),
        ("empty", ""),
    ])
    async def test_payload_names_cannot_escape_the_document(
        self, client: httpx.AsyncClient, db_session, tmp_path, label, name
    ):
        document_id, _ = await _open(client, db_session, tmp_path, f"payload-esc-{label}")
        response = await client.post(
            f"/api/image-stack/{document_id}/payloads",
            files={"file": ("x.png", _png_bytes(), "image/png")},
            data={"name": name},
        )
        assert response.status_code in (400, 422), name

    async def test_cache_is_deletable_and_payloads_survive(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        """cache/ is a pure function of document + payloads + base. payloads/
        is the pack-rat store and must never be swept with it."""
        document_id, _ = await _open(client, db_session, tmp_path, "payload-cache")
        await client.post(
            f"/api/image-stack/{document_id}/payloads",
            files={"file": ("m.png", _png_bytes(), "image/png")},
            data={"name": "keep-me.png"},
        )
        await client.post(
            f"/api/image-stack/{document_id}/payloads",
            files={"file": ("c.png", _png_bytes(), "image/png")},
            data={"name": "composite-1.png", "subdir": "cache"},
        )

        assert (await client.delete(f"/api/image-stack/{document_id}/cache")).status_code == 200

        assert (await client.get(
            f"/api/image-stack/{document_id}/payloads/keep-me.png"
        )).status_code == 200
        assert (await client.get(
            f"/api/image-stack/{document_id}/payloads/composite-1.png?subdir=cache"
        )).status_code == 404

    async def test_new_materialized_head_prunes_only_older_heads(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        document_id, _ = await _open(client, db_session, tmp_path, "head-cache-prune")
        first = _png_bytes(color=(255, 0, 0))
        latest = _png_bytes(color=(0, 0, 255))

        for name, data in (
            ("head-aaaaaaaa.png", first),
            ("selection-derived.png", first),
            ("head-bbbbbbbb.png", latest),
        ):
            response = await client.post(
                f"/api/image-stack/{document_id}/payloads",
                files={"file": (name, data, "image/png")},
                data={"name": name, "subdir": "cache"},
            )
            assert response.status_code == 200

        assert (await client.get(
            f"/api/image-stack/{document_id}/payloads/head-aaaaaaaa.png?subdir=cache"
        )).status_code == 404
        kept = await client.get(
            f"/api/image-stack/{document_id}/payloads/head-bbbbbbbb.png?subdir=cache"
        )
        assert kept.status_code == 200
        assert kept.content == latest
        assert (await client.get(
            f"/api/image-stack/{document_id}/payloads/selection-derived.png?subdir=cache"
        )).status_code == 200


class TestSaveEdit:
    """Save materializes the composite; the stack stays the composition."""

    async def test_save_keeps_the_stack_on_the_revision_it_was_built_against(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        asset_id, media_id, _ = await _asset(db_session, tmp_path, name="save-advance")
        opened = (await client.post(
            "/api/image-stack/open", json={"asset_id": asset_id}
        )).json()
        document_id = opened["document_id"]
        base_revision_id = opened["base"]["revision_id"]

        summary = [{"class": "patch", "exec": {"tool_id": "test:inpaint"}, "job_ids": ["7"]}]
        response = await client.post(
            "/api/media/save-edit",
            files={"file": ("composite.png", _png_bytes((256, 128), (0, 128, 255)), "image/png")},
            data={
                "source_media_id": str(media_id),
                "asset_id": str(asset_id),
                "base_revision_id": str(base_revision_id),
                "working_document_id": str(document_id),
                "stack_summary": json.dumps(summary),
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["asset_id"] == asset_id
        assert body["revision_id"] != base_revision_id

        async with db_session() as session:
            document = await session.get(WorkingDocument, document_id)
            # The same document — not a second one — and still rooted at the
            # revision its ops were authored against.
            #
            # Re-parenting it to its own output would double every edit: the
            # stack would render on a frame that already contained it, so
            # hiding or deleting a step would remove nothing.
            assert document.base_revision_id == base_revision_id
            assert document.base_revision_id != body["revision_id"]
            assert document.editor_type == stack.EDITOR_TYPE

            documents = (await session.execute(
                select(WorkingDocument).where(
                    WorkingDocument.asset_id == asset_id,
                    WorkingDocument.deleted_at.is_(None),
                )
            )).scalars().all()
            assert [d.id for d in documents] == [document_id]

            committed = await session.get(MediaItem, body["media_id"])
            metadata = json.loads(committed.generation_metadata)
            assert metadata["parameters"]["stack"] == summary

            revision = await session.get(AssetRevision, body["revision_id"])
            assert revision.parent_revision_id == base_revision_id

    async def test_save_does_not_rewrite_the_stack(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        """The stack keeps applying from the revision it was built against."""
        asset_id, media_id, _ = await _asset(db_session, tmp_path, name="save-composition")
        opened = (await client.post(
            "/api/image-stack/open", json={"asset_id": asset_id}
        )).json()
        document_id = opened["document_id"]
        document = _document(opened["base"], edits=[{"id": "01J0", "class": "patch", "enabled": True}])
        await client.put(f"/api/image-stack/{document_id}/document", json={"document": document})

        saved = await client.post(
            "/api/media/save-edit",
            files={"file": ("c.png", _png_bytes((256, 128)), "image/png")},
            data={
                "source_media_id": str(media_id),
                "asset_id": str(asset_id),
                "working_document_id": str(document_id),
            },
        )
        assert saved.status_code == 200, saved.text

        after = (await client.get(f"/api/image-stack/{document_id}")).json()["document"]
        assert after == document

    async def test_save_inherits_the_base_generation_history(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        """An editor save adds one step above the generated base Media."""
        from generation_metadata import dump_generation_metadata

        asset_id, media_id, _ = await _asset(
            db_session, tmp_path, name="save-generated-lineage"
        )
        async with db_session() as session:
            generated = await session.get(MediaItem, media_id)
            generated.generation_metadata = dump_generation_metadata(
                task_type="text-to-image",
                source="test",
                tool_id="test:portrait-generator",
                model="portrait-model",
                prompt="portrait in natural light",
                parameters={"seed": 4165798563, "steps": 12},
            )
            generated.tool_id = "test:portrait-generator"
            await session.commit()

        opened = (await client.post(
            "/api/image-stack/open", json={"asset_id": asset_id}
        )).json()
        response = await client.post(
            "/api/media/save-edit",
            files={"file": ("edited.png", _png_bytes((256, 128)), "image/png")},
            data={
                "source_media_id": str(media_id),
                "asset_id": str(asset_id),
                "base_revision_id": str(opened["base"]["revision_id"]),
                "working_document_id": str(opened["document_id"]),
            },
        )
        assert response.status_code == 200, response.text

        async with db_session() as session:
            edited = await session.get(MediaItem, response.json()["media_id"])
            metadata = json.loads(edited.generation_metadata)

        assert metadata["task_type"] == "image-to-image"
        assert metadata["tool_id"] == "builtin:stimma:image-editor"
        assert metadata["source_inputs"] == [{
            "media_id": media_id,
            "role": "source_image",
        }]
        assert [entry["media_id"] for entry in metadata["lineage_trace"]] == [media_id]
        assert metadata["lineage_trace"][0]["task_type"] == "text-to-image"
        assert metadata["lineage_trace"][0]["tool_id"] == "test:portrait-generator"
        assert metadata["lineage_trace"][0]["prompt"] == "portrait in natural light"
        assert metadata["lineage_trace"][0]["parameters"] == {
            "seed": 4165798563,
            "steps": 12,
        }

    async def test_reopen_after_save_reports_the_working_document_base(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        """Asset head may advance; the live composition's base must not."""
        asset_id, media_id, _ = await _asset(db_session, tmp_path, name="save-reopen")
        opened = (await client.post(
            "/api/image-stack/open", json={"asset_id": asset_id}
        )).json()
        document_id = opened["document_id"]
        original_base = opened["base"]
        document = _document(
            original_base,
            edits=[{"id": "01J0", "class": "patch", "enabled": True}],
        )
        await client.put(
            f"/api/image-stack/{document_id}/document",
            json={"document": document},
        )

        saved = await client.post(
            "/api/media/save-edit",
            files={
                "file": (
                    "flattened.png",
                    _png_bytes((256, 128), (0, 128, 255)),
                    "image/png",
                )
            },
            data={
                "source_media_id": str(media_id),
                "asset_id": str(asset_id),
                "base_revision_id": str(original_base["revision_id"]),
                "working_document_id": str(document_id),
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["revision_id"] != original_base["revision_id"]

        reopened = (await client.post(
            "/api/image-stack/open", json={"asset_id": asset_id}
        )).json()
        assert reopened["document_id"] == document_id
        assert reopened["document"] == document
        assert reopened["base"] == original_base
        assert reopened["head_revision_id"] == saved.json()["revision_id"]

    async def test_save_as_new_forks_the_document(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        asset_id, media_id, _ = await _asset(db_session, tmp_path, name="save-fork")
        document_id = (await client.post(
            "/api/image-stack/open", json={"asset_id": asset_id}
        )).json()["document_id"]

        response = await client.post(
            "/api/media/save-edit",
            files={"file": ("c.png", _png_bytes((256, 128)), "image/png")},
            data={
                "source_media_id": str(media_id),
                "asset_id": str(asset_id),
                "working_document_id": str(document_id),
                "save_as_new": "true",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["asset_id"] != asset_id

        async with db_session() as session:
            forked = await session.scalar(
                select(WorkingDocument).where(
                    WorkingDocument.asset_id == body["asset_id"],
                    WorkingDocument.deleted_at.is_(None),
                )
            )
            assert forked is not None
            assert forked.id != document_id
            assert forked.editor_type == stack.EDITOR_TYPE
            # The original stack is untouched by a fork.
            original = await session.get(WorkingDocument, document_id)
            assert original.asset_id == asset_id

    async def test_save_as_new_applies_markers_only_to_the_fork(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        asset_id, media_id, _ = await _asset(
            db_session, tmp_path, name="save-fork-markers"
        )
        document_id = (await client.post(
            "/api/image-stack/open", json={"asset_id": asset_id}
        )).json()["document_id"]
        async with db_session() as session:
            markers = [
                Marker(name="Editor fork one", icon_svg="<svg />", color="#fff"),
                Marker(name="Editor fork two", icon_svg="<svg />", color="#000"),
            ]
            session.add_all(markers)
            await session.commit()
            marker_ids = [marker.id for marker in markers]

        response = await client.post(
            "/api/media/save-edit",
            files={"file": ("marked.png", _png_bytes((256, 128)), "image/png")},
            data={
                "source_media_id": str(media_id),
                "asset_id": str(asset_id),
                "working_document_id": str(document_id),
                "save_as_new": "true",
                "marker_ids": ",".join(str(marker_id) for marker_id in marker_ids),
            },
        )
        assert response.status_code == 200, response.text
        fork_asset_id = response.json()["asset_id"]

        async with db_session() as session:
            fork_marker_ids = set(await session.scalars(
                select(AssetMarker.marker_id).where(
                    AssetMarker.asset_id == fork_asset_id,
                    AssetMarker.deleted_at.is_(None),
                )
            ))
            source_marker_ids = set(await session.scalars(
                select(AssetMarker.marker_id).where(
                    AssetMarker.asset_id == asset_id,
                    AssetMarker.deleted_at.is_(None),
                )
            ))
        assert fork_marker_ids == set(marker_ids)
        assert source_marker_ids == set()

    async def test_unknown_stack_document_is_rejected(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        asset_id, media_id, _ = await _asset(db_session, tmp_path, name="save-unknown-doc")
        response = await client.post(
            "/api/media/save-edit",
            files={"file": ("c.png", _png_bytes(), "image/png")},
            data={
                "source_media_id": str(media_id),
                "asset_id": str(asset_id),
                "working_document_id": "999999",
            },
        )
        assert response.status_code == 404

    async def test_stack_document_is_required(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        asset_id, media_id, _ = await _asset(db_session, tmp_path, name="save-no-doc")
        response = await client.post(
            "/api/media/save-edit",
            files={"file": ("c.png", _png_bytes(), "image/png")},
            data={"source_media_id": str(media_id), "asset_id": str(asset_id)},
        )
        assert response.status_code == 422

class TestAutosave:
    """Leaving the editor commits the applied stack; autosaves coalesce."""

    async def _save(self, client, *, media_id, asset_id, base_revision_id,
                    document_id, autosave, color=(0, 128, 255)):
        return await client.post(
            "/api/media/save-edit",
            files={"file": ("c.png", _png_bytes((256, 128), color), "image/png")},
            data={
                "source_media_id": str(media_id),
                "asset_id": str(asset_id),
                "base_revision_id": str(base_revision_id),
                "working_document_id": str(document_id),
                **({"autosave": "true"} if autosave else {}),
            },
        )

    async def test_autosave_commits_and_coalesces(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        asset_id, media_id, _ = await _asset(db_session, tmp_path, name="autosave-coalesce")
        opened = (await client.post(
            "/api/image-stack/open", json={"asset_id": asset_id}
        )).json()
        document_id = opened["document_id"]
        base_revision_id = opened["base"]["revision_id"]

        first = await self._save(
            client, media_id=media_id, asset_id=asset_id,
            base_revision_id=base_revision_id, document_id=document_id,
            autosave=True,
        )
        assert first.status_code == 200, first.text
        second = await self._save(
            client, media_id=media_id, asset_id=asset_id,
            base_revision_id=base_revision_id, document_id=document_id,
            autosave=True, color=(0, 255, 0),
        )
        assert second.status_code == 200, second.text

        async with db_session() as session:
            asset = await session.get(Asset, asset_id)
            assert asset.current_revision_id == second.json()["revision_id"]

            head = await session.get(AssetRevision, second.json()["revision_id"])
            assert second.json()["revision_id"] == first.json()["revision_id"]
            assert head.autosave is True
            assert head.note == "Edit autosave"
            assert head.parent_revision_id == base_revision_id

            from database import MediaOwner
            head_owner = await session.scalar(
                select(MediaOwner).where(
                    MediaOwner.root_kind == "asset_revision",
                    MediaOwner.root_id == str(head.id),
                    MediaOwner.deleted_at.is_(None),
                )
            )
            assert head_owner is not None

            live = (await session.execute(
                select(AssetRevision).where(
                    AssetRevision.asset_id == asset_id,
                    AssetRevision.deleted_at.is_(None),
                )
            )).scalars().all()
            assert {r.id for r in live} == {base_revision_id, head.id}

    async def test_explicit_save_promotes_the_autosave_head_in_place(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        asset_id, media_id, _ = await _asset(db_session, tmp_path, name="autosave-promote")
        opened = (await client.post(
            "/api/image-stack/open", json={"asset_id": asset_id}
        )).json()
        document_id = opened["document_id"]
        base_revision_id = opened["base"]["revision_id"]

        auto = await self._save(
            client, media_id=media_id, asset_id=asset_id,
            base_revision_id=base_revision_id, document_id=document_id,
            autosave=True,
        )
        saved = await self._save(
            client, media_id=media_id, asset_id=asset_id,
            base_revision_id=base_revision_id, document_id=document_id,
            autosave=False, color=(255, 255, 0),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["revision_id"] == auto.json()["revision_id"]

        async with db_session() as session:
            head = await session.get(AssetRevision, saved.json()["revision_id"])
            assert head.autosave is False
            assert head.note == "Image editor save"
            assert head.parent_revision_id == base_revision_id

    async def test_empty_stack_discards_autosave_on_an_untouched_branch(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        asset_id, media_id, _ = await _asset(
            db_session, tmp_path, name="autosave-discard-empty"
        )
        opened = (await client.post(
            "/api/image-stack/open", json={"asset_id": asset_id}
        )).json()
        document_id = opened["document_id"]
        base_revision_id = opened["base"]["revision_id"]

        autosaved = await self._save(
            client,
            media_id=media_id,
            asset_id=asset_id,
            base_revision_id=base_revision_id,
            document_id=document_id,
            autosave=True,
        )
        autosave_revision_id = autosaved.json()["revision_id"]

        discarded = await client.post(
            "/api/media/discard-edit-autosave",
            json={
                "asset_id": asset_id,
                "base_revision_id": base_revision_id,
                "working_document_id": document_id,
            },
        )
        assert discarded.status_code == 200, discarded.text
        assert discarded.json() == {
            "discarded": True,
            "reason": None,
            "asset_id": asset_id,
            "revision_id": base_revision_id,
            "media_id": media_id,
        }
        browser_item = (await client.get(
            f"/api/assets/item/{asset_id}/browser"
        )).json()
        assert browser_item["revision_count"] == 1
        assert browser_item["markers"] == []

        async with db_session() as session:
            asset = await session.get(Asset, asset_id)
            autosave_revision = await session.get(
                AssetRevision, autosave_revision_id
            )
            assert asset.current_revision_id == base_revision_id
            assert autosave_revision.deleted_at is not None

    async def test_empty_stack_keeps_autosave_when_a_saved_version_exists(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        asset_id, media_id, _ = await _asset(
            db_session, tmp_path, name="autosave-discard-keeps-version"
        )
        opened = (await client.post(
            "/api/image-stack/open", json={"asset_id": asset_id}
        )).json()
        document_id = opened["document_id"]
        base_revision_id = opened["base"]["revision_id"]
        saved = await self._save(
            client,
            media_id=media_id,
            asset_id=asset_id,
            base_revision_id=base_revision_id,
            document_id=document_id,
            autosave=False,
        )
        autosaved = await self._save(
            client,
            media_id=media_id,
            asset_id=asset_id,
            base_revision_id=base_revision_id,
            document_id=document_id,
            autosave=True,
            color=(0, 255, 0),
        )

        kept = await client.post(
            "/api/media/discard-edit-autosave",
            json={
                "asset_id": asset_id,
                "base_revision_id": base_revision_id,
                "working_document_id": document_id,
            },
        )
        assert kept.status_code == 200, kept.text
        assert kept.json()["discarded"] is False
        assert kept.json()["reason"] == "saved_versions"
        browser_item = (await client.get(
            f"/api/assets/item/{asset_id}/browser"
        )).json()
        assert browser_item["revision_count"] == 3
        assert [marker["id"] for marker in browser_item["markers"]] == [
            "implicit:edited"
        ]

        async with db_session() as session:
            asset = await session.get(Asset, asset_id)
            saved_revision = await session.get(
                AssetRevision, saved.json()["revision_id"]
            )
            autosave_revision = await session.get(
                AssetRevision, autosaved.json()["revision_id"]
            )
            assert asset.current_revision_id == autosave_revision.id
            assert autosave_revision.deleted_at is None
            assert saved_revision.deleted_at is None

    async def test_autosave_after_explicit_save_keeps_the_version(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        """A user version is history; only autosave heads get swallowed."""
        asset_id, media_id, _ = await _asset(db_session, tmp_path, name="autosave-keeps")
        opened = (await client.post(
            "/api/image-stack/open", json={"asset_id": asset_id}
        )).json()
        document_id = opened["document_id"]
        base_revision_id = opened["base"]["revision_id"]

        saved = await self._save(
            client, media_id=media_id, asset_id=asset_id,
            base_revision_id=base_revision_id, document_id=document_id,
            autosave=False,
        )
        auto = await self._save(
            client, media_id=media_id, asset_id=asset_id,
            base_revision_id=base_revision_id, document_id=document_id,
            autosave=True, color=(0, 255, 0),
        )
        assert auto.status_code == 200, auto.text

        async with db_session() as session:
            version = await session.get(AssetRevision, saved.json()["revision_id"])
            assert version.deleted_at is None
            asset = await session.get(Asset, asset_id)
            assert asset.current_revision_id == auto.json()["revision_id"]

    async def test_autosave_declines_when_the_head_moved(
        self, client: httpx.AsyncClient, db_session, tmp_path
    ):
        """An autosave never branches past changes made outside the editor."""
        asset_id, media_id, _ = await _asset(db_session, tmp_path, name="autosave-stale")
        opened = (await client.post(
            "/api/image-stack/open", json={"asset_id": asset_id}
        )).json()
        document_id = opened["document_id"]
        base_revision_id = opened["base"]["revision_id"]

        # Something else — a tool, the agent — advances the Asset.
        from asset_service import commit_revision
        async with db_session() as session:
            source = tmp_path / "outside.png"
            file_hash = generate_test_image(source, width=256, height=128)
            outside = await create_media_item(
                session, file_path=source, file_hash=file_hash, width=256, height=128
            )
            head = await commit_revision(
                session, asset_id=asset_id, media_id=outside.id
            )
            outside_head_id = head.id
            await session.commit()

        # The tool's revision parents the OLD head, so the stack's lineage no
        # longer reaches the current one.
        auto = await self._save(
            client, media_id=media_id, asset_id=asset_id,
            base_revision_id=base_revision_id, document_id=document_id,
            autosave=True,
        )
        assert auto.status_code == 409

        async with db_session() as session:
            asset = await session.get(Asset, asset_id)
            assert asset.current_revision_id == outside_head_id


class TestStepNaming:
    """A generative step is named after what it did, or keeps its verb.

    Naming is advisory: the row already says Remove or Repaint, so every failure
    path here has to be a quiet no-label rather than an error the editor has to
    handle mid-run.
    """

    @pytest.fixture
    def quick_task_vlm(self, monkeypatch):
        """Stand in for the quick-task model, recording what it was asked."""
        calls: list[dict] = []
        reply = {"text": "house"}

        async def fake_config(role, project_id=None):
            assert role == "quick_task"
            return object()

        async def fake_vision(config, prompt, image_b64, *, max_tokens=500, temperature=0.3):
            calls.append({"prompt": prompt, "image_b64": image_b64})
            return reply["text"], None

        monkeypatch.setattr("llm_resolver.get_effective_llm_config", fake_config)
        monkeypatch.setattr("llm.llm_complete_vision", fake_vision)
        return calls, reply

    async def test_remove_is_named_after_its_subject(
        self, client: httpx.AsyncClient, quick_task_vlm
    ):
        calls, reply = quick_task_vlm
        reply["text"] = "house"
        response = await client.post(
            "/api/image-stack/name-edit",
            json={"operation": "remove", "image_b64": "Zm9v"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["label"] == "Remove house"
        assert calls[0]["image_b64"] == "Zm9v"

    async def test_repaint_names_both_sides_of_the_swap(
        self, client: httpx.AsyncClient, quick_task_vlm
    ):
        calls, reply = quick_task_vlm
        reply["text"] = "dog -> fox"
        response = await client.post(
            "/api/image-stack/name-edit",
            json={
                "operation": "repaint",
                "image_b64": "Zm9v",
                "prompt": "a red fox walking on the boards",
            },
        )
        assert response.json()["label"] == "Dog → fox"
        # The requested replacement is what makes the second half nameable.
        assert "red fox walking" in calls[0]["prompt"]

    async def test_a_repaint_with_no_prompt_is_not_named(
        self, client: httpx.AsyncClient, quick_task_vlm
    ):
        calls, _ = quick_task_vlm
        response = await client.post(
            "/api/image-stack/name-edit",
            json={"operation": "repaint", "image_b64": "Zm9v"},
        )
        assert response.json()["label"] is None
        assert calls == []

    async def test_expand_is_not_named(self, client: httpx.AsyncClient, quick_task_vlm):
        calls, _ = quick_task_vlm
        response = await client.post(
            "/api/image-stack/name-edit",
            json={"operation": "expand", "image_b64": "Zm9v"},
        )
        assert response.json()["label"] is None
        assert calls == []

    @pytest.mark.parametrize(
        "reply",
        [
            "I'm sorry, I can't help with identifying objects in this image.",
            "The subject at the center of this crop appears to be a small wooden farmhouse",
            "",
        ],
    )
    async def test_an_unusable_answer_leaves_the_verb(
        self, client: httpx.AsyncClient, quick_task_vlm, reply
    ):
        """A label cut mid-word is worse than "Remove"."""
        _, reply_box = quick_task_vlm
        reply_box["text"] = reply
        response = await client.post(
            "/api/image-stack/name-edit",
            json={"operation": "remove", "image_b64": "Zm9v"},
        )
        assert response.status_code == 200
        assert response.json()["label"] is None

    async def test_a_model_error_is_not_an_editor_error(
        self, client: httpx.AsyncClient, monkeypatch
    ):
        async def fake_config(role, project_id=None):
            return object()

        async def exploding_vision(*args, **kwargs):
            raise RuntimeError("provider down")

        monkeypatch.setattr("llm_resolver.get_effective_llm_config", fake_config)
        monkeypatch.setattr("llm.llm_complete_vision", exploding_vision)
        response = await client.post(
            "/api/image-stack/name-edit",
            json={"operation": "remove", "image_b64": "Zm9v"},
        )
        assert response.status_code == 200
        assert response.json()["label"] is None

    async def test_no_configured_model_is_not_an_editor_error(
        self, client: httpx.AsyncClient, monkeypatch
    ):
        async def no_config(role, project_id=None):
            return None

        monkeypatch.setattr("llm_resolver.get_effective_llm_config", no_config)
        response = await client.post(
            "/api/image-stack/name-edit",
            json={"operation": "remove", "image_b64": "Zm9v"},
        )
        assert response.status_code == 200
        assert response.json()["label"] is None
