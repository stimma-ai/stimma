"""Fluent's shared pieces: masking, saved wildcards, which tools vary their prompts, option
writing on request, LoRA context and trigger words, the acceptance fake's reading, store keys."""

import pytest

from prompt_programs import program as prep
from prompt_programs.fill import ProgramError
from prompt_programs.store import ProgramStore








class TestPrepare:


    def test_masking_round_trips(self):
        masked, exact = prep.mask_exact("a [sign that says OPEN] on {a|b}, [{{x}}] and [neon]")
        assert masked == "a [EXACT_1] on {a|b}, [{{x}}] and [EXACT_2]"
        assert prep.unmask_exact("A EXACT_1 and [EXACT_2].", exact) == "A [sign that says OPEN] and [neon]."

    async def test_exact_text_stays_protected_through_translate(self, monkeypatch):
        # After a run the text is back in brackets, so Translate's verbatim protection
        # hides it from the translation model and the final cleanup unwraps it.
        import prompt_pipeline as pp
        seen = []

        async def fake_translate(text, language, project_id):
            seen.append(text)
            return text.replace("a woman", "una mujer")

        monkeypatch.setattr(pp, "_profile_wildcards_and_segments", lambda profile_id: ([], []))
        monkeypatch.setattr(pp, "_translate_with_verbatim_protection",
                            lambda text, lang, pid: _protected(text, lang, pid, fake_translate))
        out = await pp.run_prompt_pipeline(None, "a woman under a sign that says [OPEN ALL NIGHT]",
                                           {"translate": {"enabled": True, "language": "es"}})
        assert "OPEN ALL NIGHT" not in " ".join(seen) and out == "una mujer under a sign that says OPEN ALL NIGHT"


    def test_named_wildcards_become_lists(self):
        out = prep.expand_named_lists("a {{color}} car, {{style}}", [{"name": "color", "values": ["red", "blue"]}],
                                      [{"name": "style", "content": "film photo"}])
        assert out == "a {red|blue} car, film photo"




class TestProgramSupport:
    @pytest.mark.parametrize("model,task,images,supported", [
        ("Qwen-Image-2.1", "text-to-image", 0, True), ("Qwen-Image-2.1", "image-to-image", 1, False),
        ("FLUX.3 Klein", "image-to-image", 1, False), ("sdxl", "text-to-image", 0, True),
        ("some model", "image-to-image", 1, False), ("some model", "text-to-audio", 0, False),
        ("some model", "text-to-video", 0, True),
    ])
    def test_edits_and_audio_keep_the_per_image_enhancer(self, monkeypatch, model, task, images, supported):
        import routes.generation as gen
        monkeypatch.setattr(gen, "_prompt_pipeline_context", lambda *a: (model, None, task, {}))
        monkeypatch.setattr(gen, "_prompt_input_image_count", lambda *a: images)
        assert gen.prompt_enhance_context({}, "t", task, None)["program_supported"] is supported


class TestSuggestOptions:
    ENTRY = {"key": "k", "prompt": "a woman in <stylish tank top>", "example": "a woman in a silk tank top",
             "slot_words": {"stylish_tank_top": "stylish tank top"},
             "elaborate": False, "mode": "prose",
             "choices": [{"id": "stylish_tank_top", "kind": "pick", "label": "Tank Top",
                          "about": "a stylish tank top", "options": ["a silk tank top", "a linen tank top"]},
                         {"id": "look", "kind": "lora", "label": "Look", "options": ["A"]}]}

    async def test_new_options_skip_existing_and_repeats(self, monkeypatch):
        from prompt_programs import options as opts
        calls = []

        async def fake_ask(messages, project_id, tool):
            calls.append(messages)
            return '```json\n["a silk tank top", "a ribbed cotton tank", "A ribbed cotton tank", "a sheer mesh tank"]\n```', None

        async def text_only(_pid):
            return ("", ""), False

        monkeypatch.setattr(opts, "_ask_options", fake_ask)
        monkeypatch.setattr(opts, "_endpoint", text_only)
        out = await opts.suggest_options(self.ENTRY, "stylish_tank_top", ["a silk tank top", "a linen tank top"], 2, None)
        assert out == ["a ribbed cotton tank", "a sheer mesh tank"] and len(calls) == 1
        system, user = calls[0][0]["content"], calls[0][1]["content"]
        # the same writer as background generation: its rules, the user's own words as a rule
        assert "Write 2 options" in system and "a few words" in system and "most typical" in system
        assert "- a linen tank top" in user and '"stylish tank top"' in user

    async def test_retries_once_when_short(self, monkeypatch):
        from prompt_programs import options as opts
        replies = ['["a ribbed cotton tank"]', '["a sheer mesh tank", "a crochet halter"]']

        async def fake_ask(messages, project_id, tool):
            return replies.pop(0), None

        async def text_only(_pid):
            return ("", ""), False

        monkeypatch.setattr(opts, "_ask_options", fake_ask)
        monkeypatch.setattr(opts, "_endpoint", text_only)
        out = await opts.suggest_options(self.ENTRY, "stylish_tank_top", [], 3, None)
        assert out == ["a ribbed cotton tank", "a sheer mesh tank", "a crochet halter"]

    async def test_only_picks(self):
        from prompt_programs import options as opts
        with pytest.raises(ProgramError):
            await opts.suggest_options(self.ENTRY, "look", [], 3, None)




async def _protected(text, lang, pid, translate):
    """The real masking from prompt_pipeline around a fake translation call."""
    from prompt_pipeline import extract_verbatim, restore_verbatim
    masked, segs = extract_verbatim(text)
    return restore_verbatim(await translate(masked, lang, pid), segs)


