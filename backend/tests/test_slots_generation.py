"""A Fluent generation on the slot path: the prompt's slots read and their pools written in the
background (a fake model and a fake writer), each image drawing a variant per slot with the
chooser's choices, judged, then improved per image at the Detail level with every drawn value
kept exactly; what each image was made from is stored with it. A submit never waits on the
slot reader, narrowing or pool writing."""

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import routes.generation as gen
from prompt_programs import slots
from prompt_programs import variant_pools as P
from prompt_programs.choices import UnknownChoiceError

from test_prompt_program_variants import FakeWriter
from test_slots_fill import PORCH_PROMPT, PORCH_READING
from test_slots_reader import FakeModel, Hang, _reply, _use, profile, ready  # noqa: F401 (profile is a fixture)

MAN = "elderly_african_man"
ADDED = ", in warm late-afternoon light"
AS_WRITTEN = ("An elderly African man reading on a porch with his pet, summer evening",
              "An elderly African man reading on a porch with his pet, autumn evening")


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


async def _submit(prompt=PORCH_PROMPT, *, level="expand", choices=None, forever=False, **program):
    auto = {"enabled": level != "off", **({"level": level} if level != "off" else {})}
    options = {"autoImprove": auto, "program": {"enabled": True, "choices": choices or {}, **program}}
    return await gen._apply_generation_prompt_pipeline(
        {"prompt": prompt, "seed": 1}, tool_id="t", task_type="text-to-image", prompt_options=options,
        prompt_preload=None, generator_instance_id="gen-1" if forever else None, forever=forever)


async def _read(monkeypatch, profile, prompt=PORCH_PROMPT, *replies):
    model = _use(monkeypatch, FakeModel(*(replies or [_reply(PORCH_READING)])))
    await ready(prompt, profile)
    return model


class FakeJudge:
    """The judge as llm_judge gives it: every pick fits; counts what it was asked."""
    version = "fake-judge"
    reroll_all = True

    def __init__(self):
        self.asked = []

    def p_wrong(self, items):
        self.asked.append(items)
        return [0.0] * len(items)


class HangWriter(FakeWriter):
    """A pool writer that never answers until let go."""

    def __init__(self):
        import asyncio
        super().__init__()
        self.go = asyncio.Event()

    async def __call__(self, messages, project_id, max_tokens, temperature=0.8):
        await self.go.wait()
        return await super().__call__(messages, project_id, max_tokens, temperature)


async def test_a_submit_waits_on_nothing_but_the_judge_and_improve(tool, monkeypatch, profile):
    """Reader, narrowing and pool writing would hang if awaited: the submit still finishes,
    its unread slots as their words, judged and improved; once the readings land the slots
    still stand as their words while their pools are written, and draw variants after."""
    import asyncio
    from prompt_programs import llm_judge

    model = _use(monkeypatch, Hang(_reply(PORCH_READING)))
    writer = HangWriter()
    monkeypatch.setattr(P, "ASK", writer)
    judge = FakeJudge()
    monkeypatch.setenv("STIMMA_FLUENT_FIX_MODEL", "default")
    monkeypatch.setattr(llm_judge, "current", lambda project_id=None: judge)
    out = await asyncio.wait_for(_submit(), 3.0)
    assert model.calls == 3 and model.asked == []   # its reading started, never waited for
    assert len(tool) == 1                            # the one model call in line: Improve
    record = out["prompt_program"]
    assert record["filled"].split("\n")[1] in AS_WRITTEN
    assert {d["id"] for d in record["draws"]} == {"list1"} and judge.asked and record["fix"]["judge"] == "fake-judge"

    model.go.set()
    await slots.idle()
    written = (await asyncio.wait_for(_submit(), 3.0))["prompt_program"]
    assert written["filled"].split("\n")[1] in AS_WRITTEN and written["more_coming"] == [MAN, "pet"]
    assert all(d["source"] == "words" for d in written["draws"] if d["id"] != "list1")

    writer.go.set()
    await P.writer_for(profile).drain()
    later = (await asyncio.wait_for(_submit(), 3.0))["prompt_program"]
    assert all(d["source"] == "variant" for d in later["draws"] if d["id"] != "list1") and "more_coming" not in later
    assert len(tool) == 3


