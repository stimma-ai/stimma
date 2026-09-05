"""Sprite documents (.stimmasprite.json): type registration, container members,
content resolution, library save, revisions through show(), thumbnails, export.

A sprite is a recipe: media references by id + hash, a production block, and one
animated WebP per move. These tests build real WebPs and documents on disk and
drive the same code paths the agent and the UI use.
"""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image, ImageDraw
from sqlalchemy import select

from database import Asset, AssetRevision, ContainerMember, MediaItem
from tests.helpers.media import create_media_item


def _frames(n=6, size=(48, 64), color=(200, 60, 60, 255)):
    frames = []
    for i in range(n):
        im = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle([10, 20 + i, 38, 60], fill=color)
        frames.append(im)
    return frames


def _write_webp(path: Path, frames, fps=12) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        path, format="WEBP", save_all=True, append_images=frames[1:],
        duration=round(1000 / fps), loop=0, lossless=True,
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_png(path: Path, image) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _media_for(session, path: Path, digest: str, fmt: str, **kw) -> MediaItem:
    return await create_media_item(session, file_path=path, file_hash=digest, file_format=fmt, **kw)


def _doc(title, *, base, portrait, animations, production=None):
    return {
        "type": "sprite",
        "version": 1,
        "title": title,
        "description": "",
        "style": "16-bit pixel art",
        "base_image": base,
        "base_image_nobg": None,
        "portrait": portrait,
        "anchor": {"x": 0.5, "y": 1.0},
        "production": production or {
            "style": {"preset": "pixel-16bit", "fragment": "16-bit pixel art"},
            "key": {"rgb": [255, 0, 255], "phrase": "plain solid magenta (#FF00FF) background", "margin": 0.31},
            "cleanup_profile": {"name": "pixel", "overrides": {}},
            "frame_budget": 6,
            "fps": 12,
            "height_px": 64,
            "direction_scheme": "side",
        },
        "animations": animations,
    }


def _anim(name, direction, ref, frame_count, fps=12, loop="loop", **extra):
    entry = {
        "name": name,
        "direction": direction,
        "mirrored_from": None,
        "fps": fps,
        "loop": loop,
        "loop_start": 0,
        "loop_end": frame_count - 1,
        "source_video": None,
        "anchor": None,
        "prompt": None,
        "animation": {**ref, "format": "webp"},
        "frame_count": frame_count,
        "frames": [{"duration_ms": None, "rects": {}, "events": []} for _ in range(frame_count)],
    }
    entry.update(extra)
    return entry


@pytest.fixture(scope="module")
async def sprite_fixture(db_session, temp_appdata_dir: Path):
    """A sprite document on disk whose refs all resolve to library media."""
    root = temp_appdata_dir / "sprite-fixture"
    frames = _frames()
    run_path = root / "run_east.webp"
    run_hash = _write_webp(run_path, frames)
    idle_path = root / "idle.webp"
    idle_hash = _write_webp(idle_path, _frames(4), fps=8)
    base_path = root / "base.png"
    base_hash = _write_png(base_path, frames[0])
    portrait_path = root / "portrait.png"
    portrait_hash = _write_png(portrait_path, frames[0].crop((0, 0, 48, 32)))

    async with db_session() as session:
        run = await _media_for(session, run_path, run_hash, "webp", width=48, height=64)
        idle = await _media_for(session, idle_path, idle_hash, "webp", width=48, height=64)
        base = await _media_for(session, base_path, base_hash, "png", width=48, height=64)
        portrait = await _media_for(session, portrait_path, portrait_hash, "png", width=48, height=32)
        await session.commit()
        ids = {"run_id": run.id, "idle_id": idle.id, "base_id": base.id, "portrait_id": portrait.id}

        doc = _doc(
            "Fox Knight",
            base={"media_id": ids["base_id"], "hash": base_hash},
            portrait={"media_id": ids["portrait_id"], "hash": portrait_hash},
            animations=[
                _anim("run", "east", {"media_id": ids["run_id"], "hash": run_hash}, 6),
                # Hash-only reference (no media_id): must still resolve.
                _anim("idle", None, {"hash": idle_hash}, 4, fps=8, loop="pingpong"),
            ],
        )
        doc_path = root / "fox-knight.stimmasprite.json"
        doc_path.write_text(json.dumps(doc, indent=2))
        doc_hash = hashlib.sha256(doc_path.read_bytes()).hexdigest()
        sprite = await create_media_item(
            session,
            file_path=doc_path,
            file_hash=doc_hash,
            file_format="stimmasprite.json",
            width=0,
            height=0,
            raw_metadata=json.dumps(doc),
        )
        await session.commit()
        ids["sprite_id"] = sprite.id
        ids["doc_hash"] = doc_hash

        # Browsers list Assets, never bare Media: materialize the sprite container.
        from container_service import create_container_asset_from_media, infer_structured_member_specs

        asset = await create_container_asset_from_media(
            session,
            media_id=sprite.id,
            container_type="sprite",
            members=await infer_structured_member_specs(session, container_media=sprite),
            title=doc["title"],
            origin_type="test",
        )
        await session.commit()
        ids["asset_id"] = asset.id
    return {
        "root": root,
        "doc": doc,
        "doc_path": doc_path,
        **ids,
        "hashes": {"run": run_hash, "idle": idle_hash, "base": base_hash, "portrait": portrait_hash},
    }


