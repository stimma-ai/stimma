"""What a file the agent makes in code is recorded as made from.

Each output follows its own data: a batch of tool results cropped and saved one
by one lists one source each, whatever order the code works in. One source reads
as an edit of it; several read as a new thing made of them.
"""
import json

import pytest
from PIL import Image
from sqlalchemy import select

from agent.v2.tools.run_code import run_code
from database import MediaItem, MediaLineage
from tests.helpers.media import create_media_item, generate_test_image

from .test_run_code_v2 import _patch_mock_registry

pytestmark = pytest.mark.asyncio

PHOTOS = 4


@pytest.fixture
async def studio(session, test_chat, tmp_path, monkeypatch):
    """A chat workspace, PHOTOS library photos, and a mock tool that turns photo
    N into its own library result (as a real tool does)."""
    workspace = tmp_path / "workspace"
    output_dir = tmp_path / "output"
    library_dir = tmp_path / "library"
    for d in (workspace, output_dir, library_dir):
        d.mkdir()

    photos: list[int] = []
    results: dict[int, dict] = {}
    for i in range(PHOTOS):
        photo_path = library_dir / f"photo_{i}.png"
        photo = await create_media_item(session, file_path=photo_path, width=40, height=40,
                                        file_hash=generate_test_image(photo_path, 40, 40, color=(10 * i, 0, 0)))
        result_path = library_dir / f"result_{i}.png"
        result_hash = generate_test_image(result_path, 40, 40, color=(0, 40 + 20 * i, 200))
        result = await create_media_item(session, file_path=result_path, width=40, height=40, file_hash=result_hash)
        result.generation_metadata = json.dumps({
            "task_type": "image-to-image", "tool_id": "mock:gen", "prompt": "cut out the subject",
            "source_inputs": [{"media_id": photo.id, "role": "input_image"}],
            "lineage_trace": [{"media_id": photo.id, "task_type": None}],
        })
        photos.append(photo.id)
        results[photo.id] = {"media_id": result.id, "path": str(result_path)}
    await session.commit()

    async def _fake_execute_call_tool(*, tool_id, parameters=None, **kwargs):
        params = parameters or {}
        made = results[params["input_images"][0]]
        return {**made, "width": 40, "height": 40, "seed": 1, "tool_id": tool_id, "tool_name": "Mock Tool",
                "task_type": "image-to-image", "parameters": params,
                "input_media_ids": list(params["input_images"]), "duration_ms": 1}

    async def _noop_validate(*args, **kwargs):
        return []

    monkeypatch.setattr("agent.v2.code_runtime.execute_call_tool", _fake_execute_call_tool)
    monkeypatch.setattr("agent.v2.tools.library._get_default_folder", lambda _=None: str(output_dir))
    monkeypatch.setattr("agent.v2.code_lint.validate_hardcoded_refs", _noop_validate)
    _patch_mock_registry(monkeypatch, task_types=("image-to-image",))
    test_chat.agent_tool_config = json.dumps({"allowed_tools": ["mock:gen"]})
    await session.commit()

    async def run(code: str) -> str:
        return await run_code(code=code, session=session, chat_id=test_chat.id, workspace_dir=workspace)

    return {"run": run, "photos": photos, "results": [results[p]["media_id"] for p in photos],
            "workspace": workspace, "session": session}


async def _sources(session, media_id: int) -> list[int]:
    rows = (await session.execute(select(MediaLineage).where(MediaLineage.media_id == media_id)
                                  .order_by(MediaLineage.source_order))).scalars().all()
    return [r.source_media_id for r in rows]


async def _meta(session, media_id: int) -> dict:
    return json.loads((await session.get(MediaItem, media_id)).generation_metadata)


async def _saved_as(session, name: str) -> int:
    rows = (await session.execute(select(MediaItem.id).where(MediaItem.file_path.like(f"%{name}"))
                                  .order_by(MediaItem.id.desc()))).scalars().all()
    assert rows, f"{name} was not saved"
    return rows[0]


def _printed_json(result: str):
    return json.loads(result.split("\n\n<system-reminder>", 1)[0].strip().splitlines()[-1])


async def test_each_file_of_a_batch_lists_only_its_own_source(studio):
    """The reported case: a tool result per photo, cropped in code and shown.
    Every output used to list every result of the run."""
    await studio["run"](
        "from stimma.tools.image_to_image import gen\n"
        f"for i, photo in enumerate({studio['photos']}):\n"
        "    r = await gen(prompt='cut out the subject', input_images=[photo])\n"
        "    r.open().crop((4, 4, 30, 30)).save(f'cut_{i}.png')\n"
        "    stimma.show(f'cut_{i}.png', role='final')\n"
    )
    session = studio["session"]
    for i, (photo, result) in enumerate(zip(studio["photos"], studio["results"])):
        media_id = await _saved_as(session, f"cut_{i}.png")
        assert await _sources(session, media_id) == [result]
        meta = await _meta(session, media_id)
        assert meta["task_type"] == "agent_edit"
        assert [(s["media_id"], s["role"]) for s in meta["source_inputs"]] == [(result, "source_image")]
        # One line of history: the photo, then the tool's result, then this edit.
        assert [e["media_id"] for e in meta["lineage_trace"]] == [photo, result]