async def test_each_image_draws_its_slots_then_is_improved_with_its_values_kept(tool, monkeypatch, profile):
    from prompt_programs.fill import tidy_text
    model = await _read(monkeypatch, profile)
    outs = [await _submit() for _ in range(4)]
    assert len(model.asked) == 3            # each part read once, drawn four times
    assert len(tool) == 4                   # one improve call per image
    assert len({o["prompt"] for o in outs}) == 4
    for out, request in zip(outs, tool):
        record = out["prompt_program"]
        drawn = {d["id"]: d["value"] for d in record["draws"]}
        sent = out["prompt"]
        # the improver saw the comment line and every drawn value marked; the tool never sees the comment
        assert request.prompt.startswith("# she is his granddaughter, visiting\n") and request.level == "expand"
        assert request.marked and f"⟦{drawn['pet']}⟧" in request.prompt and f"⟦{drawn['list1']}⟧" in request.prompt
        assert "#" not in sent and "⟦" not in sent and sent.endswith(ADDED)
        for cid in (MAN, "pet", "list1"):
            assert drawn[cid] in sent
        # the record: draws, choices, the filled and sent prompts, the outcome
        assert record["key"] and record["level"] == "expand" and record["choices"] == {}
        assert record["sent"] == sent and record["filled"].startswith("# she is his granddaughter")
        assert record["improve"]["improved"] == "true" and record["improve"]["target"]
        assert all(record["filled"][a:b].lower() in (str(drawn[c]).lower(), tidy_text([str(drawn[c])]).lower())
                   for a, b, c in record["spans"])
        assert record["draw_revision"]["engine"] == "variants-1"
        json.dumps(record)   # stored as JSON with the image
    # each shipped draw counted: four images took four different pets
    pets = [{d["id"]: d["value"] for d in o["prompt_program"]["draws"]}["pet"] for o in outs]
    assert len(set(pets)) == 4


async def test_choices_hold_and_a_slot_left_out_takes_its_lead(tool, monkeypatch, profile):
    await _read(monkeypatch, profile)
    choices = {MAN: {"values": ["stooped elderly African man in a cardigan"]}, "pet": {"off": True},
               "list1": {"values": ["autumn"]}}
    for _ in range(3):
        out = await _submit(choices=choices)
        record = out["prompt_program"]
        assert "stooped elderly African man in a cardigan" in out["prompt"] and "autumn evening" in out["prompt"]
        assert "with his" not in out["prompt"] and "pet" not in {d["id"] for d in record["draws"]}
        assert record["choices"] == choices


async def test_yours_sends_the_filled_prompt_without_an_improve_call(tool, monkeypatch, profile):
    await _read(monkeypatch, profile)
    out = await _submit(level="off")
    record = out["prompt_program"]
    assert tool == [] and record["improve"]["improved"] == "skipped" and record["level"] == "off"
    assert out["prompt"] == record["filled"].split("\n", 1)[1]   # the comment line stripped, nothing added


def _failing(failure):
    async def broken(request, session):
        raise failure
    return broken


def _unconfigured():
    from llm_resolver import LLMNotConfiguredError
    return LLMNotConfiguredError("no chat model")


@pytest.mark.parametrize("failure", [
    HTTPException(status_code=502, detail={"code": "prompt_enhancement_failed", "message": "empty"}),
    HTTPException(status_code=503, detail={"code": "llm_unavailable", "message": "unreachable"}),
    "unconfigured",
])
async def test_an_improver_that_fails_sends_the_filled_prompt(tool, monkeypatch, profile, failure):
    import routes.prompt_enhancement as pe

    await _read(monkeypatch, profile)
    monkeypatch.setattr(pe, "improve_prompt", _failing(_unconfigured() if failure == "unconfigured" else failure))
    out = await _submit(level="expand")
    record = out["prompt_program"]
    assert out["prompt"] == record["sent"] == record["filled"].split("\n", 1)[1]
    assert record["improve"]["improved"] == "fallback" and record["improve"]["reason"]


async def test_a_prompt_with_nothing_to_vary_goes_straight_to_the_improver(tool, monkeypatch):
    model = _use(monkeypatch, FakeModel())
    out = await _submit("# keep it quiet\na lighthouse at dusk", level="fill")
    assert model.asked == [] and "prompt_program" not in out
    assert len(tool) == 1 and tool[0].level == "fill" and tool[0].prompt.startswith("# keep it quiet")
    assert out["prompt"] == "a lighthouse at dusk" + ADDED


async def test_agent_keep_choices_are_choices_of_values(tool, monkeypatch, profile):
    await _read(monkeypatch, profile)
    out = await _submit(keep_choices={"Pet": "gray parrot", "Season": "summer"})
    drawn = {d["id"]: d["value"] for d in out["prompt_program"]["draws"]}
    assert drawn["pet"] == "gray parrot" and drawn["list1"] == "summer"
    with pytest.raises(UnknownChoiceError):
        await _submit(keep_choices={"hat": "bowler"})