# --- registration ------------------------------------------------------------

def test_sprite_is_a_registered_format():
    from asset_service import infer_asset_type
    from media_scanner import STRUCTURED_EXTENSIONS, get_file_extension
    from utils.query_builder import COMPOSITE_FORMATS, SPRITE_FORMATS, STRUCTURED_FORMATS, is_composite_media

    assert ".stimmasprite.json" in STRUCTURED_EXTENSIONS
    assert get_file_extension(Path("/x/fox.stimmasprite.json")) == ".stimmasprite.json"
    assert SPRITE_FORMATS == ["stimmasprite.json"]
    assert "stimmasprite.json" in COMPOSITE_FORMATS and "stimmasprite.json" in STRUCTURED_FORMATS
    assert is_composite_media({"file_format": "stimmasprite.json"})
    assert infer_asset_type(MediaItem(file_format="stimmasprite.json")) == "sprite"


def test_validate_sprite_document_reports_structural_problems():
    from sprite_document import iter_sprite_refs, validate_sprite_document

    good = _doc("Ok", base={"media_id": 1, "hash": "a" * 64}, portrait=None,
                animations=[_anim("run", "east", {"media_id": 2, "hash": "b" * 64}, 3)])
    assert validate_sprite_document(good) == []
    assert [role for role, _ in iter_sprite_refs(good)] == ["base_image", "run_east/animation"]

    bad = json.loads(json.dumps(good))
    bad["animations"][0]["loop_end"] = 9
    bad["animations"].append(_anim("run", "east", {"hash": "c" * 64}, 2))
    bad["base_image"] = {"media_id": 1}
    problems = validate_sprite_document(bad)
    assert any("loop_start" in p for p in problems)
    assert any("duplicate" in p for p in problems)
    assert any("base_image" in p and "hash" in p for p in problems)
    assert validate_sprite_document({"type": "grid"}) == ["type must be 'sprite'"]


# --- container membership + content ------------------------------------------

@pytest.mark.asyncio
async def test_member_specs_resolve_by_id_then_hash_and_embed_exactly(db_session, sprite_fixture):
    from sprite_document import sprite_member_specs

    async with db_session() as session:
        specs = await sprite_member_specs(session, sprite_fixture["doc"])
    by_role = {spec["title"]: spec for spec in specs}
    assert set(by_role) == {"base_image", "portrait", "run_east/animation", "idle/animation"}
    assert all("embedded_media_id" in spec and "linked_asset_id" not in spec for spec in specs)
    assert by_role["run_east/animation"]["embedded_media_id"] == sprite_fixture["run_id"]
    # Hash-only reference resolved to the idle WebP.
    assert by_role["idle/animation"]["embedded_media_id"] == sprite_fixture["idle_id"]


