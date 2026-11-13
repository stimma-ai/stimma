"""Direct with a Detail level: the prompt is filled as Direct fills it (lists and saved
wildcards drawn, slots as their words, comment lines and [exact text] kept for the
improver), then improved per image like Fluent's fill, with every drawn value kept
exactly. Yours sends it as filled, Raw sends it untouched, and an improver that fails or
changes a drawn value sends it as filled: never an error."""

import random
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import prompt_pipeline as pp
import routes.generation as gen

ADDED = ", on a quiet street at dusk"
WILDCARDS = [{"name": "animal", "values": ["a corgi", "a tabby cat"]}]
PROMPT = "a <young woman> in a {red|blue} coat walking {{animal}}\n# keep it candid"


class _Session:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def tool(monkeypatch):
    """A prose image model, no LoRAs, one saved wildcard, and an improver that adds a clause
    and keeps the marks it was given; returns what the improver was asked."""
    import routes.prompt_enhancement as pe

    monkeypatch.setattr(gen, "prompt_enhance_context", lambda *a, **k: {
        "model": "m", "model_vendor": None, "effective_task": "text-to-image", "schema_props": {},
        "mode": "prose", "program_supported": True, "enhance": {}})
    monkeypatch.setattr(gen, "get_current_profile", lambda: "p")
    monkeypatch.setattr(gen, "get_database_registry",
                        lambda: SimpleNamespace(get_database=lambda p: SimpleNamespace(async_session_maker=_Session)))
    monkeypatch.setattr("prompt_pipeline._profile_wildcards_and_segments", lambda profile_id: (WILDCARDS, []))

    async def no_context(tool_id, parameters, profile_id=None):
        return []

    async def fingerprint(project_id):
        return "fake-model"

    monkeypatch.setattr("lora_notes.lora_context_for", no_context)
    monkeypatch.setattr("prompt_programs.program.model_fingerprint", fingerprint)
    asked = []

    async def improve(request, session):
        asked.append(request)
        body = "\n".join(line for line in request.prompt.split("\n") if not line.startswith("#"))
        return pe.ImprovePromptResponse(improved_prompt=body + ADDED)

    monkeypatch.setattr(pe, "improve_prompt", improve)
    return asked


async def _submit(prompt=PROMPT, *, level="fill", raw=False, forever=False, **extra):
    auto = {"enabled": level != "off", **({"level": level} if level != "off" else {})}
    options = {"direct": True, "autoImprove": auto, **({"raw": True} if raw else {}), **extra}
    return await gen._apply_generation_prompt_pipeline(
        {"prompt": prompt, "seed": 1}, tool_id="t", task_type="text-to-image", prompt_options=options,
        prompt_preload=None, generator_instance_id="gen-1" if forever else None, forever=forever)


def _drawn(text):
    color = "red" if "red coat" in text else "blue"
    animal = "a corgi" if "a corgi" in text else "a tabby cat"
    return color, animal


# --------------------------------------------------------------------------- the fill

def test_the_fill_marks_drawn_values_and_unwraps_slots():
    random.seed(3)
    text, spans = pp.draw_marked(PROMPT, WILDCARDS, [])
    color, animal = _drawn(text)
    assert text == f"a young woman in a {color} coat walking {animal}\n# keep it candid"
    assert [text[a:b] for a, b in spans] == [color, animal]


def test_values_drawn_in_comments_or_exact_text_are_not_kept_values():
    text, spans = pp.draw_marked("a {red|red} hat\n# make it {dim|dim}\n[{big|big} sign]", [], [])
    assert text == "a red hat\n# make it dim\n[big sign]"
    assert [text[a:b] for a, b in spans] == ["red"]


def test_a_list_of_wildcards_is_one_drawn_value_and_segments_are_not_drawn():
    segments = [{"name": "style", "content": "shot on {film|film}"}]
    text, spans = pp.draw_marked("{{{animal}}|{{animal}}} by a door, {{style}}", WILDCARDS, segments)
    assert [text[a:b] for a, b in spans][0] in ("a corgi", "a tabby cat")
    assert [text[a:b] for a, b in spans][1:] == ["film"]
    assert "⟦" not in text and "⟧" not in text


# --------------------------------------------------------------------------- per image

async def test_direct_at_medium_is_improved_with_its_drawn_values_kept(tool):
    out = await _submit(level="fill")
    assert len(tool) == 1
    request = tool[0]
    assert request.level == "fill" and request.marked
    color, animal = _drawn(out["prompt"])
    assert request.prompt == f"a young woman in a ⟦{color}⟧ coat walking ⟦{animal}⟧\n# keep it candid"
    assert out["prompt"] == f"a young woman in a {color} coat walking {animal}{ADDED}"
    record = out["prompt_direct"]
    assert record["level"] == "fill" and record["sent"] == out["prompt"]
    assert record["filled"] == f"a young woman in a {color} coat walking {animal}\n# keep it candid"
    assert record["improve"]["improved"] == "true"
    assert "prompt_program" not in out


async def test_direct_at_high_asks_for_high(tool):
    out = await _submit(level="expand")
    assert tool[0].level == "expand" and out["prompt_direct"]["level"] == "expand"


async def test_yours_sends_the_filled_prompt_without_an_improve_call(tool):
    out = await _submit(level="off")
    assert tool == []
    color, animal = _drawn(out["prompt"])
    assert out["prompt"] == f"a young woman in a {color} coat walking {animal}"
    assert "prompt_direct" not in out


async def test_raw_is_never_improved(tool):
    out = await _submit(level="fill", raw=True)
    assert tool == [] and out["prompt"] == PROMPT and "prompt_direct" not in out


