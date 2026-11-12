"""How an agent's (and an MCP client's, a flow's) prompt reaches the image model.

Default: the person's Direct handling (syntax applied, no model). vary: the person's
prepared prompt, with keep_choices as pins and draw_seed as Same draws. These run the
real pipeline (routes.generation / prompt_pipeline / prompt_programs) with the chat
model stubbed.
"""

import pytest

import routes.generation as gen
from agent.v2 import prompt_handling as ph
from agent.v2.prompt_handling import PromptHandlingError, PromptRequest, prepare_prompt
from tests.test_slots_build import PORCH_PROMPT as PROMPT, PORCH_READING
from tests.test_slots_reader import FakeModel, _reply, _use, profile  # noqa: F401 (profile is a fixture)

SCHEMA = {"prompt": {"type": "string"}}


WILDCARDS = [{"name": "outfit", "values": ["a red raincoat"]}]
SEGMENTS = [{"name": "house style", "content": "soft window light"}]


@pytest.fixture
def lists(monkeypatch):
    monkeypatch.setattr("prompt_pipeline._profile_wildcards_and_segments", lambda profile_id: (WILDCARDS, SEGMENTS))


@pytest.fixture
def prose_model(monkeypatch, lists):
    """A plain prose model: no prompt format of its own, programs supported."""
    monkeypatch.setattr(gen, "prompt_enhance_context", lambda *a, **k: {
        "model": "m", "model_vendor": None, "effective_task": "text-to-image", "schema_props": SCHEMA,
        "mode": "prose", "program_supported": True, "enhance": {}})
    monkeypatch.setattr(gen, "native_prompt_format", lambda *a, **k: None)
    calls = []

    async def no_rewrite(*a, **k):
        calls.append((a, k))
        raise AssertionError("no rewrite expected")

    monkeypatch.setattr(gen, "enhance_tool_prompt", no_rewrite)
    return calls


async def _direct(prompt, enhance=False, **kw):
    out = await prepare_prompt({"prompt": prompt, "seed": 1}, tool_id="t", task_type="text-to-image",
                               request=PromptRequest(enhance=enhance, **kw), project_id=None)
    return out


class TestDirectByDefault:
    async def test_plain_prompt_is_byte_exact(self, prose_model):
        text = "  A lighthouse at dusk, oil on canvas.  "
        out = await _direct(text, enhance="auto")
        assert out.params["prompt"] == text
        assert out.params["prompt_metadata"] == {"original_prompt": text, "auto_improve_enabled": False}
        assert out.choices is None and out.draw_seed is None

    async def test_inline_list_picks_one(self, prose_model):
        for _ in range(10):
            out = await _direct("a {nun|nurse} in a garden")
            assert out.params["prompt"] in ("a nun in a garden", "a nurse in a garden")
            assert out.params["prompt_metadata"]["original_prompt"] == "a {nun|nurse} in a garden"

    async def test_saved_lists_and_segments_fill(self, prose_model):
        out = await _direct("a woman in {{outfit}}, {{House Style}}")
        assert out.params["prompt"] == "a woman in a red raincoat, soft window light"

    async def test_brackets_unwrap_and_notes_drop(self, prose_model):
        out = await _direct("[Shot on Portra 400] a harbour\n# keep it calm\nat noon")
        assert out.params["prompt"] == "Shot on Portra 400 a harbour\nat noon"

    async def test_unknown_name_stops_the_call(self, prose_model):
        with pytest.raises(PromptHandlingError) as e:
            await _direct("a woman in {{hairstyle}}")
        assert str(e.value) == ("{{hairstyle}} isn't one of your saved lists. Write its options as {a|b|c}, "
                                "or write it as <hairstyle> and pass vary=True for options to be found. Nothing was generated.")

    async def test_unknown_name_in_a_note_is_fine(self, prose_model):
        out = await _direct("a harbour\n# maybe {{weather}} later")
        assert out.params["prompt"] == "a harbour"

    async def test_json_prompt_untouched(self, prose_model):
        text = '{"scene": "a {red|blue} door", "layout": [1, 2]}'
        assert (await _direct(text)).params["prompt"] == text

    async def test_h3_untouched(self, prose_model, monkeypatch):
        monkeypatch.setattr(gen, "prompt_enhance_context", lambda *a, **k: {
            "model": "h3", "mode": "minimax-h3", "program_supported": False, "schema_props": {}, "enhance": {}})
        text = "Shot 1: [Picture 1] {{unknown}} walks in"
        assert (await _direct(text)).params["prompt"] == text

    async def test_keep_choices_needs_vary(self, prose_model):
        with pytest.raises(PromptHandlingError, match="only work with vary=True"):
            await _direct("a cat", keep_choices={"outfit": "x"})
        with pytest.raises(PromptHandlingError, match="only work with vary=True"):
            await _direct("a cat", draw_seed=4)

    async def test_format_models_still_rewrite_by_default(self, lists, monkeypatch):
        monkeypatch.setattr(gen, "prompt_enhance_context", lambda *a, **k: {
            "model": "q", "mode": "qwen-image-2.1", "program_supported": True, "schema_props": {}, "enhance": {}})
        monkeypatch.setattr(gen, "native_prompt_format", lambda *a, **k: "Qwen-Image-2.1")
        seen = {}

        async def rewrite(params, **kw):
            seen["params"] = params
            return {**params, "prompt": "REWRITTEN"}

        monkeypatch.setattr(gen, "enhance_tool_prompt", rewrite)
        out = await _direct("a cat", enhance="auto")
        assert out.params["prompt"] == "REWRITTEN" and "rewritten for Qwen-Image-2.1" in out.note
        assert out.params["prompt_metadata"] == {"original_prompt": "a cat", "auto_improve_enabled": True}
        # False sends your wording (with the syntax applied), no rewrite.
        seen.clear()
        out = await _direct("a {cat|cat}", enhance=False)
        assert out.params["prompt"] == "a cat" and not seen