class TestLoraChoices:

    def test_notes_and_triggers_shape_what_the_model_is_told(self):
        from routes.generation import _shape_lora_context
        ctx = [{"name": "Wolf cut", "trigger_words": ["wolfcut"], "notes": "works best at 0.8"}]
        assert _shape_lora_context(ctx, True, True) == ctx
        assert _shape_lora_context(ctx, False, True)[0]["trigger_words"] == []
        assert _shape_lora_context(ctx, True, False)[0]["notes"] == ""
        assert _shape_lora_context([], False, False) == []


class TestTriggerWordsAreOptIn:
    """Builds without Fluent (and the agent) send no loraTriggers: nothing is added."""

    async def _run(self, monkeypatch, prompt_options):
        import routes.generation as gen

        async def fake_pipeline(db, prompt, options, **kw):
            return prompt

        async def fake_context(tool_id, parameters, profile_id=None):
            return [{"name": "Wolf cut", "trigger_words": ["wolfcut"], "notes": ""}]

        monkeypatch.setattr("prompt_pipeline.run_prompt_pipeline", fake_pipeline)
        monkeypatch.setattr("lora_notes.lora_context_for", fake_context)
        monkeypatch.setattr(gen, "prompt_enhance_context", lambda *a, **k: {
            "model": "m", "model_vendor": None, "schema_props": {}, "mode": "prose", "program_supported": True, "enhance": {}})
        monkeypatch.setattr(gen, "get_database_registry", lambda: type("R", (), {"get_database": lambda self, p: None})())
        monkeypatch.setattr(gen, "get_current_profile", lambda: "p")
        out = await gen._apply_generation_prompt_pipeline(
            {"prompt": "a woman", "loras": [{"lora": "wc.safetensors", "weight": 1}]},
            tool_id="t", task_type=None, prompt_options=prompt_options, prompt_preload=None)
        return out["prompt"]

    async def test_absent_adds_nothing(self, monkeypatch):
        assert await self._run(monkeypatch, {"autoImprove": {"enabled": False}}) == "a woman"

    async def test_fluent_builds_add_missing_triggers(self, monkeypatch):
        assert await self._run(monkeypatch, {"loraTriggers": True}) == "wolfcut, a woman"
        assert await self._run(monkeypatch, {"loraTriggers": False}) == "a woman"

    async def test_raw_never(self, monkeypatch):
        assert await self._run(monkeypatch, {"raw": True, "loraTriggers": True}) == "a woman"


class TestEditorAndRunAgreeOnTheKey:
    """The editor prepares with a sketch of the inputs (frontend contextParams); a run
    prepares with the real parameters. The parts of the key that depend on inputs must
    come out the same, or a run prepares a second program."""

    def test_video_start_frame(self):
        from routes.generation import _prompt_media_id
        editor = {"input_media_ids": [42]}
        run = {"image": "/library/frame.png", "image_media_id": 42}
        assert _prompt_media_id(editor, "image-to-video") == _prompt_media_id(run, "image-to-video") == 42

    def test_driving_audio(self):
        from routes.generation import _prompt_audio_conditioned
        schema = {"input_audios": {"x-control": "audio_picker"}}
        assert _prompt_audio_conditioned({"input_audios": ["ref"]}, schema)
        assert _prompt_audio_conditioned({"input_audios": ["/library/voice.wav"]}, schema)
        ref = {"input_audios": {"x-control": "audio_picker", "x-audio-role": "reference"}}
        assert not _prompt_audio_conditioned({"input_audios": ["ref"]}, ref)  # the editor doesn't send it either


class TestAcceptanceFakeReadsSlots:
    """The acceptance sandbox's fake chat model must answer the slot reader with a reading
    it can use, or every Fluent run of a prompt with slots on a fresh app is blocked."""

    async def test_the_fake_reply_is_a_usable_reading(self, tmp_path):
        from llm import _acceptance_program
        from prompt_programs import reader
        from prompt_programs.narrow import NarrowCache
        from prompt_programs.slots import compose, parse

        async def ask(messages, project_id, max_tokens):
            return _acceptance_program(messages)

        parsed = parse("# at dusk\na <young man> on a {red|blue} bench by the <lake>")
        got = await reader.read(parsed, ask=ask, project_id=None, model="m", cache=NarrowCache(tmp_path))
        entry = compose(parsed, {r["n"]: r for r in got["slots"]}, {r["n"]: r["label"] for r in got["lists"]})
        assert [s["kind"] for s in entry["slots"]] == ["free", "free"] and not any(s.get("degraded") for s in entry["slots"])
        assert {c["id"] for c in entry["choices"]} == {"young_man", "lake", "list1"}

    def test_other_requests_keep_the_dummy_reply(self):
        from llm import _acceptance_program
        assert _acceptance_program([{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "hi"}]) is None


class TestStoreKeys:
    def test_only_program_keys_reach_the_disk(self, tmp_path):
        from prompt_programs.store import program_key
        store = ProgramStore(tmp_path / "store")
        (tmp_path / "secret.json").write_text('{"program": "emit(1)"}')
        (tmp_path / "store").mkdir()
        for bad in ["../secret", "../../secret", "/etc/passwd", "ab/../../secret", "A" * 32, "0" * 31, "", None, 7,
                    "0" * 32 + "/../x", "..%2fsecret"]:
            assert store.get(bad) is None
        with pytest.raises(ValueError):
            store.put("../secret", {"x": 1})
        key = program_key({"prompt": "a cat"})
        store.put(key, {"key": key})
        assert store.get(key) == {"key": key}
