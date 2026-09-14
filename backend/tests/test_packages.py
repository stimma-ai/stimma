"""Packages: recipes, bundles, covers, rebuild, exports and routes."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

from database import Asset, AssetRevision, ContainerMember, MediaItem
from packages import cache as run_cache
from packages.bundle import PackageBuilder, package_status, rebuild_package
from packages.cover import CoverError
from packages.export import export_single_html, export_zip
from packages.manifest import read_manifest, sha256_file
from packages.naming import NamingError, expand_name, parse_naming
from packages.recipes import (
    RecipeError,
    ResolvedInput,
    check_determinism,
    describe_file,
    get_recipe,
    list_recipes,
    run_recipe,
)
from tests.helpers.media import create_media_item


def _write_icon(path: Path, size: int = 1200, color=(20, 120, 200, 255)) -> str:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((size * 0.1, size * 0.1, size * 0.9, size * 0.9), fill=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")
    return sha256_file(path)


async def _media(session, path: Path, *, materialize_asset: bool = False) -> MediaItem:
    with Image.open(path) as img:
        w, h = img.size
    return await create_media_item(
        session,
        file_path=path,
        file_hash=sha256_file(path),
        file_size=path.stat().st_size,
        width=w,
        height=h,
        materialize_asset=materialize_asset,
    )


def _resolved(role: str, path: Path) -> ResolvedInput:
    return ResolvedInput(role=role, path=path, hash=sha256_file(path), **describe_file(path))


# Recipes ---------------------------------------------------------------------

def test_builtin_recipes_are_listed():
    ids = {r.id for r in list_recipes()}
    assert {"app-icons", "logo", "key-art-crops"} <= ids


@pytest.mark.asyncio
async def test_app_icons_recipe_builds_xcode_tree(tmp_path):
    _write_icon(tmp_path / "master.png")
    spec = get_recipe("app-icons")
    result = await run_recipe(spec, {"master": _resolved("master", tmp_path / "master.png")}, {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["ios", "web"]}, tmp_path / "out", slug="acme")
    paths = {f.path for f in result.files}
    assert "ios/AppIcon.appiconset/Contents.json" in paths
    assert "ios/AppIcon.appiconset/icon-1024.png" in paths
    assert "web/favicon.ico" in paths
    contents = json.loads((tmp_path / "out/ios/AppIcon.appiconset/Contents.json").read_text())
    assert any(e.get("filename") == "icon-180.png" for e in contents["images"])
    assert "web/site.webmanifest" in paths


@pytest.mark.asyncio
async def test_app_icons_rejects_non_square(tmp_path):
    img = Image.new("RGBA", (1200, 800), (255, 0, 0, 255))
    img.save(tmp_path / "wide.png")
    spec = get_recipe("app-icons")
    with pytest.raises(RecipeError, match="square"):
        await run_recipe(spec, {"master": _resolved("master", tmp_path / "wide.png")}, {}, tmp_path / "out")


@pytest.mark.asyncio
async def test_builtin_recipes_are_deterministic(tmp_path):
    _write_icon(tmp_path / "master.png")
    hero = Image.new("RGB", (2400, 1600), (200, 80, 40))
    hero.save(tmp_path / "hero.jpg", quality=90)
    assert await check_determinism(get_recipe("app-icons"), {"master": _resolved("master", tmp_path / "master.png")}, {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["ios"]}) == []
    assert await check_determinism(get_recipe("key-art-crops"), {"master": _resolved("master", tmp_path / "hero.jpg")}, {"aspects": ["16x9", "1x1"]}) == []
    assert await check_determinism(get_recipe("logo"), {"primary": _resolved("primary", tmp_path / "master.png")}, {"png_widths": ["512"], "avatar_background": "#FFFFFF"}) == []


def test_naming_templates():
    naming = parse_naming("{slug}-logo-{variant}-{color}", fields=["slug", "variant", "color"], default_template="x")
    assert expand_name(naming, ext="png", slug="Acme Co", variant="mark", color="") == "acme-co-logo-mark.png"
    snake = parse_naming({"template": "{slug}_{variant}", "case": "snake"}, fields=["slug", "variant"], default_template="x")
    assert expand_name(snake, ext="svg", slug="Acme", variant="Wordmark") == "acme_wordmark.svg"
    with pytest.raises(NamingError):
        parse_naming("{nope}", fields=["slug"], default_template="x")
    with pytest.raises(NamingError):
        parse_naming("a/b", fields=["slug"], default_template="x")


# Bundles ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_builder_saves_package_with_run_and_asset(db_session, tmp_path):
    _write_icon(tmp_path / "master.png")
    async with db_session() as session:
        master = await _media(session, tmp_path / "master.png")
        async with PackageBuilder(session, profile_id="default", title="Acme icons") as builder:
            mid = await builder.add_member(master.id, role="master")
            rid = await builder.run("app-icons", {"master": mid}, {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["ios"]})
            media, asset = await builder.save(materialize_asset=True)
        assert media.file_format == "stimmapackage"
        assert asset is not None and asset.asset_type == "package"
        bundle = Path(media.file_path)
        assert (bundle / "index.html").is_file()
        assert (bundle / "stimma-package.json").is_file()
        assert (bundle / "app-icons/ios/AppIcon.appiconset/Contents.json").is_file()
        assert (bundle / "members/master.png").is_file()
        manifest = read_manifest(bundle)
        assert manifest["members"][0]["hash"] == master.file_hash
        assert manifest["runs"][0]["id"] == rid and manifest["runs"][0]["recipe"]["id"] == "app-icons"
        assert manifest["cover"]["kind"] == "auto"
        rows = list(await session.scalars(select(ContainerMember).where(ContainerMember.container_revision_id == asset.current_revision_id)))
        assert len(rows) == 1 and rows[0].embedded_media_id == master.id and rows[0].title == mid
        status = await package_status(session, media)
        assert status["stale"] is False and status["asset_id"] == asset.id


@pytest.mark.asyncio
async def test_runs_are_memoized(db_session, tmp_path):
    _write_icon(tmp_path / "master.png")
    run_cache.clear("default")
    async with db_session() as session:
        master = await _media(session, tmp_path / "master.png")
        async with PackageBuilder(session, profile_id="default", title="one") as b1:
            await b1.run("key-art-crops", {"master": await b1.add_member(master.id)}, {"aspects": ["1x1"]})
            assert b1.runs[0].cached is False
            await b1.save()
        async with PackageBuilder(session, profile_id="default", title="two") as b2:
            await b2.run("key-art-crops", {"master": await b2.add_member(master.id)}, {"aspects": ["1x1"]})
            assert b2.runs[0].cached is True
            media, _ = await b2.save()
        assert (Path(media.file_path) / "key-art-crops/1x1").is_dir()
    assert run_cache.stats("default").entries >= 1
    assert run_cache.enforce_budget("default", max_entries=0) >= 1
    assert run_cache.stats("default").entries == 0


@pytest.mark.asyncio
async def test_stale_after_master_revision_and_rebuild(db_session, tmp_path):
    from asset_service import commit_revision

    _write_icon(tmp_path / "v1.png")
    _write_icon(tmp_path / "v2.png", color=(200, 30, 30, 255))
    async with db_session() as session:
        master = await _media(session, tmp_path / "v1.png", materialize_asset=True)
        master_rev = await session.scalar(select(AssetRevision).where(AssetRevision.primary_media_id == master.id))
        async with PackageBuilder(session, profile_id="default", title="Acme icons") as builder:
            await builder.run("app-icons", {"master": await builder.add_member(master.id, role="master")}, {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["web"]})
            builder.set_cover('<h1>Acme</h1><stimma-media ref="m1"></stimma-media><stimma-files ref="r1"></stimma-files>')
            media, asset = await builder.save(materialize_asset=True)
        rows = list(await session.scalars(select(ContainerMember).where(ContainerMember.container_revision_id == asset.current_revision_id)))
        assert rows[0].linked_asset_id == master_rev.asset_id
        assert (await package_status(session, media))["stale"] is False

        v2 = await _media(session, tmp_path / "v2.png")
        await commit_revision(session, asset_id=master_rev.asset_id, media_id=v2.id)
        await session.commit()
        status = await package_status(session, media)
        assert status["stale"] is True
        assert status["members"][0]["current_hash"] == v2.file_hash

        new_media, same_asset, report = await rebuild_package(session, profile_id="default", asset_id=asset.id)
        assert same_asset.id == asset.id
        assert report["was_stale"] is True and report["cover_carried_unchanged"] is True
        assert report["runs"][0]["reused_cache"] is False
        refreshed = await session.get(Asset, asset.id)
        head = await session.get(AssetRevision, refreshed.current_revision_id)
        assert head.primary_media_id == new_media.id and head.revision_number == 2
        assert (await package_status(session, new_media))["stale"] is False
        new_manifest = read_manifest(Path(new_media.file_path))
        assert new_manifest["members"][0]["hash"] == v2.file_hash
        assert new_manifest["cover"]["kind"] == "authored"
        assert "<h1>Acme</h1>" in (Path(new_media.file_path) / "index.html").read_text()


@pytest.mark.asyncio
async def test_cover_lint_and_expansion(db_session, tmp_path):
    _write_icon(tmp_path / "master.png")
    async with db_session() as session:
        master = await _media(session, tmp_path / "master.png")
        async with PackageBuilder(session, profile_id="default", title="lint") as builder:
            await builder.add_member(master.id, role="master")
            builder.set_cover('<img src="https://example.com/x.png">')
            with pytest.raises(CoverError, match="external URL"):
                await builder.save()
        async with PackageBuilder(session, profile_id="default", title="lint2") as builder:
            await builder.add_member(master.id, role="master")
            builder.set_cover('<stimma-media ref="missing"></stimma-media>')
            with pytest.raises(CoverError, match="does not resolve"):
                await builder.save()
        async with PackageBuilder(session, profile_id="default", title="ok") as builder:
            await builder.add_member(master.id, role="master")
            builder.set_cover('<style>h1{color:red}</style><h1>Hi</h1><stimma-grid><stimma-media ref="m1" caption="Master"/></stimma-grid>')
            media, _ = await builder.save()
        html = (Path(media.file_path) / "index.html").read_text()
        assert '<img src="members/master.png"' in html
        assert 'id="m1-1"' in html and "Master" in html and "h1{color:red}" in html
        assert 'id="stimma-package-manifest"' in html and '"media_id"' not in html.split("stimma-package-manifest")[1].split("</script>")[0]


@pytest.mark.asyncio
async def test_exports(db_session, tmp_path):
    _write_icon(tmp_path / "master.png")
    async with db_session() as session:
        master = await _media(session, tmp_path / "master.png")
        async with PackageBuilder(session, profile_id="default", title="Export me") as builder:
            await builder.run("app-icons", {"master": await builder.add_member(master.id)}, {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["web"]})
            (tmp_path / "brief.txt").write_text("the brief")
            builder.add_extra(tmp_path / "brief.txt")
            media, _ = await builder.save()
        bundle = Path(media.file_path)
        manifest = read_manifest(bundle)
        data = export_zip(bundle, manifest, folder_name="export-me")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            assert "export-me/index.html" in names
            assert "export-me/stimma-package.json" in names
            assert "export-me/app-icons/web/favicon.ico" in names
            assert "export-me/app-icons.zip" in names
            assert "export-me/extras/brief.txt" in names
            assert not any("/_stimma/" in n for n in names)
            with zipfile.ZipFile(io.BytesIO(zf.read("export-me/app-icons.zip"))) as inner:
                assert "web/favicon.ico" in inner.namelist()
                # The run zip carries the page it came with, and that page
                # opens on its own: previews inlined, nothing fetched.
                assert "index.html" in inner.namelist()
                page = inner.read("index.html").decode("utf-8")
                assert 'data-stimma-single-file="1"' in page
                assert "data:image/png;base64," in page
        single = export_single_html(bundle)
        assert "data:image/png;base64," in single
        assert 'data-stimma-single-file="1"' in single


# Routes ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_package_routes(client, db_session, tmp_path):
    _write_icon(tmp_path / "master.png")
    async with db_session() as session:
        master = await _media(session, tmp_path / "master.png")
        master_id = master.id

    recipes = (await client.get("/api/packages/recipes")).json()["recipes"]
    assert any(r["id"] == "app-icons" and any(i["name"] == "master" for i in r["inputs"]) for r in recipes)

    created = await client.post("/api/packages", json={
        "title": "Route icons", "media_ids": [master_id], "recipe": "app-icons",
        "inputs": {"master": master_id}, "params": {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["ios"]},
    })
    assert created.status_code == 200, created.text
    media_id = created.json()["media_id"]
    asset_id = created.json()["asset_id"]
    assert asset_id

    info = (await client.get(f"/api/media/{media_id}/package")).json()
    assert info["manifest"]["title"] == "Route icons"
    assert info["status"]["stale"] is False and info["status"]["runs"][0]["recipe"]["id"] == "app-icons"

    cover = await client.get(f"/api/media/{media_id}/package-file/index.html")
    assert cover.status_code == 200 and 'data-stimma-host="local"' in cover.text
    contents = await client.get(f"/api/media/{media_id}/package-file/app-icons/ios/AppIcon.appiconset/Contents.json")
    assert contents.status_code == 200 and "images" in contents.json()
    run_zip = await client.get(f"/api/media/{media_id}/package-file/app-icons.zip")
    assert run_zip.status_code == 200 and run_zip.headers["content-type"] == "application/zip"
    assert (await client.get(f"/api/media/{media_id}/package-file/../../etc/passwd")).status_code == 404

    exported = await client.post(f"/api/media/{media_id}/package-export", json={"format": "zip"})
    assert exported.status_code == 200 and "route-icons.zip" in exported.headers["content-disposition"]
    html = await client.post(f"/api/media/{media_id}/package-export", json={"format": "html"})
    assert html.status_code == 200 and "data:image" in html.text
    assert (await client.post(f"/api/media/{media_id}/package-export", json={"format": "link"})).status_code == 501

    status = await client.get(f"/api/assets/{asset_id}/package/status")
    assert status.status_code == 200 and status.json()["stale"] is False
    rebuilt = await client.post(f"/api/assets/{asset_id}/package/rebuild", json={})
    assert rebuilt.status_code == 200 and rebuilt.json()["report"]["runs"][0]["reused_cache"] is True

    content = await client.get(f"/api/media/{media_id}/content")
    assert content.status_code == 200 and content.json()["members"][0]["resolved"]["media_id"] == master_id

    bad = await client.post("/api/packages", json={"title": "x", "media_ids": [master_id], "recipe": "nope"})
    assert bad.status_code == 400
