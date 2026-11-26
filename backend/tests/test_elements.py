"""Elements: bundles and revisions, the chat workspace and tool, routes, lineage."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from database import Asset, AssetRevision, ContainerMember, MediaElement, MediaItem
from tests.helpers.media import create_media_item


def _png(path: Path, color=(200, 60, 40)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color).save(path, format="PNG")
    return path


async def _library_image(session, path: Path) -> tuple[int, int]:
    """A library image Asset. Returns (asset_id, media_id)."""
    from packages.manifest import sha256_file

    media = await create_media_item(
        session, file_path=path, file_hash=sha256_file(path), file_size=path.stat().st_size,
        width=64, height=48, materialize_asset=True,
    )
    revision = await session.scalar(select(AssetRevision).where(AssetRevision.primary_media_id == media.id))
    return revision.asset_id, media.id


async def _tool(session, workspace: Path, **kwargs) -> str:
    from agent.v2.tools.element import element_tool

    return await element_tool(session=session, workspace_dir=str(workspace), **kwargs)


def _edit_manifest(directory: Path, **changes) -> dict:
    manifest = json.loads((directory / "element.json").read_text())
    manifest.update(changes)
    (directory / "element.json").write_text(json.dumps(manifest))
    return manifest


INSTRUCTIONS = """# Mira

Late-20s editorial model, asymmetrical dark bob.