@pytest.mark.asyncio
async def test_content_endpoint_attaches_resolved_blocks(client: AsyncClient, sprite_fixture):
    response = await client.get(f"/api/media/{sprite_fixture['sprite_id']}/content")
    assert response.status_code == 200, response.text
    content = response.json()
    assert content["type"] == "sprite"
    assert content["base_image"]["resolved"]["media_id"] == sprite_fixture["base_id"]
    assert content["base_image"]["resolved"]["file_hash"] == sprite_fixture["hashes"]["base"]
    run = next(a for a in content["animations"] if a["name"] == "run")
    idle = next(a for a in content["animations"] if a["name"] == "idle")
    assert run["animation"]["resolved"]["file_hash"] == sprite_fixture["hashes"]["run"]
    assert idle["animation"]["resolved"]["media_id"] == sprite_fixture["idle_id"]
    assert content["production"]["key"]["phrase"].startswith("plain solid magenta")


@pytest.mark.asyncio
async def test_browse_filters_sprites(client: AsyncClient, sprite_fixture):
    response = await client.get("/api/media", params={"media_types": "sprites"})
    assert response.status_code == 200
    formats = {item["file_format"] for item in response.json()["items"]}
    assert formats == {"stimmasprite.json"}


# --- library save materializes a sprite container ---------------------------

@pytest.mark.asyncio
async def test_library_save_registers_a_sprite_container(db_session, sprite_fixture, temp_appdata_dir: Path):
    from agent.v2.tools.library import save_workspace_file
    from sprite_document import validate_sprite_document

    workspace = temp_appdata_dir / "sprite-workspace"
    workspace.mkdir(exist_ok=True)
    doc = json.loads(json.dumps(sprite_fixture["doc"]))
    doc["title"] = "Saved Fox"
    assert validate_sprite_document(doc) == []
    path = workspace / "saved-fox.stimmasprite.json"
    path.write_text(json.dumps(doc))

    async with db_session() as session:
        raw = await save_workspace_file(
            session=session,
            path=str(path),
            workspace_dir=workspace,
            save_tags=None,
            provenance={"task_type": "code", "tool_id": "run_code", "parameters": {},
                        "seed": None, "source_media_ids": [sprite_fixture["run_id"]]},
            materialize_asset=True,
        )
        assert not raw.startswith("Error"), raw
        saved = json.loads(raw)
        media = await session.get(MediaItem, saved["media_id"])
        assert media.file_format == "stimmasprite.json"
        assert media.clip_status == "skipped" and media.vlm_caption_status == "skipped"
        assert json.loads(media.raw_metadata)["title"] == "Saved Fox"

        asset = await session.get(Asset, saved["asset_id"])
        assert asset.asset_type == "sprite" and asset.title == "Saved Fox"
        members = list(await session.scalars(
            select(ContainerMember).where(ContainerMember.container_revision_id == asset.current_revision_id)
        ))
        assert {m.embedded_media_id for m in members} == {
            sprite_fixture["run_id"], sprite_fixture["idle_id"],
            sprite_fixture["base_id"], sprite_fixture["portrait_id"],
        }

        # Invalid documents are rejected before anything is registered.
        broken = workspace / "broken.stimmasprite.json"
        broken.write_text(json.dumps({"type": "sprite", "version": 1, "animations": []}))
        raw = await save_workspace_file(
            session=session, path=str(broken), workspace_dir=workspace, save_tags=None, materialize_asset=True,
        )
        assert raw.startswith("Error: invalid sprite document") and "title" in raw


# --- revisions through show(revises=) ---------------------------------------

