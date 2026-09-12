"""Agent queries against real SQLite metadata, Assets, and provenance graphs."""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from agent.v2.code_runtime import StimmaLibraryAPI
from agent.v2.tools.library import library
from database import MediaLineage, Project, ProjectAsset
from asset_service import create_asset_from_media
from tests.helpers.media import create_media_item


async def call(session, action="browse", **kwargs):
    return json.loads(await library(action=action, session=session, **kwargs))


async def media(session, *, asset=True, **metadata):
    file_format = metadata.pop("file_format", "png")
    return await create_media_item(
        session,
        file_format=file_format,
        generation_metadata=json.dumps(metadata),
        materialize_asset=asset,
    )


async def link(
    session, source, output, task="image-to-video", relationship="derived", order=0
):
    edge = MediaLineage(
        source_media_id=source.id if source else None,
        media_id=output.id,
        task_type=task,
        relationship_type=relationship,
        source_order=order,
    )
    session.add(edge)
    await session.flush()
    return edge


async def test_prompt_fields_and_explicit_glob_have_identical_sdk_results(db_session):
    async with db_session() as session:
        original = await media(
            session,
            prompt="rendered",
            prompt_metadata={"original_prompt": "a Copper, lighthouse!"},
        )
        generated = await media(session, prompt="a copper lighthouse")
        imported = await create_media_item(
            session, extracted_prompt="a copper lighthouse", materialize_asset=True
        )
        percent = await media(session, prompt="100%_literal")
        distractor = await media(session, prompt="100xxliteral")
        ids = [original.id, generated.id, imported.id, percent.id, distractor.id]
        sdk = StimmaLibraryAPI(SimpleNamespace(session=session, project_id=None))
        results = await sdk.search("copper", filters={"media_ids": ids})
        assert {row["media_id"] for row in results} == {
            original.id,
            generated.id,
            imported.id,
        }
        filters = {
            "media_ids": ids,
            "prompt_query": {"include": ["*COPPER*light?ouse*"], "match": "glob"},
        }
        page = await call(session, filters=filters)
        assert page["total"] == 3
        assert (await sdk.query(filters))["items"] == page["items"]
        assert (await call(session, filters={"media_ids": ids, "prompt_query": "%_"}))[
            "total"
        ] == 1
        assert (
            await call(session, filters={"media_ids": ids, "prompt_query": "*copper*"})
        )["total"] == 0
        assert (
            await call(
                session,
                filters={
                    "media_ids": ids,
                    "prompt_query": {
                        "include": ["copper", "lighthouse"],
                        "mode": "all",
                    },
                },
            )
        )["total"] == 3


async def test_lora_shapes_basename_globs_all_exclude_and_facets(db_session):
    async with db_session() as session:
        first = await media(
            session,
            model="models/Klein-9B.safetensors",
            prompt="portrait",
            parameters={
                "loras": [
                    {"path": "styles/Portrait_v2.safetensors", "weight": 0.8},
                    {"lora": "detail.safetensors"},
                ]
            },
        )
        second = await media(
            session, model="Other", loras=[{"name": "Portrait_v3.safetensors"}]
        )
        third = await media(
            session, model="Other", parameters={"loras": ["flat.safetensors"]}
        )
        ids = [first.id, second.id, third.id]
        filters = {
            "media_ids": ids,
            "loras": {"include": ["portrait_*.safetensors"], "match": "glob"},
        }
        assert (await call(session, filters=filters))["total"] == 2
        filters["loras"]["exclude"] = ["*v3*"]
        page = await call(session, filters=filters)
        assert [row["media_id"] for row in page["items"]] == [first.id]
        filters["loras"] = {
            "include": ["portrait*", "detail*"],
            "match": "glob",
            "mode": "all",
        }
        filters["models"] = {"include": ["Klein-9B.safetensors"], "match": "exact"}
        assert (await call(session, filters=filters))["total"] == 1
        options = await call(
            session,
            "browse_options",
            facet="loras",
            filters={"media_ids": ids},
            limit=2,
        )
        assert options["next_cursor"] == "2"
        more = await call(
            session,
            "browse_options",
            facet="loras",
            filters={"media_ids": ids},
            limit=2,
            cursor=options["next_cursor"],
        )
        values = {item["id"] for item in options["items"] + more["items"]}
        assert values == {
            "styles/Portrait_v2.safetensors",
            "detail.safetensors",
            "Portrait_v3.safetensors",
            "flat.safetensors",
        }


