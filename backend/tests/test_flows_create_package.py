"""The ``create_package()`` flow primitive and its production evaluator.

Build time: the DSL registers one ``create_package`` equation whose static
identity (recipe + params + title/description) is folded into the
definition hash, with members and role inputs left as dynamic bindings.
Evaluation time: the evaluator assembles a real ``.stimmapackage`` bundle
through ``PackageBuilder`` and returns its media id.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from database import MediaItem
from flow_dsl import (
    ProgramLoadError,
    build_graph_from_callable,
    code,
    create_package,
    flow,
    output as dsl_output,
    phase,
)
from flow_runtime.dry_run import build_dry_run_registry
from flow_runtime.evaluators import TOOL_ERROR, EvaluationRequest, EvaluatorError
from flow_runtime.graph import EquationType
from flow_runtime.production_evaluators import CreatePackageEvaluator
from flow_runtime.store_key import (
    STOREABLE_EQUATION_TYPES,
    definition_hash_for_create_package,
)
from packages.manifest import read_manifest, sha256_file
from tests.helpers.media import create_media_item


def _write_icon(path: Path, size: int = 1200, color=(20, 120, 200, 255)) -> str:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((size * 0.1, size * 0.1, size * 0.9, size * 0.9), fill=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")
    return sha256_file(path)


async def _media(session, path: Path) -> MediaItem:
    with Image.open(path) as img:
        w, h = img.size
    return await create_media_item(
        session,
        file_path=path,
        file_hash=sha256_file(path),
        file_size=path.stat().st_size,
        width=w,
        height=h,
    )


# ----- Build time -----------------------------------------------------------


def _package_flow():
    @flow(name="r", outputs={"pkg": dsl_output("media")})
    def r():
        with phase("P"):
            members = code(lambda: [1, 2], output_type="list[media]")
            master = code(lambda: 1, output_type="media")
            return create_package(
                members,
                recipe="tiles",
                inputs={"master": master},
                params={"background": "#FFFFFF", "app_name": "Acme", "platforms": ["ios"]},
                title="Acme icons",
                description="handoff",
            )

    return r


def test_create_package_registers_one_equation():
    g = build_graph_from_callable(_package_flow())
    (eq,) = [
        e for e in g.all_equations()
        if e.equation_type == EquationType.CREATE_PACKAGE
    ]

    assert eq.definition["title"] == "Acme icons"
    assert eq.definition["description"] == "handoff"
    assert eq.definition["recipe"] == "tiles"
    assert eq.definition["params"] == {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["ios"]}
    assert eq.definition["input_roles"] == {"master": "dynamic"}
    # Members and each role input are dynamic bindings, so both producers
    # are dependencies of the package step.
    assert set(eq.definition["_dynamic"]) == {"members", "input:master"}
    assert len(eq.dependencies) == 2


def test_create_package_definition_hash_covers_static_identity():
    g = build_graph_from_callable(_package_flow())
    (eq,) = [
        e for e in g.all_equations()
        if e.equation_type == EquationType.CREATE_PACKAGE
    ]

    assert eq.definition["definition_hash"] == definition_hash_for_create_package(
        "tiles", {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["ios"]}, "Acme icons", "handoff",
    )
    # Params are part of the step's identity: a different platform list is a
    # different build.
    assert definition_hash_for_create_package(
        "tiles", {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["web"]}, "Acme icons", "handoff",
    ) != eq.definition["definition_hash"]
    assert "create_package" in STOREABLE_EQUATION_TYPES


def test_create_package_without_recipe_is_members_only():
    @flow(name="r", outputs={"pkg": dsl_output("media")})
    def r():
        with phase("P"):
            members = code(lambda: [1], output_type="list[media]")
            return create_package(members, title="Bare")

    g = build_graph_from_callable(r)
    (eq,) = [
        e for e in g.all_equations()
        if e.equation_type == EquationType.CREATE_PACKAGE
    ]
    assert eq.definition["recipe"] is None
    assert eq.definition["input_roles"] == {}
    assert set(eq.definition["_dynamic"]) == {"members"}


def test_create_package_rejects_node_params():
    @flow(name="r", outputs={"pkg": dsl_output("media")})
    def r():
        with phase("P"):
            members = code(lambda: [1], output_type="list[media]")
            sizes = code(lambda: ["ios"], output_type="json")
            return create_package(
                members, recipe="tiles", params={"background": "#FFFFFF", "app_name": "Acme", "platforms": sizes},
            )

    with pytest.raises(ProgramLoadError, match="params must be static"):
        build_graph_from_callable(r)


def test_create_package_rejects_inputs_without_recipe():
    @flow(name="r", outputs={"pkg": dsl_output("media")})
    def r():
        with phase("P"):
            members = code(lambda: [1], output_type="list[media]")
            master = code(lambda: 1, output_type="media")
            return create_package(members, inputs={"master": master})

    with pytest.raises(ProgramLoadError, match="only meaningful with a recipe"):
        build_graph_from_callable(r)


def test_create_package_rejects_non_media_members():
    @flow(name="r", outputs={"pkg": dsl_output("media")})
    def r():
        with phase("P"):
            names = code(lambda: ["a"], output_type="list[str]")
            return create_package(names)

    with pytest.raises(ProgramLoadError, match="expected list\\[media\\]"):
        build_graph_from_callable(r)


# ----- Evaluation -----------------------------------------------------------


def _request(*, members, definition, inputs=None) -> EvaluationRequest:
    resolved = {"members": list(members)}
    resolved.update(inputs or {})
    return EvaluationRequest(
        equation_key="r/create_package$0",
        equation_type="create_package",
        attempt=1,
        definition=definition,
        resolved_inputs=resolved,
        flow_id=None,  # skips the flow-tagging DB path
        project_id=None,
    )


@pytest.mark.asyncio
async def test_evaluator_builds_bundle_with_members_and_run(db_session, tmp_path):
    _write_icon(tmp_path / "master.png")
    _write_icon(tmp_path / "shot.png", color=(200, 40, 40, 255))
    async with db_session() as session:
        master = await _media(session, tmp_path / "master.png")
        shot = await _media(session, tmp_path / "shot.png")
        master_id, shot_id = master.id, shot.id
        master_hash, shot_hash = master.file_hash, shot.file_hash

    result = await CreatePackageEvaluator()(_request(
        members=[shot_id],
        inputs={"input:master": master_id},
        definition={
            "title": "Acme icons",
            "description": "",
            "recipe": "tiles",
            "params": {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["ios"]},
            "input_roles": {"master": "dynamic"},
        },
    ))

    assert result.media_ids == [result.value]
    async with db_session() as session:
        media = await session.get(MediaItem, result.value)
    assert media is not None and media.file_format == "stimmapackage"

    bundle = Path(media.file_path)
    manifest = read_manifest(bundle)
    assert {m["hash"] for m in manifest["members"]} == {master_hash, shot_hash}
    assert [m["role"] for m in manifest["members"] if m["role"]] == ["master"]
    assert manifest["title"] == "Acme icons"
    (run,) = manifest["runs"]
    assert run["recipe"]["id"] == "tiles"
    assert run["params"]["platforms"] == ["ios"]
    assert (bundle / "tiles/ios/tile-256.png").is_file()
    assert (bundle / "index.html").is_file()


@pytest.mark.asyncio
async def test_evaluator_role_input_is_not_duplicated_as_member(db_session, tmp_path):
    """A media that is both a member and a recipe input joins once, with its role."""
    _write_icon(tmp_path / "solo.png", color=(10, 160, 90, 255))
    async with db_session() as session:
        solo = await _media(session, tmp_path / "solo.png")
        solo_id = solo.id

    result = await CreatePackageEvaluator()(_request(
        members=[solo_id],
        inputs={"input:master": solo_id},
        definition={
            "title": "Solo",
            "description": "",
            "recipe": "tiles",
            "params": {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["web"]},
            "input_roles": {"master": "dynamic"},
        },
    ))

    async with db_session() as session:
        media = await session.get(MediaItem, result.value)
    manifest = read_manifest(Path(media.file_path))
    assert len(manifest["members"]) == 1
    assert manifest["members"][0]["role"] == "master"


@pytest.mark.asyncio
async def test_unknown_recipe_maps_to_tool_error(db_session, tmp_path):
    _write_icon(tmp_path / "master.png")
    async with db_session() as session:
        master = await _media(session, tmp_path / "master.png")
        master_id = master.id

    with pytest.raises(EvaluatorError) as excinfo:
        await CreatePackageEvaluator()(_request(
            members=[master_id],
            inputs={"input:master": master_id},
            definition={
                "title": "Nope",
                "description": "",
                "recipe": "no-such-recipe",
                "params": {},
                "input_roles": {"master": "dynamic"},
            },
        ))

    assert excinfo.value.category == TOOL_ERROR
    assert "no-such-recipe" in str(excinfo.value)


@pytest.mark.asyncio
async def test_empty_members_is_a_tool_error():
    with pytest.raises(EvaluatorError) as excinfo:
        await CreatePackageEvaluator()(_request(
            members=[],
            definition={
                "title": "",
                "description": "",
                "recipe": None,
                "params": {},
                "input_roles": {},
            },
        ))
    assert excinfo.value.category == TOOL_ERROR


@pytest.mark.asyncio
async def test_dry_run_registry_fakes_the_package(tmp_path):
    reg = build_dry_run_registry(tmp_path / "dryrun")
    evaluator = reg.resolve("create_package")
    result = await evaluator(_request(
        members=[7, 8],
        inputs={"input:master": 7},
        definition={
            "title": "d",
            "description": "",
            "recipe": "tiles",
            "params": {},
            "input_roles": {"master": "dynamic"},
        },
    ))
    assert isinstance(result.value, int)
    assert result.media_ids == [result.value]