@pytest.mark.asyncio
async def test_show_revises_commits_a_sprite_container_revision(db_session, sprite_fixture, temp_appdata_dir: Path):
    from agent.v2.tools.library import save_workspace_file
    from agent.v2.tools.show import show
    from container_service import get_normalized_container_content
    from database import Chat

    workspace = temp_appdata_dir / "sprite-revise"
    workspace.mkdir(exist_ok=True)
    v1 = json.loads(json.dumps(sprite_fixture["doc"]))
    v1["title"] = "Revised Fox"
    v1["animations"] = v1["animations"][:1]  # run only
    p1 = workspace / "revised-fox.stimmasprite.json"
    p1.write_text(json.dumps(v1))
    v2 = json.loads(json.dumps(sprite_fixture["doc"]))
    v2["title"] = "Revised Fox"
    p2 = workspace / "revised-fox-v2.stimmasprite.json"
    p2.write_text(json.dumps(v2))

    async with db_session() as session:
        chat = Chat(name="sprite revisions")
        session.add(chat)
        await session.commit()

        saved = json.loads(await save_workspace_file(
            session=session, path=str(p1), workspace_dir=workspace, save_tags=None, materialize_asset=True,
        ))
        asset_id = saved["asset_id"]
        saved2 = json.loads(await save_workspace_file(
            session=session, path=str(p2), workspace_dir=workspace, save_tags=None, materialize_asset=False,
        ))

        result = await show(
            role="final",
            media_id=saved2["media_id"],
            revises=asset_id,
            revision_note="added idle",
            session=session,
            chat_id=chat.id,
        )
        assert not result.startswith("Error"), result
        revisions = list(await session.scalars(
            select(AssetRevision).where(AssetRevision.asset_id == asset_id).order_by(AssetRevision.revision_number)
        ))
        assert [r.revision_number for r in revisions] == [1, 2]
        assert revisions[1].note == "added idle"
        members = list(await session.scalars(
            select(ContainerMember).where(ContainerMember.container_revision_id == revisions[1].id)
        ))
        assert sprite_fixture["idle_id"] in {m.embedded_media_id for m in members}

        media2 = await session.get(MediaItem, saved2["media_id"])
        content = await get_normalized_container_content(session, container_media=media2)
        assert content is not None and content["title"] == "Revised Fox"
        assert {a["name"] for a in content["animations"]} == {"run", "idle"}
        assert content["animations"][0]["animation"]["resolved"]["media_id"] == sprite_fixture["run_id"]


# --- thumbnail ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_sprite_thumbnail_is_portrait_with_filmstrip(client: AsyncClient, sprite_fixture):
    from routes.media_files import THEME_PALETTES, _generate_sprite_preview
    from sprite_document import sprite_thumbnail_sources

    # Resolved content as the container/content layer would hand it over.
    resolved = json.loads(json.dumps(sprite_fixture["doc"]))
    resolved["portrait"]["resolved"] = {"file_path": str(sprite_fixture["root"] / "portrait.png")}
    resolved["animations"][0]["animation"]["resolved"] = {"file_path": str(sprite_fixture["root"] / "run_east.webp")}
    sources = sprite_thumbnail_sources(resolved)
    assert sources["hero"].endswith("portrait.png") and sources["animation"].endswith("run_east.webp")

    img = _generate_sprite_preview(str(sprite_fixture["doc_path"]), 256, palette=THEME_PALETTES["dark"], normalized_content=resolved)
    assert img.size == (256, 256)
    # Filmstrip footer occupies the bottom band: a strip cell pixel is not the matte colour.
    assert img.getpixel((4, 250)) != img.getpixel((4, 4))


@pytest.mark.asyncio
async def test_thumbnail_route_serves_sprite(client: AsyncClient, sprite_fixture):
    # The media-id route redirects to the content-addressed thumbnail; hit that directly.
    response = await client.get(f"/api/thumbnail/{sprite_fixture['doc_hash']}", params={"size": 128})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("image/")