async def test_videos_descended_from_klein_images_and_upscale_pairs(db_session):
    async with db_session() as session:
        image = await media(
            session, asset=False, model="Klein 9B", task_type="text-to-image"
        )
        video = await media(
            session,
            asset=False,
            file_format="mp4",
            model="video-model",
            task_type="image-to-video",
        )
        upscale = await media(
            session,
            file_format="mp4",
            task_type="upscale-video",
            source_inputs=[{"media_id": video.id, "role": "input_video"}],
        )
        unrelated = await media(session, file_format="mp4", task_type="upscale-video")
        await link(session, image, video)
        await link(session, video, upscale, "upscale-video")
        await link(session, image, unrelated, relationship="inspired")
        await session.commit()
        sdk = StimmaLibraryAPI(SimpleNamespace(session=session, project_id=None))
        candidates = await sdk.query(
            {"models": "klein", "media_types": ["images"], "media_ids": [image.id]},
            scope="media",
        )
        assert candidates["total"] == 1
        assert (await sdk.query({"media_ids": [image.id]}))["total"] == 0
        graph = await sdk.lineage(
            media_ids=[row["media_id"] for row in candidates["items"]],
            direction="descendants",
            filters={"media_types": ["videos"]},
        )
        assert {
            (edge["source_media_id"], edge["output_media_id"])
            for edge in graph["edges"]
        } == {(image.id, video.id), (video.id, upscale.id)}
        # Find the actual upscale step, then recover its original directly.
        outputs = await sdk.query(
            {"task_types": "upscale-video", "media_ids": [upscale.id]}
        )
        pairs = await sdk.lineage(
            media_ids=[row["media_id"] for row in outputs["items"]], direction="parents"
        )
        assert pairs["edges"][0]["source_media_id"] == video.id
        assert pairs["edges"][0]["input_role"] == "input_video"
        assert pairs["edges"][0]["task_type"] == "upscale-video"
        ancestors = await sdk.lineage(
            upscale.id, direction="ancestors", filters={"models": "klein"}
        )
        assert ancestors["total"] == 1  # Traverses through a nonmatching video.
        assert ancestors["edges"][0]["source_media_id"] == image.id
        assert (
            await sdk.lineage(image.id, direction="descendants", relationship="all")
        )["total"] == 3


async def test_recursive_cycles_diamonds_roots_and_pagination(db_session):
    async with db_session() as session:
        a, b, c, d = [await media(session) for _ in range(4)]
        await link(session, a, b)
        await link(session, a, c)
        await link(session, b, d, order=0)
        await link(session, c, d, order=1)
        await link(session, d, a)  # Bad historical data must still terminate.
        await session.commit()
        all_edges = []
        offset = 0
        while True:
            graph = await call(
                session,
                "lineage",
                media_ids=[a.id, b.id],
                direction="descendants",
                limit=3,
                offset=offset,
            )
            all_edges += graph["edges"]
            if not graph["has_more"]:
                break
            offset += 3
        assert graph["total"] == 10
        assert (
            len({(edge["root_media_id"], edge["edge_id"]) for edge in all_edges}) == 10
        )


async def test_unavailable_sources_and_large_history_remain_valid_json(db_session):
    async with db_session() as session:
        source = await media(session, asset=False)
        output = await media(
            session, lineage_trace=[{"prompt": "x" * 10000, "media_id": source.id}]
        )
        await link(session, source, output)
        external = await link(session, None, output, order=1)
        external.source_file_path = "/external/reference.png"
        source.deleted_at = datetime.now()
        await session.commit()
        graph = await call(
            session, "lineage", media_id=output.id, direction="ancestors"
        )
        assert {edge["source_status"] for edge in graph["edges"]} == {
            "deleted",
            "external",
        }
        details = await call(
            session, "inspect", media_ids=[output.id, source.id, 99999999]
        )
        assert len(details["items"][0]["history"][1]["prompt"]) == 10000
        assert details["items"][1]["status"] == "deleted"
        assert details["items"][2]["status"] == "missing"
        assert "path" not in details["items"][0]  # No workspace file copy.