async def test_slots_that_cant_be_read_still_run_as_written(tool, monkeypatch, profile):
    await _read(monkeypatch, profile, PORCH_PROMPT, "not json")
    out = await _submit(level="off")
    assert out["prompt"] in AS_WRITTEN, out["prompt"]


async def test_a_prompt_too_long_is_refused(tool, monkeypatch):
    _use(monkeypatch, FakeModel())
    with pytest.raises(HTTPException) as e:
        await _submit("a <cat> " + "x" * 9000)
    assert e.value.status_code == 422 and e.value.detail["code"] == "prompt_too_long"


async def test_a_batch_reads_each_part_once(tool, monkeypatch):
    import asyncio
    model = _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    outs = await asyncio.gather(*[_submit() for _ in range(4)])
    await slots.idle()
    assert len(model.asked) == 3 and len({o["prompt_program"]["key"] for o in outs}) == 1


async def test_draws_are_their_own_seed_never_the_images(tool, monkeypatch, profile):
    await _read(monkeypatch, profile)
    fresh = [(await _submit())["prompt_program"]["draw_seed"] for _ in range(6)]
    assert len(set(fresh)) > 1
    a, b = (await _submit(draw_seed=7))["prompt_program"], (await _submit(draw_seed=7))["prompt_program"]
    # the user's list draws the same; a slot takes its least-used variant, and the first draw was counted
    season = [next(d["value"] for d in r["draws"] if d["id"] == "list1") for r in (a, b)]
    assert a["draw_seed"] == b["draw_seed"] == 7 and season[0] == season[1]


async def test_a_replay_draws_its_values_exactly(tool, monkeypatch, profile):
    await _read(monkeypatch, profile)
    first = (await _submit(level="off"))["prompt_program"]
    fixed = {d["id"]: d["value"] for d in first["draws"]}
    again = (await _submit(level="off", fixed=fixed))["prompt_program"]
    assert again["filled"] == first["filled"] and {d["source"] for d in again["draws"]} == {"fixed", "list"}


# --------------------------------------------------------------------------- generate forever improves ahead

@pytest.fixture
def forever_queue(monkeypatch):
    """A queue with "gen-1" registered for generate forever (two slots), its pool's
    improver writing through the test's fake database."""
    from generation_queue import GenerationQueue

    q = GenerationQueue()
    q._forever_mode_clients = {"backend-a": {"gen-1": 2}}
    monkeypatch.setattr(q, "_get_db", lambda profile_id=None: SimpleNamespace(async_session_maker=_Session))
    monkeypatch.setattr("generation_queue.get_generation_queue", lambda: q)
    return q


async def _settle(q, gid="gen-1"):
    import asyncio
    for _ in range(200):
        tasks = list(q._prompt_warm_tasks.get(gid, ()))
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)
    raise AssertionError("refill never settled")


async def test_generate_forever_sends_a_pooled_prompt_improved_ahead(tool, forever_queue, monkeypatch, profile):
    import routes.prompt_enhancement as pe

    await _read(monkeypatch, profile)
    cold = await _submit(forever=True)
    # the first image waits on its own improve (the pool's improves ahead may land meanwhile)
    assert tool and cold["prompt"].endswith(ADDED) and cold["prompt_program"]["improve"]["improved"] == "true"
    await _settle(forever_queue)
    pool = forever_queue._prompt_warm_ready["gen-1"]
    assert len(pool) == 2 and all(h["sent"].endswith(ADDED) and h["improve"]["improved"] == "true" for h in pool)
    pooled = dict(pool[0])

    # The improver may not be called for this submit: one that improved inline would fail.
    real_improve = pe.improve_prompt

    async def no_call(request, session):
        raise AssertionError("an improve call at submit")
    monkeypatch.setattr(pe, "improve_prompt", no_call)
    hot = await _submit(forever=True)
    monkeypatch.setattr(pe, "improve_prompt", real_improve)

    record = hot["prompt_program"]
    assert hot["prompt"] == pooled["sent"] == record["sent"]
    assert record["draw_seed"] == pooled["result"].seed and record["improve"] == pooled["improve"]
    drawn = {d["id"]: d["value"] for d in record["draws"]}
    for cid in (MAN, "pet", "list1"):
        assert drawn[cid] in hot["prompt"]
    await _settle(forever_queue)