async def test_load_everything_then_save_everything_keeps_each_source(studio):
    """Order of work is not evidence: results made, opened and turned into
    arrays up front, then written one by one."""
    result = await studio["run"](
        "from stimma.tools.image_to_image import gen\n"
        f"results = [await gen(prompt='cut', input_images=[p]) for p in {studio['photos']}]\n"
        "arrays = [np.asarray(Image.open(r.path)) for r in results]\n"
        "saved = []\n"
        "for i, a in enumerate(arrays):\n"
        "    mask = a[..., 2] > 100\n"
        "    out = np.where(mask[..., None], a, 0).astype(np.uint8)[2:20, 2:20]\n"
        "    Image.fromarray(out).save(f'cut_{i}.png')\n"
        "for i in range(len(arrays)):\n"
        "    saved.append((await stimma.library.save(f'cut_{i}.png'))['media_id'])\n"
        "print(json.dumps(saved))\n"
    )
    saved = _printed_json(result)
    assert [await _sources(studio["session"], m) for m in saved] == [[r] for r in studio["results"]]


async def test_several_sources_are_a_new_thing_made_of_them(studio):
    a, b = studio["results"][:2]
    result = await studio["run"](
        f"a, b = Image.open((await stimma.library.get({a})).path), Image.open((await stimma.library.get({b})).path)\n"
        "sheet = Image.new('RGB', (80, 40))\n"
        "sheet.paste(a, (0, 0)); sheet.paste(b, (40, 0))\n"
        "sheet.save('sheet.png')\n"
        "plain = await stimma.library.save('sheet.png')\n"
        "sheet.paste(a, (1, 0)); sheet.save('sheet2.png')\n"
        f"based = await stimma.library.save('sheet2.png', based_on={b})\n"
        "print(json.dumps([plain['media_id'], based['media_id']]))\n"
    )
    session = studio["session"]
    plain, based = _printed_json(result)
    assert await _sources(session, plain) == [a, b]
    meta = await _meta(session, plain)
    assert meta["task_type"] == "agent_compose"
    assert [(s["media_id"], s["role"]) for s in meta["source_inputs"]] == [(a, "image"), (b, "image")]
    # Each input keeps its own history; none of it is this file's.
    assert meta["lineage_trace"] == []
    assert meta.get("tool_id") is None

    # Named as a changed version of b: an edit of b, with a as another input.
    assert await _sources(session, based) == [b, a]
    meta = await _meta(session, based)
    assert meta["task_type"] == "agent_edit"
    assert [(s["media_id"], s["role"]) for s in meta["source_inputs"]] == [(b, "source_image"), (a, "image")]
    assert meta["lineage_trace"][-1]["media_id"] == b


async def test_a_file_made_from_nothing_has_no_sources_and_no_note(studio):
    result = await studio["run"](
        "Image.new('RGB', (20, 20), 'navy').save('swatch.png')\n"
        "print(json.dumps((await stimma.library.save('swatch.png'))['media_id']))\n"
    )
    assert "[sources]" not in result
    media_id = _printed_json(result)
    assert await _sources(studio["session"], media_id) == []
    assert (await _meta(studio["session"], media_id))["task_type"] == "code"


async def test_a_file_whose_sources_were_lost_says_so_on_the_runs_output(studio):
    """Raw bytes carry no tag. The code is told, and can declare the source."""
    photo = studio["results"][0]
    result = await studio["run"](
        f"im = Image.open((await stimma.library.get({photo})).path)\n"
        "Image.frombytes(im.mode, im.size, im.tobytes()).save('raw.png')\n"
        "first = await stimma.library.save('raw.png')\n"
        "Image.frombytes(im.mode, im.size, im.tobytes()).rotate(90).save('raw2.png')\n"
        f"await stimma.record_sources('raw2.png', [{photo}])\n"
        "second = await stimma.library.save('raw2.png')\n"
        "print(json.dumps([first['media_id'], second['media_id']]))\n"
    )
    assert "[sources] raw.png is saved without a record" in result
    assert "raw2.png is saved" not in result
    first, second = _printed_json(result)
    assert await _sources(studio["session"], first) == []
    assert await _sources(studio["session"], second) == [photo]


async def test_showing_an_untouched_result_file_shows_that_library_item(studio):
    """A path whose bytes are a library item is that item, not a disconnected copy."""
    photo = studio["photos"][0]
    session = studio["session"]
    before = len((await session.execute(select(MediaItem.id))).scalars().all())
    await studio["run"](
        "from stimma.tools.image_to_image import gen\n"
        f"r = await gen(prompt='cut', input_images=[{photo}])\n"
        "stimma.show(str(r.path), role='final')\n"
    )
    assert len((await session.execute(select(MediaItem.id))).scalars().all()) == before


async def test_a_made_file_used_as_a_tool_input_keeps_its_history(studio):
    """The implicit import of a workspace file must not cut the chain."""
    from agent.v2.tools.library import resolve_or_import_input_file

    result = studio["results"][0]
    await studio["run"](
        f"Image.open((await stimma.library.get({result})).path).resize((20, 20)).save('small.png')\n"
    )
    session = studio["session"]
    imported = await resolve_or_import_input_file(session, str(studio["workspace"] / "small.png"), studio["workspace"])
    assert await _sources(session, imported) == [result]
    assert (await _meta(session, imported))["task_type"] == "agent_edit"

    # A file with no history is still a plain import.
    Image.new("RGB", (8, 8), "white").save(studio["workspace"] / "blank.png")
    plain = await resolve_or_import_input_file(session, str(studio["workspace"] / "blank.png"), studio["workspace"])
    assert (await _meta(session, plain))["task_type"] == "imported"
