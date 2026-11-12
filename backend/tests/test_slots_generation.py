"""A Fluent generation on the slot path: the prompt's slots read once (a fake model), drawn
per image with the chooser's choices, then improved per image at the Detail level with every
drawn value kept exactly; what each image was made from is stored with it."""

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import routes.generation as gen
from prompt_programs import slots
from prompt_programs.choices import UnknownChoiceError

from test_slots_build import PORCH_PROMPT, PORCH_READING
from test_slots_reader import FakeModel, _reply, _use, profile  # noqa: F401 (profile is a fixture)

MAN = "elderly_african_man"
ADDED = ", in warm late-afternoon light"


class _Session:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def tool(monkeypatch, profile):  # noqa: F811
    """A prose image model, no LoRAs, no saved lists, the judge not waited for, and an improver
    that adds a clause and keeps the marks it was given; returns what the improver was asked."""
    import prompt_programs.fix as fix
    import routes.prompt_enhancement as pe

    monkeypatch.setattr(gen, "prompt_enhance_context", lambda *a, **k: {
        "model": "m", "model_vendor": None, "effective_task": "text-to-image", "schema_props": {},
        "mode": "prose", "program_supported": True, "enhance": {}})
    monkeypatch.setattr(gen, "get_current_profile", lambda: profile)
    monkeypatch.setattr(gen, "get_database_registry",
                        lambda: SimpleNamespace(get_database=lambda p: SimpleNamespace(async_session_maker=_Session)))
    monkeypatch.setattr("prompt_pipeline._profile_wildcards_and_segments", lambda profile_id: ([], []))

    async def no_context(tool_id, parameters, profile_id=None):
        return []

    async def no_judge(entry, project_id=None):
        return None

    monkeypatch.setattr("lora_notes.lora_context_for", no_context)
    monkeypatch.setattr(fix, "await_judge", no_judge)
    asked = []

    async def improve(request, session):
        asked.append(request)
        body = "\n".join(line for line in request.prompt.split("\n") if not line.startswith("#"))
        return pe.ImprovePromptResponse(improved_prompt=body + ADDED)

    monkeypatch.setattr(pe, "improve_prompt", improve)
    return asked


async def _submit(prompt=PORCH_PROMPT, *, level="expand", choices=None, **program):
    auto = {"enabled": level != "off", **({"level": level} if level != "off" else {})}
    options = {"autoImprove": auto, "program": {"enabled": True, "choices": choices or {}, **program}}
    return await gen._apply_generation_prompt_pipeline(
        {"prompt": prompt, "seed": 1}, tool_id="t", task_type="text-to-image", prompt_options=options,
        prompt_preload=None)


async def test_each_image_draws_its_slots_then_is_improved_with_its_values_kept(tool, monkeypatch):
    model = _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    outs = [await _submit() for _ in range(4)]
    assert len(model.asked) == 1            # read once, drawn four times
    assert len(tool) == 4                   # one improve call per image
    assert len({o["prompt"] for o in outs}) == 4
    for out, request in zip(outs, tool):
        record = out["prompt_program"]
        drawn = {d["id"]: d["value"] for d in record["draws"]}
        sent = out["prompt"]
        # the improver saw the comment line and every drawn value marked; the tool never sees the comment
        assert request.prompt.startswith("# she is his granddaughter, visiting\n") and request.level == "expand"
        assert request.marked and f"⟦{drawn[MAN + '.age']}⟧" in request.prompt and f"⟦{drawn['pet']}⟧" in request.prompt
        assert "#" not in sent and "⟦" not in sent and sent.endswith(ADDED)
        for cid in (MAN + ".age", MAN + ".descent", "pet", "list1"):
            assert drawn[cid] in sent
        # the record: draws (an outfit keeps its template), choices, the filled and sent prompts, the outcome
        assert record["key"] and record["level"] == "expand" and record["choices"] == {}
        assert record["sent"] == sent and record["filled"].startswith("# she is his granddaughter")
        assert record["improve"]["improved"] == "true" and record["improve"]["target"]
        assert all(record["filled"][a:b].lower() in str(drawn[c]).lower() or c.endswith(".outfit")
                   for a, b, c in record["spans"])
        outfit = next(d for d in record["draws"] if d["id"] == MAN + ".outfit")
        assert outfit.get("template") and "{" in outfit["template"]
        json.dumps(record)   # stored as JSON with the image


async def test_choices_hold_and_a_slot_left_out_takes_its_lead(tool, monkeypatch):
    _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    choices = {MAN + ".age": {"values": ["74-year-old"]}, "pet": {"off": True}, "list1": {"values": ["autumn"]}}
    for _ in range(3):
        out = await _submit(choices=choices)
        record = out["prompt_program"]
        assert "74-year-old" in out["prompt"] and "autumn evening" in out["prompt"]
        assert "with his" not in out["prompt"] and "pet" not in {d["id"] for d in record["draws"]}
        assert record["choices"] == choices


async def test_yours_sends_the_filled_prompt_without_an_improve_call(tool, monkeypatch):
    _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    out = await _submit(level="off")
    record = out["prompt_program"]
    assert tool == [] and record["improve"]["improved"] == "skipped" and record["level"] == "off"
    assert out["prompt"] == record["filled"].split("\n", 1)[1]   # the comment line stripped, nothing added


async def test_a_prompt_with_nothing_to_vary_goes_straight_to_the_improver(tool, monkeypatch):
    model = _use(monkeypatch, FakeModel())
    out = await _submit("# keep it quiet\na lighthouse at dusk", level="fill")
    assert model.asked == [] and "prompt_program" not in out
    assert len(tool) == 1 and tool[0].level == "fill" and tool[0].prompt.startswith("# keep it quiet")
    assert out["prompt"] == "a lighthouse at dusk" + ADDED


async def test_agent_keep_choices_are_choices_of_values(tool, monkeypatch):
    _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    out = await _submit(keep_choices={"Pet": "grey parrot"})
    assert {d["id"]: d["value"] for d in out["prompt_program"]["draws"]}["pet"] == "grey parrot"
    with pytest.raises(UnknownChoiceError):
        await _submit(keep_choices={"hat": "bowler"})


async def test_slots_that_cant_be_read_fail_the_run_with_a_424(tool, monkeypatch):
    _use(monkeypatch, FakeModel("not json", "still not json"))
    with pytest.raises(HTTPException) as e:
        await _submit()
    assert e.value.status_code == 424 and e.value.detail["code"] == "reader_failed"
    assert tool == []


async def test_a_prompt_too_long_is_refused(tool, monkeypatch):
    _use(monkeypatch, FakeModel())
    with pytest.raises(HTTPException) as e:
        await _submit("a <cat> " + "x" * 9000)
    assert e.value.status_code == 422 and e.value.detail["code"] == "prompt_too_long"


async def test_the_slot_reader_runs_once_for_a_batch(tool, monkeypatch):
    import asyncio
    model = _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    monkeypatch.setattr(slots, "_in_flight", {})
    outs = await asyncio.gather(*[_submit() for _ in range(4)])
    assert len(model.asked) == 1 and len({o["prompt_program"]["key"] for o in outs}) == 1


async def test_draws_are_their_own_seed_never_the_images(tool, monkeypatch):
    _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    fresh = [(await _submit())["prompt_program"]["draw_seed"] for _ in range(6)]
    assert len(set(fresh)) > 1
    a, b = (await _submit(draw_seed=7))["prompt_program"], (await _submit(draw_seed=7))["prompt_program"]
    assert a["draw_seed"] == b["draw_seed"] == 7 and a["draws"] == b["draws"]