class TestSameWhetherOrNotToolViewHasTheFeature:
    """The feature's switch is the app build (dev/canary today). Without vary, nothing an
    agent, MCP client or flow sends depends on it: no prepared program, same prompt."""

    @pytest.mark.parametrize("branch", ["dev", "canary", "beta", "production"])
    @pytest.mark.parametrize("enhance", ["auto", True, False])
    async def test_no_program_without_vary(self, branch, enhance, lists, monkeypatch):
        import user_agent
        monkeypatch.setattr(user_agent, "_app_branch", branch)
        monkeypatch.setattr(gen, "prompt_enhance_context", lambda *a, **k: {
            "model": "q", "mode": "qwen-image-2.1", "program_supported": True, "schema_props": {}, "enhance": {}})
        monkeypatch.setattr(gen, "native_prompt_format", lambda *a, **k: "Qwen-Image-2.1")
        seen = []

        async def spy(parameters, **kw):
            seen.append(kw.get("prompt_options"))
            return {**parameters, "prompt": "REWRITTEN"}

        async def no_program(*a, **k):
            raise AssertionError("no program may be prepared without vary")

        monkeypatch.setattr(gen, "_apply_generation_prompt_pipeline", spy)
        monkeypatch.setattr(gen, "_run_slots", no_program)
        out = await _direct("a [red] {cat|cat}", enhance=enhance)
        assert "prompt_program" not in out.params
        assert all("program" not in (o or {}) for o in seen)
        expected = "REWRITTEN" if enhance in ("auto", True) else "a red cat"
        assert out.params["prompt"] == expected


@pytest.fixture
def writer(monkeypatch, profile, prose_model):  # noqa: F811
    """The chat model that reads the prompt's slots, stubbed (as tests/test_slots_reader.py),
    and the improver, which keeps what it is given; returns the reader's calls."""
    import prompt_programs.fix as fix
    import routes.prompt_enhancement as pe

    async def no_context(tool_id, parameters, profile_id=None):
        return []

    async def no_judge(entry, project_id=None):
        return None

    async def improve(request, session):
        return pe.ImprovePromptResponse(improved_prompt=request.prompt)

    class _Session:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("lora_notes.lora_context_for", no_context)
    monkeypatch.setattr(fix, "await_judge", no_judge)
    monkeypatch.setattr(pe, "improve_prompt", improve)
    monkeypatch.setattr(gen, "get_current_profile", lambda: profile)
    monkeypatch.setattr(gen, "get_database_registry", lambda: type("R", (), {
        "get_database": lambda self, p: type("D", (), {"async_session_maker": _Session})()})())
    model = _use(monkeypatch, FakeModel(*[_reply(PORCH_READING)] * 8))
    return model.asked


async def _vary(**kw):
    return await prepare_prompt({"prompt": PROMPT, "seed": 7}, tool_id="t", task_type="text-to-image",
                                request=PromptRequest(vary=True, **kw), project_id=None)