# --- export ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_targets_listed(client: AsyncClient):
    response = await client.get("/sprite-export/targets")
    assert response.status_code == 200
    groups = {g["id"]: [t["id"] for t in g["targets"]] for g in response.json()["groups"]}
    assert "godot" in groups["engines"] and "frames" in groups["generic"] and "gif" in groups["preview"]


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [
    "atlas-hash", "atlas-array", "godot", "unity", "unreal", "gamemaker", "defold",
    "libgdx", "cocos2d", "frames", "grid-sheet", "strips", "stills", "gif", "webp", "apng",
])
async def test_export_route_produces_each_target(client: AsyncClient, sprite_fixture, target):
    response = await client.post(
        f"/media/{sprite_fixture['sprite_id']}/sprite-export",
        json={"format": target, "extrude": 1, "padding": 1},
    )
    assert response.status_code == 200, response.text
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    if response.headers["content-type"] == "application/zip":
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            names = zf.namelist()
            assert "manifest.json" in names
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["target"] == target
            assert manifest["anchor"] == {"x": 0.5, "y": 1.0}
            if target != "stills":
                assert {a["key"] for a in manifest["animations"]} == {"run_east", "idle"}
            if target in ("atlas-hash", "unity"):
                atlas = json.loads(zf.read("fox-knight.json"))
                assert set(atlas["frames"]) >= {"run_east/0", "idle/3"}
                assert atlas["frames"]["run_east/0"]["pivot"] == {"x": 0.5, "y": 1.0}
                assert [t["name"] for t in atlas["meta"]["frameTags"]] == ["run_east", "idle"]
            if target == "godot":
                tres = zf.read("fox-knight.tres").decode()
                assert 'type="SpriteFrames"' in tres and '&"run_east"' in tres and '"loop": true' in tres
            if target == "cocos2d":
                assert zf.read("fox-knight.plist").decode().startswith("<?xml")
            if target == "frames":
                assert "run_east/frame_000.png" in names and "idle/frame_003.png" in names
    else:
        assert len(response.content) > 0


@pytest.mark.asyncio
async def test_export_route_validates(client: AsyncClient, sprite_fixture):
    media_id = sprite_fixture["sprite_id"]
    response = await client.post(f"/media/{media_id}/sprite-export", json={"format": "rpgmaker"})
    assert response.status_code == 400
    assert "south, west, east, north" in response.json()["detail"]

    response = await client.post(f"/media/{media_id}/sprite-export", json={"format": "vhs"})
    assert response.status_code == 400 and "Unsupported" in response.json()["detail"]

    response = await client.post(f"/media/{media_id}/sprite-export", json={"format": "atlas-hash", "animations": ["nope"]})
    assert response.status_code == 400 and "subset" in response.json()["detail"]

    response = await client.post(f"/media/{sprite_fixture['run_id']}/sprite-export", json={"format": "gif"})
    assert response.status_code == 400 and "Not a sprite" in response.json()["detail"]


def test_export_geometry_scale_trim_extrude():
    from sprite_export import ExportAnimation, SpriteExportOptions, SpriteSource, run_sprite_export

    frames = _frames()
    source = SpriteSource(
        title="Geo", base_name="geo", anchor=(0.5, 1.0), pixelated=True,
        animations=[ExportAnimation("run", "east", 12.0, "loop", 0, 5, frames, [83] * 6)],
    )
    result = run_sprite_export(
        source, SpriteExportOptions(format="atlas-hash", scale=2, extrude=2, padding=4, trim=True)
    )
    with zipfile.ZipFile(io.BytesIO(result.payload)) as zf:
        atlas = json.loads(zf.read("geo.json"))
        rect = atlas["frames"]["run_east/1"]["frame"]
        # Trim to the union bbox (29×41 opaque box), then 2× nearest.
        assert (rect["w"], rect["h"]) == (58, 82), rect
        sheet = Image.open(io.BytesIO(zf.read("geo.png")))
        inside = sheet.getpixel((rect["x"], rect["y"] + 40))
        bleed = sheet.getpixel((rect["x"] - 2, rect["y"] + 40))       # extrude band
        beyond = sheet.getpixel((rect["x"] - 3, rect["y"] + 40))      # padding gap
        assert inside == bleed == (200, 60, 60, 255) and beyond[3] == 0
        # Anchor follows the trim: (0.5 * 48 - 10) / 29.
        assert atlas["frames"]["run_east/1"]["pivot"]["x"] == round(14 / 29, 4)

    result = run_sprite_export(source, SpriteExportOptions(format="grid-sheet", power_of_two=True))
    with zipfile.ZipFile(io.BytesIO(result.payload)) as zf:
        sheet = Image.open(io.BytesIO(zf.read("geo_run_east.png")))
        assert sheet.width & (sheet.width - 1) == 0 and sheet.height & (sheet.height - 1) == 0

    with pytest.raises(Exception) as excinfo:
        run_sprite_export(source, SpriteExportOptions(format="atlas-hash", max_sheet_size=64))
    assert "over the 64px limit" in str(excinfo.value)