@pytest.mark.parametrize(
    "kwargs",
    [
        {"filters": {"lora": "oops"}},
        {"filters": {"loras": {"match": "regex", "include": ["x"]}}},
        {"filters": {"prompt_query": {"include": ["x"], "unknown": True}}},
        {"filters": {"media_types": ["imaginary"]}},
        {"filters": {"generated": "true"}},
        {"filters": {"created_at": {"after": "yesterday"}}},
        {"filters": {"created_at": {"after": 42}}},
        {"limit": 0},
        {"offset": -1},
        {"sort_by": "bogus"},
        {"search_fields": "prompt"},
        {"direction": "parents"},
        {"loras": ["misplaced-criterion"]},
    ],
)
async def test_invalid_queries_fail_instead_of_broadening(db_session, kwargs):
    async with db_session() as session:
        with pytest.raises(ValueError):
            await library(action="browse", session=session, **kwargs)


async def test_search_filters_and_sdk_tags_are_not_ignored(db_session):
    async with db_session() as session:
        item = await media(session, prompt="unique-search-token", model="Klein")
        assert (
            await call(
                session,
                "search",
                query="unique-search-token",
                filters={"models": "Klein"},
            )
        )[0]["media_id"] == item.id
        sdk = StimmaLibraryAPI(SimpleNamespace(session=session, project_id=None))
        assert (
            await sdk.search(
                "unique-search-token", tags=["nonexistent-library-test-tag"]
            )
            == []
        )
        assert (
            await sdk.search("unique-search-token", filters={"models": "no-such-model"})
            == []
        )


async def test_project_facets_match_browse_and_metadata_scope_is_explicit(db_session):
    async with db_session() as session:
        inside = await media(session, asset=False, model="inside-model")
        outside = await media(session, model="outside-model")
        asset = await create_asset_from_media(session, media_id=inside.id)
        project = Project(name="library-query-project")
        session.add(project)
        await session.flush()
        session.add(ProjectAsset(project_id=project.id, asset_id=asset.id))
        await session.commit()
        sdk = StimmaLibraryAPI(SimpleNamespace(session=session, project_id=project.id))
        filters = {"media_ids": [inside.id, outside.id]}
        assert (await sdk.query(filters))["total"] == 1
        assert [
            row["id"] for row in (await sdk.options("models", filters=filters))["items"]
        ] == ["inside-model"]
        assert (await sdk.query(filters, scope="media"))["total"] == 2


async def test_pending_missing_files_and_malformed_metadata_are_inspectable(db_session):
    async with db_session() as session:
        item = await media(session, model="Recorded")
        item.metadata_status = "pending"
        item.file_unavailable = True
        broken = await media(session)
        broken.generation_metadata = "{invalid"
        await session.commit()
        page = await call(
            session, filters={"media_ids": [item.id, broken.id], "models": "Recorded"}
        )
        assert page["total"] == 1
        assert page["items"][0]["file_unavailable"] is True
        assert (await call(session, "inspect", media_id=broken.id))["items"][0][
            "provenance_status"
        ] == "unrecorded"
        assert (
            await call(
                session,
                filters={
                    "media_ids": [item.id, broken.id],
                    "models": {"include": ["*"], "match": "glob"},
                },
            )
        )["total"] == 1


async def test_path_separators_and_repeated_source_roles(db_session):
    async with db_session() as session:
        source = await media(session, model=r"models\Klein9B.safetensors")
        output = await media(
            session,
            source_inputs=[
                {"media_id": source.id, "role": "start_frame"},
                {"media_id": source.id, "role": "end_frame"},
            ],
        )
        await link(session, source, output, order=0)
        await link(session, source, output, order=1)
        await session.commit()
        for value in (
            r"models\Klein9B.safetensors",
            "models/Klein9B.safetensors",
            "Klein9B.safetensors",
        ):
            page = await call(
                session,
                filters={
                    "media_ids": [source.id],
                    "models": {"include": [value], "match": "exact"},
                },
            )
            assert page["total"] == 1
        graph = await call(session, "lineage", media_id=output.id)
        assert [edge["input_role"] for edge in graph["edges"]] == [
            "start_frame",
            "end_frame",
        ]