{{#if model_family == "flux-3-klein" and lora_active}}
Use trigger `mira_kl`. Don't describe her face.
{{else}}
Describe her face: olive skin, dark hazel eyes.
{{/if}}

{{#if surface == "chat"}}
Score picks against face-front before showing them.
{{/if}}
Keep the {{wardrobe}} wildcard.
"""


async def _make_mira(session, tmp_path: Path, workspace: Path) -> tuple[int, list[int]]:
    face, angry = await _library_image(session, _png(tmp_path / "lib" / "face.png")), await _library_image(
        session, _png(tmp_path / "lib" / "angry.png", (10, 10, 200))
    )
    out = await _tool(session, workspace, action="init", slug="mira", name="Mira", kind="Character",
                      description="Editorial model")
    assert "elements/mira/" in out
    directory = workspace / "elements" / "mira"
    _edit_manifest(
        directory,
        cover_member_key="face-front",
        media_menu=[
            {"key": "face-front", "asset_id": face[0], "title": "Front neutral", "labels": ["identity"],
             "usage_hint": "Default identity anchor."},
            {"key": "expr-angry", "asset_id": angry[0], "title": "Furious glare", "conditional": True,
             "labels": ["expression:angry"], "usage_hint": "When the prompt asks for anger."},
        ],
        loras=[{"key": "mira-klein-v2", "fingerprint": "stfp1:0123456789abcdef", "display_name": "mira_klein_v2",
                "model_family": "flux-3-klein", "default_weight": 0.8, "trigger": "mira_kl"}],
    )
    (directory / "ELEMENT.md").write_text(INSTRUCTIONS)
    (directory / "files").mkdir(exist_ok=True)
    (directory / "files" / "palette.json").write_text('{"accent": "#ff0000"}')
    saved = await _tool(session, workspace, action="save", slug="mira")
    assert saved.startswith("Saved new element 'Mira'"), saved
    asset_id = int(saved.split("asset_id ")[1].split(",")[0])
    return asset_id, [face[0], angry[0]]


@pytest.mark.asyncio
async def test_save_from_workspace_creates_element_asset_and_bundle(db_session, tmp_path):
    workspace = tmp_path / "ws"
    async with db_session() as session:
        asset_id, linked = await _make_mira(session, tmp_path, workspace)
        asset = await session.get(Asset, asset_id)
        assert asset.asset_type == "element" and asset.title == "Mira"
        revision = await session.get(AssetRevision, asset.current_revision_id)
        media = await session.get(MediaItem, revision.primary_media_id)
        assert media.file_format == "stimmaelement"
        bundle = Path(media.file_path)
        assert {p.name for p in bundle.iterdir()} == {"element.json", "ELEMENT.md", "files", "_tile.png"}
        manifest = json.loads((bundle / "element.json").read_text())
        assert manifest["kind"] == "character" and manifest["slug"] == "mira"
        assert manifest["files"] == [{"path": "files/palette.json", "mime_type": "application/json"}]
        assert manifest["media_menu"][0]["status"] == "canonical"
        rows = list(await session.scalars(
            select(ContainerMember).where(ContainerMember.container_revision_id == revision.id)
            .order_by(ContainerMember.member_order)
        ))
        assert [r.linked_asset_id for r in rows] == linked
        assert [r.title for r in rows] == ["face-front", "expr-angry"]
        assert rows[1].caption == "When the prompt asks for anger."
        assert json.loads(rows[1].member_metadata)["conditional"] is True
        assert all(r.embedded_media_id is None for r in rows)  # linked, never owned

        # The checkout now matches what was saved, with read-only media copies.
        directory = workspace / "elements" / "mira"
        meta = json.loads((directory / ".stimma-element.json").read_text())
        assert meta["asset_id"] == asset_id and meta["base_revision_id"] == revision.id
        copy = directory / "media" / "face-front.png"
        assert copy.is_file() and not copy.is_symlink() and not os.access(copy, os.W_OK)

        listed = await _tool(session, workspace, action="list")
        assert f"| {asset_id} | Mira | character | 1 | 2 | 1 | elements/mira |" in listed


@pytest.mark.asyncio
async def test_open_renders_for_chat_and_media_is_read_only(db_session, tmp_path):
    from agent.v2.tools.write_file import write_file
    from agent.v2.tools.edit_file import edit_file

    async with db_session() as session:
        asset_id, _ = await _make_mira(session, tmp_path, tmp_path / "ws")
        other = tmp_path / "ws2"
        out = await _tool(session, other, action="open", asset_id=asset_id)
        assert "# Mira (character, version 1)" in out
        assert "Score picks against face-front" in out  # surface == chat
        assert "Describe her face" in out and "mira_kl`. Don't" not in out
        assert "{{wardrobe}}" in out and "{{#if" not in out
        assert "expr-angry (asset_id" in out and "situational" in out
        assert "elements/mira/files/palette.json" in out
        assert (other / "elements" / "mira" / "media" / "expr-angry.png").is_file()

        blocked = await write_file(file_path="elements/mira/media/face-front.png", content="x", workspace_dir=str(other))
        assert blocked.startswith("Error:") and "read-only" in blocked
        blocked = await write_file(file_path="elements/mira/.stimma-element.json", content="{}", workspace_dir=str(other))
        assert blocked.startswith("Error:")
        ok = await edit_file(file_path="elements/mira/ELEMENT.md", old_string="asymmetrical dark bob",
                             new_string="asymmetrical chin-length dark bob", workspace_dir=str(other))
        assert not ok.startswith("Error"), ok


@pytest.mark.asyncio
async def test_new_revision_is_immutable_and_conflicts_are_detected(db_session, client, tmp_path):
    async with db_session() as session:
        asset_id, _ = await _make_mira(session, tmp_path, tmp_path / "ws")
        first = await session.get(Asset, asset_id)
        first_rev = await session.get(AssetRevision, first.current_revision_id)
        first_bundle = Path((await session.get(MediaItem, first_rev.primary_media_id)).file_path)
        first_text = (first_bundle / "ELEMENT.md").read_text()

        a = tmp_path / "a"
        await _tool(session, a, action="open", asset_id=asset_id)
        (a / "elements/mira/ELEMENT.md").write_text(first_text + "\nTowel on the left shoulder.\n")
        saved = await _tool(session, a, action="save", slug="mira", note="Towel")
        assert saved.startswith("Saved 'Mira'") and "version 2" in saved
        assert (first_bundle / "ELEMENT.md").read_text() == first_text  # old revision untouched

        # Another checkout started from version 1 is now stale.
        b = tmp_path / "b"
        b.mkdir()
        await _tool(session, b, action="open", asset_id=asset_id)
    # Meanwhile the viewer changes the cover (version 3).
    response = await client.patch(f"/api/elements/{asset_id}", json={"cover_member_key": "expr-angry"})
    assert response.status_code == 200, response.text
    assert response.json()["revision_number"] == 3 and response.json()["cover"]["key"] == "expr-angry"

    async with db_session() as session:
        (b / "elements/mira/ELEMENT.md").write_text("# Mira\n\nRewritten.\n")
        refused = await _tool(session, b, action="save", slug="mira")
        assert refused.startswith("Error:") and "changed since" in refused
        reopened = await _tool(session, b, action="open", asset_id=asset_id)
        assert "unsaved edits" in reopened and "Rewritten" in (b / "elements/mira/ELEMENT.md").read_text()
        forced = await _tool(session, b, action="save", slug="mira", force=True)
        assert "version 4" in forced
        revisions = list(await session.scalars(select(AssetRevision).where(AssetRevision.asset_id == asset_id)))
        assert sorted(r.revision_number for r in revisions) == [1, 2, 3, 4]
        latest = max(revisions, key=lambda r: r.revision_number)
        assert latest.note is None or isinstance(latest.note, str)
        note_rev = next(r for r in revisions if r.revision_number == 2)
        assert note_rev.note == "Towel"


@pytest.mark.asyncio
async def test_save_validation_errors_are_plain(db_session, tmp_path):
    workspace = tmp_path / "ws"
    async with db_session() as session:
        asset_id, linked = await _make_mira(session, tmp_path, workspace)
        directory = workspace / "elements" / "mira"

        (directory / "ELEMENT.md").write_text("{{#if lora_active}}never closed")
        out = await _tool(session, workspace, action="save", slug="mira")
        assert out.startswith("Error:") and "never closed" in out
        (directory / "ELEMENT.md").write_text("ok {{#if mood == 'happy'}}smile{{/if}}")

        _edit_manifest(directory, media_menu=[{"key": "a", "asset_id": 999999}], cover_member_key=None)
        out = await _tool(session, workspace, action="save", slug="mira")
        assert "asset 999999 is not in the library" in out

        _edit_manifest(directory, media_menu=[{"key": "a", "asset_id": asset_id}])
        out = await _tool(session, workspace, action="save", slug="mira")
        assert "can't contain other elements" in out

        _edit_manifest(directory, media_menu=[{"key": "a", "asset_id": linked[0]}, {"key": "a", "asset_id": linked[1]}])
        out = await _tool(session, workspace, action="save", slug="mira")
        assert "used twice" in out

        _edit_manifest(directory, media_menu=[{"key": "Bad Key", "asset_id": linked[0]}], cover_member_key="zzz")
        out = await _tool(session, workspace, action="save", slug="mira")
        assert "short lowercase name" in out and "cover_member_key 'zzz'" in out

        _edit_manifest(directory, media_menu=[{"key": "a", "asset_id": linked[0]}], cover_member_key=None)
        out = await _tool(session, workspace, action="save", slug="mira")
        assert out.startswith("Saved") and "mood" in out  # unknown variable is a warning, not an error

        assert (await _tool(session, workspace, action="save", slug="nope")).startswith("Error:")
        assert "already exists" in await _tool(session, workspace, action="init", slug="mira", name="Again")


@pytest.mark.asyncio
async def test_removed_linked_asset_becomes_missing_slot(db_session, client, tmp_path):
    from asset_deletion_service import prepare_asset_reference_deletion
    from asset_service import trash_asset

    workspace = tmp_path / "ws"
    async with db_session() as session:
        asset_id, linked = await _make_mira(session, tmp_path, workspace)
        await trash_asset(session, asset_id=linked[1])
        await session.commit()

    detail = (await client.get(f"/api/elements/{asset_id}")).json()
    angry = next(m for m in detail["media"] if m["key"] == "expr-angry")
    assert angry["missing"] is True and angry["usage_hint"] == "When the prompt asks for anger."

    async with db_session() as session:
        # Privacy deletion tombstones the link but keeps the slot.
        await prepare_asset_reference_deletion(session, [linked[1]])
        await session.commit()
        asset = await session.get(Asset, asset_id)
        rows = list(await session.scalars(select(ContainerMember).where(
            ContainerMember.container_revision_id == asset.current_revision_id).order_by(ContainerMember.member_order)))
        assert rows[1].missing_linked_asset is True and rows[1].linked_asset_id is None and rows[1].title == "expr-angry"

    detail = (await client.get(f"/api/elements/{asset_id}")).json()
    angry = next(m for m in detail["media"] if m["key"] == "expr-angry")
    assert angry["missing"] is True and angry["asset_id"] is None and angry["title"] == "Furious glare"

    # Saving again carries the empty slot instead of failing.
    async with db_session() as session:
        out = await _tool(session, workspace, action="save", slug="mira")
        assert out.startswith("Saved") and "no longer in the library" in out
        asset = await session.get(Asset, asset_id)
        rows = list(await session.scalars(select(ContainerMember).where(
            ContainerMember.container_revision_id == asset.current_revision_id).order_by(ContainerMember.member_order)))
        assert rows[1].missing_linked_asset is True and rows[0].linked_asset_id == linked[0]


@pytest.mark.asyncio
async def test_element_routes(db_session, client, tmp_path):
    async with db_session() as session:
        asset_id, linked = await _make_mira(session, tmp_path, tmp_path / "ws")

    listing = (await client.get("/api/elements")).json()["elements"]
    row = next(e for e in listing if e["asset_id"] == asset_id)
    assert row["name"] == "Mira" and row["kind"] == "character" and row["canonical_count"] == 2 and row["lora_count"] == 1
    assert (await client.get("/api/elements", params={"kind": "style"})).json()["elements"] == []
    found = [e["asset_id"] for e in (await client.get("/api/elements", params={"q": "editorial"})).json()["elements"]]
    assert found[0] == asset_id  # newest first
    assert (await client.get("/api/elements", params={"q": "no such words"})).json()["elements"] == []

    detail = (await client.get(f"/api/elements/{asset_id}")).json()
    assert detail["name"] == "Mira" and detail["kind"] == "character" and detail["revision_number"] == 1
    assert detail["cover"]["key"] == "face-front" and detail["cover"]["media_id"] and detail["has_tile"]
    assert "{{#if" in detail["instructions"]
    assert "{{#if" not in detail["instructions_display"] and "Describe her face" in detail["instructions_display"]
    assert detail["instructions_valid"] is True
    assert detail["referenced_vars"] == ["lora_active", "model_family", "surface"]
    assert [m["key"] for m in detail["media"]] == ["face-front", "expr-angry"]
    assert detail["media"][0]["asset_id"] == linked[0] and detail["media"][0]["is_cover"] is True
    assert detail["media"][0]["file_format"] == "png" and detail["media"][0]["missing"] is False
    assert detail["loras"][0]["trigger"] == "mira_kl"
    assert detail["files"] == [{"path": "files/palette.json", "name": "palette.json", "label": "",
                                "mime_type": "application/json", "size": 21}]
    assert detail["created_at"] and detail["updated_at"]

    renamed = await client.patch(f"/api/elements/{asset_id}", json={"name": "Mira Vale"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Mira Vale"
    assert renamed.json()["revision_number"] == 1  # the Asset title owns the name
    stale = await client.patch(f"/api/elements/{asset_id}", json={"cover_member_key": "expr-angry", "base_revision_id": 1})
    assert stale.status_code == 409
    bad = await client.patch(f"/api/elements/{asset_id}", json={"cover_member_key": "nope"})
    assert bad.status_code == 400

    file = await client.get(f"/api/elements/{asset_id}/files/files/palette.json", params={"download": True})
    assert file.status_code == 200 and file.json() == {"accent": "#ff0000"}
    assert "attachment" in file.headers["content-disposition"]
    assert (await client.get(f"/api/elements/{asset_id}/files/element.json")).status_code == 404
    assert (await client.get(f"/api/elements/{asset_id}/files/files/../element.json")).status_code == 404
    assert (await client.get("/api/elements/999999")).status_code == 404
    assert (await client.get(f"/api/elements/{linked[0]}")).status_code == 404  # an image is not an element

    content = (await client.get(f"/api/media/{detail['media_id']}/content")).json()
    assert content["media_menu"][1]["resolved"]["asset_id"] == linked[1]

    created = await client.post("/api/elements", json={"name": "Night market", "kind": "place", "asset_ids": linked})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["name"] == "Night market" and [m["key"] for m in body["media"]] == ["ref-1", "ref-2"]
    assert body["cover"]["key"] == "ref-1"
    empty = await client.post("/api/elements", json={})
    assert empty.status_code == 200 and empty.json()["name"] == "Untitled element" and empty.json()["media"] == []
    assert empty.json()["has_tile"] is False


@pytest.mark.asyncio
async def test_element_thumbnail_uses_tile(db_session, tmp_path):
    from routes.media_files import _generate_element_preview

    async with db_session() as session:
        asset_id, _ = await _make_mira(session, tmp_path, tmp_path / "ws")
        asset = await session.get(Asset, asset_id)
        media = await session.get(MediaItem, (await session.get(AssetRevision, asset.current_revision_id)).primary_media_id)
    img = _generate_element_preview(media.file_path, 128)
    assert img.size == (128, 128)
    assert img.getpixel((64, 64))[0] > 150  # the red cover, not the placeholder


@pytest.mark.asyncio
async def test_generation_lineage_records_and_scrubs(db_session, tmp_path):
    from asset_deletion_service import prepare_asset_reference_deletion
    from elements.lineage import media_made_with, record_media_elements

    async with db_session() as session:
        asset_id, _ = await _make_mira(session, tmp_path, tmp_path / "ws")
        asset = await session.get(Asset, asset_id)
        output = await create_media_item(session, generation_metadata=json.dumps({"task_type": "text-to-image"}))
        entries = await record_media_elements(session, output.id, [
            {"asset_id": asset_id, "carrier": "lora+refs"},
            {"asset_id": 999999},  # unknown: skipped
        ])
        await session.commit()
        assert entries == [{"asset_id": asset_id, "revision_id": asset.current_revision_id, "name": "Mira",
                            "carrier": "lora+refs"}]
        await session.refresh(output)
        assert json.loads(output.generation_metadata)["elements"] == entries
        assert await media_made_with(session, asset_id) == [output.id]
        row = await session.scalar(select(MediaElement).where(MediaElement.media_id == output.id))
        assert row.element_revision_id == asset.current_revision_id

        await prepare_asset_reference_deletion(session, [asset_id])
        await session.commit()
        await session.refresh(output)
        assert "elements" not in json.loads(output.generation_metadata)
        assert await media_made_with(session, asset_id) == []