class TestVary:
    async def test_fresh_choices_reported_and_recorded(self, writer):
        out = await _vary()
        record = out.params["prompt_program"]
        assert out.draw_seed == record["draw_seed"]
        assert out.choices and "pet" in out.choices and "list1" in out.choices
        assert out.params["prompt_metadata"] == {"original_prompt": PROMPT, "auto_improve_enabled": False}
        line = ph.choices_line(out.choices, out.draw_seed)
        assert line.startswith("choices: ") and f"(draw_seed {out.draw_seed})" in line and "pet = " in line

    async def test_unchecked_choices_are_mentioned_only_when_it_happened(self, writer, monkeypatch):
        from prompt_programs import fix as fx
        real = fx.realize_and_fix

        def judged(*a, **k):
            result, _ = real(*a, **k)
            return result, None

        monkeypatch.setattr(fx, "realize_and_fix", judged)
        assert (await _vary()).note is None  # checked, or no check configured: nothing said

        def unjudged(*a, **k):  # the judge couldn't be had for this run
            result, _ = real(*a, **k)
            return result, {"judge": "pick-judge/v", "skipped": "unavailable"}

        monkeypatch.setattr(fx, "realize_and_fix", unjudged)
        out = await _vary()
        assert out.params["prompt_program"]["fix"]["skipped"] == "unavailable"
        assert out.note == ph.UNCHECKED_NOTE and out.choices

    async def test_one_prepare_for_many_calls(self, writer):
        import asyncio
        outs = await asyncio.gather(*[_vary() for _ in range(6)])
        assert len(writer) == 1
        assert len({o.params["prompt_program"]["key"] for o in outs}) == 1

    async def test_draw_seed_repeats_the_choices(self, writer):
        first = await _vary()
        again = await _vary(draw_seed=first.draw_seed)
        assert again.choices == first.choices and again.params["prompt"] == first.params["prompt"]

    async def test_keep_choices_hold(self, writer):
        for _ in range(8):
            out = await _vary(keep_choices={"pet": "grey parrot"})
            assert out.choices["pet"] == "grey parrot"
        out = await _vary(keep_choices={"Season": ["summer"]})  # by label
        assert out.choices["list1"] == "summer"

    async def test_unknown_choice_names_the_real_ones(self, writer):
        with pytest.raises(PromptHandlingError) as e:
            await _vary(keep_choices={"hat": "bowler"})
        msg = str(e.value)
        assert msg.startswith('"hat" isn\'t a choice in this prompt. Its choices are: ')
        assert "pet" in msg and msg.endswith("Nothing was generated.")

    async def test_detail_level_follows_enhance_prompt(self, writer, monkeypatch):
        seen = []
        import prompt_pipeline
        real = prompt_pipeline.run_prompt_pipeline

        async def spy(*a, **kw):
            seen.append(kw.get("level"))
            return await real(*a, **kw)

        monkeypatch.setattr(prompt_pipeline, "run_prompt_pipeline", spy)
        await _vary()                       # prose model, omitted: Yours
        await _vary(enhance=False)          # Yours
        await _vary(enhance=True)           # High
        monkeypatch.setattr(gen, "native_prompt_format", lambda *a, **k: "FLUX.3 Klein")
        await _vary()                       # a model with its own format, omitted: Medium
        assert seen == ["off", "off", "expand", "fill"]

    async def test_no_chat_model_stops_the_call_and_says_so(self, writer, monkeypatch):
        from llm_resolver import LLMNotConfiguredError
        from prompt_programs import program

        async def unconfigured(*a, **kw):
            raise LLMNotConfiguredError("No chat model is configured.")

        monkeypatch.setattr(program, "ask_model", unconfigured)
        with pytest.raises(PromptHandlingError) as e:
            await _vary()
        assert "no chat model is set up" in str(e.value) and "Nothing was generated" in str(e.value)

    async def test_models_that_cant_vary_write_each_prompt(self, lists, monkeypatch):
        monkeypatch.setattr(gen, "prompt_enhance_context", lambda *a, **k: {
            "model": "h3", "mode": "minimax-h3", "program_supported": False, "schema_props": {}, "enhance": {}})
        monkeypatch.setattr(gen, "native_prompt_format", lambda *a, **k: "MiniMax H3")

        async def rewrite(params, **kw):
            return {**params, "prompt": "WRITTEN"}

        monkeypatch.setattr(gen, "enhance_tool_prompt", rewrite)
        out = await _vary()
        assert out.params["prompt"] == "WRITTEN" and out.note == ph.NO_CHOICES_NOTE
        assert out.choices is None and "prompt_program" not in out.params


class TestRequestArguments:
    def test_popped_from_the_tool_call(self):
        kw = {"prompt": "x", "vary": "true", "keep_choices": '{"a": "b"}', "draw_seed": "12"}
        req = ph.request_from(kw, "auto")
        assert kw == {"prompt": "x"} and req.vary and req.keep_choices == {"a": "b"} and req.draw_seed == 12

    def test_bad_values_say_how_to_fix(self):
        with pytest.raises(PromptHandlingError, match="keep_choices must map"):
            ph.request_from({"keep_choices": ["outfit"]}, "auto")
        with pytest.raises(PromptHandlingError, match="draw_seed must be a whole number"):
            ph.request_from({"draw_seed": "soon"}, "auto")