async def test_generate_forever_keeps_draws_whose_improve_failed(tool, forever_queue, monkeypatch, profile):
    import routes.prompt_enhancement as pe

    await _read(monkeypatch, profile)

    async def broken(request, session):
        raise HTTPException(status_code=502, detail={"code": "prompt_enhancement_failed", "message": "empty"})
    monkeypatch.setattr(pe, "improve_prompt", broken)
    cold = await _submit(forever=True)
    assert cold["prompt_program"]["improve"]["improved"] == "fallback"
    await _settle(forever_queue)
    pool = forever_queue._prompt_warm_ready["gen-1"]
    assert len(pool) == 2 and all(h["improve"]["improved"] == "fallback" for h in pool)
    assert all(h["sent"] == h["result"].prompt.split("\n", 1)[1] for h in pool)
    pooled = dict(pool[0])

    # served as it is (the pooled draw itself), not improved again at submit
    hot = await _submit(forever=True)
    assert hot["prompt_program"]["draw_seed"] == pooled["result"].seed
    assert hot["prompt"] == pooled["sent"] and hot["prompt_program"]["improve"] == pooled["improve"]
    await _settle(forever_queue)


async def test_generate_forever_discards_the_pool_when_the_level_changes(tool, forever_queue, monkeypatch, profile):
    await _read(monkeypatch, profile)
    await _submit(forever=True)
    await _settle(forever_queue)
    old = {h["sent"] for h in forever_queue._prompt_warm_ready["gen-1"]}
    asked = len(tool)

    out = await _submit(forever=True, level="fill")
    assert out["prompt"] not in old and out["prompt_program"]["level"] == "fill"
    assert tool[asked].level == "fill"  # improved inline at the new level
    await _settle(forever_queue)
    pool = forever_queue._prompt_warm_ready["gen-1"]
    assert len(pool) == 2 and not {h["sent"] for h in pool} & old
    assert all(r.level == "fill" for r in tool[asked:])


async def test_generate_forever_discards_the_pool_when_the_image_model_changes(tool, forever_queue, monkeypatch, profile):
    await _read(monkeypatch, profile)
    await _submit(forever=True)
    await _settle(forever_queue)
    old = {h["sent"] for h in forever_queue._prompt_warm_ready["gen-1"]}
    signature = forever_queue._prompt_warm_intent["gen-1"]["signature"]
    asked = len(tool)

    monkeypatch.setattr(gen, "prompt_enhance_context", lambda *a, **k: {
        "model": "another image model", "model_vendor": None, "effective_task": "text-to-image",
        "schema_props": {}, "mode": "prose", "program_supported": True, "enhance": {}})
    out = await _submit(forever=True)
    assert forever_queue._prompt_warm_intent["gen-1"]["signature"] != signature
    assert out["prompt"] not in old and len(tool) > asked
    assert tool[asked].model == "another image model"
    await _settle(forever_queue)
    assert not {h["sent"] for h in forever_queue._prompt_warm_ready["gen-1"]} & old


async def test_the_improve_signature_covers_what_the_improved_text_depends_on(monkeypatch):
    import routes.prompt_enhancement as pe

    monkeypatch.setattr("prompt_pipeline._profile_wildcards_and_segments", lambda profile_id: ([], []))

    async def writer(project_id):
        return "writer-a"
    monkeypatch.setattr("prompt_programs.program.model_fingerprint", writer)
    base = dict(prompt_options={"autoImprove": {"enabled": True, "level": "expand"}, "program": {"enabled": True}},
                model="m", model_vendor=None, lora_context=[], width=1024, height=1024,
                profile_id="p", project_id=None, level="expand")

    async def sig(mode="prose", **changes):
        return await gen.improve_signature({**base, **changes}, mode)

    first = await sig()
    assert await sig() == first
    # the choices are in the draw's own signature, not this one
    assert await sig(prompt_options={**base["prompt_options"], "program": {"enabled": True, "choices": {"x": 1}}}) == first
    assert await sig(level="fill") != first
    assert await sig(model="m2") != first
    assert await sig(mode="keyword") != first
    assert await sig(lora_context=[{"name": "mara", "trigger_words": ["ohwx"], "notes": ""}]) != first
    assert await sig(width=768) != first
    assert await sig(prompt_options={**base["prompt_options"], "translate": {"enabled": True, "language": "de"}}) != first

    real_guide = pe.guide_template
    monkeypatch.setattr(pe, "guide_template", lambda mode, fill=False: real_guide(mode, fill) + " (edited)")
    assert await sig() != first
    monkeypatch.setattr(pe, "guide_template", real_guide)

    async def other_writer(project_id):
        return "writer-b"
    monkeypatch.setattr("prompt_programs.program.model_fingerprint", other_writer)
    assert await sig() != first