async def test_a_prompt_that_is_not_a_picture_is_sent_as_filled(tool, monkeypatch):
    monkeypatch.setattr(gen, "prompt_enhance_context", lambda *a, **k: {
        "model": "m", "model_vendor": None, "effective_task": "image-to-image", "schema_props": {},
        "mode": "edit", "program_supported": False, "enhance": {}})
    out = await _submit("remove the {red|red} car", level="expand")
    assert tool == [] and out["prompt"] == "remove the red car" and "prompt_direct" not in out


@pytest.mark.parametrize("failure", [
    HTTPException(status_code=502, detail={"code": "prompt_enhancement_failed", "message": "empty"}),
    RuntimeError("the chat model went away"),
])
async def test_an_improver_that_fails_sends_the_filled_prompt(tool, monkeypatch, failure):
    import routes.prompt_enhancement as pe

    async def broken(request, session):
        tool.append(request)
        raise failure
    monkeypatch.setattr(pe, "improve_prompt", broken)
    out = await _submit(level="fill")
    color, animal = _drawn(out["prompt"])
    assert out["prompt"] == f"a young woman in a {color} coat walking {animal}"
    assert out["prompt_direct"]["improve"]["improved"] == "fallback"


async def test_no_chat_model_sends_the_filled_prompt_quietly(tool, monkeypatch):
    import routes.prompt_enhancement as pe
    from llm_resolver import LLMNotConfiguredError

    async def unconfigured(request, session):
        raise LLMNotConfiguredError("no chat model")
    monkeypatch.setattr(pe, "improve_prompt", unconfigured)
    out = await _submit(level="expand")
    assert "⟦" not in out["prompt"] and out["prompt"].startswith("a young woman in a ")


async def test_a_changed_drawn_value_sends_the_filled_prompt(tool, monkeypatch):
    import routes.prompt_enhancement as pe

    async def recolor(request, session):
        tool.append(request)
        return pe.ImprovePromptResponse(
            improved_prompt=request.prompt.replace("⟦red⟧", "⟦green⟧").replace("⟦blue⟧", "⟦green⟧") + ADDED)
    monkeypatch.setattr(pe, "improve_prompt", recolor)
    out = await _submit(level="fill")
    assert len(tool) == 2  # one retry with the values named
    color, animal = _drawn(out["prompt"])
    assert out["prompt"] == f"a young woman in a {color} coat walking {animal}"
    improve = out["prompt_direct"]["improve"]
    assert improve["improved"] == "fallback" and "fixed value" in improve["reason"]


async def test_a_classic_warm_prompt_is_never_used_for_direct(tool, monkeypatch):
    import generation_queue

    served = {"originalPrompt": PROMPT, "improvedPrompt": "classic"}
    monkeypatch.setattr(generation_queue, "get_generation_queue",
                        lambda: SimpleNamespace(consume_prompt_warm_pool=lambda gid: served))
    out = await gen._apply_generation_prompt_pipeline(
        {"prompt": PROMPT, "seed": 1}, tool_id="t", task_type="text-to-image",
        prompt_options={"direct": True, "autoImprove": {"enabled": True, "level": "fill"}},
        prompt_preload=None, generator_instance_id="gen-1")
    assert out["prompt"] != "classic" and out["prompt"].endswith(ADDED)


# --------------------------------------------------------------------------- generate forever

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


async def test_generate_forever_sends_a_pooled_fill_improved_ahead(tool, forever_queue, monkeypatch):
    import routes.prompt_enhancement as pe

    cold = await _submit(forever=True)
    assert cold["prompt"].endswith(ADDED) and cold["prompt_direct"]["improve"]["improved"] == "true"
    await _settle(forever_queue)
    pool = forever_queue._prompt_warm_ready["gen-1"]
    assert len(pool) == 2 and all(h["sent"].endswith(ADDED) and h["improve"]["improved"] == "true" for h in pool)
    assert all(r.marked and r.level == "fill" for r in tool)
    pooled = dict(pool[0])

    real_improve = pe.improve_prompt

    async def no_call(request, session):
        raise AssertionError("an improve call at submit")
    monkeypatch.setattr(pe, "improve_prompt", no_call)
    hot = await _submit(forever=True)
    monkeypatch.setattr(pe, "improve_prompt", real_improve)

    assert hot["prompt"] == pooled["sent"] == hot["prompt_direct"]["sent"]
    assert hot["prompt_direct"]["filled"] == pooled["filled"]
    await _settle(forever_queue)


async def test_generate_forever_discards_the_pool_when_the_level_or_prompt_changes(tool, forever_queue):
    await _submit(forever=True)
    await _settle(forever_queue)
    signature = forever_queue._prompt_warm_intent["gen-1"]["signature"]
    asked = len(tool)

    out = await _submit(forever=True, level="expand")
    assert out["prompt_direct"]["level"] == "expand" and tool[asked].level == "expand"
    await _settle(forever_queue)
    assert forever_queue._prompt_warm_intent["gen-1"]["signature"] != signature
    assert all(r.level == "expand" for r in tool[asked:])

    signature = forever_queue._prompt_warm_intent["gen-1"]["signature"]
    await _submit("a {green|green} kite", forever=True, level="expand")
    await _settle(forever_queue)
    assert forever_queue._prompt_warm_intent["gen-1"]["signature"] != signature
    assert all(h["filled"] == "a green kite" for h in forever_queue._prompt_warm_ready["gen-1"])


async def test_generate_forever_at_yours_keeps_no_pool(tool, forever_queue):
    await _submit(forever=True, level="off")
    assert tool == [] and "gen-1" not in forever_queue._prompt_warm_intent
