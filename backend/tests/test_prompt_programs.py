"""Prompt programs: the runtime, discovery, prepare (with a stubbed model) and the
per-job application of a run."""

import pytest

from prompt_programs import prepare as prep
from prompt_programs.runtime import LoraInfo, ProgramError, discover, run
from prompt_programs.store import ProgramStore


async def fake_style(*a, **kw):
    return "STYLE GUIDE: write rich prose.", []

TRAIN = '''
weather = pick("weather", ["rainy", "foggy", "bright"], label="Weather", source="list", line=1)
umbrella = None
if weather == "rainy":
    umbrella = pick("umbrella", ["holding a clear umbrella", "holding a black umbrella"], label="Umbrella", added=True)
hair = pick_lora("hairstyle", ["Curtain bangs", "Wolf cut"], label="Hairstyle", line=3)
clothing = pick("clothing", by=weather, label="Clothing", line=2, options={
    "rainy": ["a trench coat", "a rain jacket"], "foggy": ["a wool coat"], "bright": ["a linen shirt"]})
param("guidance", 3.5, 5.5, line=4)
emit("A woman waiting for a train on a", weather, "morning, wearing", clothing, ",", umbrella, ". [Shot on Portra 400]")
'''
# What the program writer replies now that it only ever sees [EXACT_1] for the user's
# protected text (see prepare.mask_exact).
TRAIN_M = TRAIN.replace("[Shot on Portra 400]", "[EXACT_1]")
LORAS = [LoraInfo("Curtain bangs", "loras/cb.safetensors", 0.8, "cbangs"), LoraInfo("Wolf cut", "loras/wc.safetensors", 0.9, "wolfcut")]
PARAMS = {"guidance", "steps"}


class TestRuntime:
    def test_same_seed_same_result(self):
        a = run(TRAIN, 42, None, LORAS, PARAMS)
        b = run(TRAIN, 42, None, LORAS, PARAMS)
        assert a.prompt == b.prompt and [d.value for d in a.draws] == [d.value for d in b.draws]

    def test_seeds_vary(self):
        prompts = {run(TRAIN, s, None, LORAS, PARAMS).prompt for s in range(30)}
        assert len(prompts) > 5

    def test_pins_narrow_the_draw(self):
        for s in range(20):
            r = run(TRAIN, s, {"weather": ["rainy"], "hairstyle": ["Wolf cut"]}, LORAS, PARAMS)
            assert "rainy" in r.prompt and r.loras[0].name == "Wolf cut"
            assert any(d.id == "umbrella" for d in r.draws)

    def test_a_pin_outside_the_options_is_ignored(self):
        r = run(TRAIN, 1, {"weather": ["snowy"]}, LORAS, PARAMS)
        assert any(d.id == "weather" and d.value in ("rainy", "foggy", "bright") for d in r.draws)

    def test_fixed_replays_draws(self):
        first = run(TRAIN, 3, None, LORAS, PARAMS)
        fixed = {d.id: d.value for d in first.draws}
        again = run(TRAIN, 999, None, LORAS, PARAMS, fixed)
        assert again.prompt == first.prompt

    def test_user_edits(self):
        for s in range(20):
            r = run(TRAIN, s, {"weather": ["sleet"]}, LORAS, PARAMS, None,
                    {"weather": {"add": ["sleet"]}, "umbrella": {"off": True}, "clothing": {"remove": ["a trench coat"]}})
            assert "sleet" in r.prompt and not any(d.id == "umbrella" for d in r.draws)
            assert "trench coat" not in r.prompt

    def test_lora_trigger_and_weight(self):
        r = run(TRAIN, 5, {"hairstyle": ["Curtain bangs"]}, LORAS, PARAMS)
        assert r.prompt.startswith("cbangs,")
        assert r.loras[0].path == "loras/cb.safetensors" and r.loras[0].weight == 0.8

    def test_param_range(self):
        vals = {run(TRAIN, s, None, LORAS, PARAMS).params["guidance"] for s in range(40)}
        assert all(3.5 <= v <= 5.5 for v in vals) and len(vals) > 3

    def test_param_must_exist_and_not_be_added(self):
        with pytest.raises(ProgramError, match="no parameter"):
            run('param("cfg", 1, 2)\nemit("x")', 1, None, [], PARAMS)
        with pytest.raises(ProgramError, match="only vary when the user asks"):
            run('param("guidance", 1, 2, source="added")\nemit("x")', 1, None, [], PARAMS)

    def test_loop_with_distinct_values(self):
        src = '''
ages = []
for i in range(group("people", 3, label="People")):
    a = pick(f"people[{i+1}].age", ["20s", "40s", "70s"], exclude=ages)
    ages.append(a)
emit("Three friends:", ", ".join(ages))
'''
        for s in range(15):
            r = run(src, s)
            assert sorted(d.value for d in r.draws) == ["20s", "40s", "70s"]
            assert r.groups["people"]["count"] == 3

    @pytest.mark.parametrize("bad, msg", [
        ("import os\n", "Import is not allowed"),
        ("x = ().__class__\n", "is not allowed"),
        ("while True:\n    pass\n", "While is not allowed"),
        ("emit(open('x'))\n", "NameError"),
        ("for i in range(1000000000):\n    pass\nemit('x')\n", "ran too long"),
        ("pick('a', ['x'])\npick('a', ['y'])\nemit('z')\n", "used twice"),
        ("pick('a', ['x'])\n", "emitted no prompt"),
    ])
    def test_rejections(self, bad, msg):
        with pytest.raises(ProgramError, match=msg):
            run(bad, 1)


class TestDiscover:
    def test_structure(self):
        info = discover(TRAIN, LORAS, PARAMS)
        by = {c["id"]: c for c in info["choices"]}
        assert by["weather"]["source"] == "list" and by["weather"]["options"] == ["rainy", "foggy", "bright"]
        assert by["umbrella"]["parent"] == "weather" and by["umbrella"]["when"] == ["rainy"]
        assert by["umbrella"]["source"] == "added"
        assert by["clothing"]["follows"] == "weather"
        assert set(by["clothing"]["options"]) == {"a trench coat", "a rain jacket", "a wool coat", "a linen shirt"}
        assert by["hairstyle"]["kind"] == "lora"
        assert by["param.guidance"]["options"] == ["3.5", "5.5"]
        assert info["params"] == ["guidance"]


PROMPT = "A woman waiting for a train on a {rainy|foggy|bright} morning. [Shot on Portra 400]\n# Vary her clothing.\n# Hairstyle: use the curtain bangs or wolf cut LoRA.\n# Vary guidance between 3.5 and 5.5."


@pytest.fixture
def stub(monkeypatch, tmp_path):
    calls = []

    async def fake_ask(messages, project_id, max_tokens=4096):
        calls.append(messages)
        return replies.pop(0)

    async def fake_candidates(tool_id, items, profile_id):
        return list(LORAS), {}

    replies = []
    enhanced = {"text": "A woman waiting for a train on a [{rainy|foggy|bright}] morning. [EXACT_1]"}

    async def fake_upsample(prompt, ctx, instructions, lora_context, project_id, profile_id):
        calls.append([{"role": "upsample", "content": prompt}])
        return enhanced["text"]

    monkeypatch.setattr(prep, "upsample", fake_upsample)
    monkeypatch.setattr(prep, "writer_style", fake_style)
    monkeypatch.setattr(prep, "_ask_model", fake_ask)
    monkeypatch.setattr(prep, "lora_candidates", fake_candidates)
    monkeypatch.setattr(prep, "_store", lambda profile_id: ProgramStore(tmp_path))
    monkeypatch.setattr("prompt_pipeline._profile_wildcards_and_segments", lambda profile_id: ([], []))
    stub_state["enhanced"] = enhanced
    return calls, replies


stub_state = {}


def ctx(schema):
    return {"model": "m", "mode": "prose", "schema_props": schema, "enhance": {}}


SCHEMA = {"guidance": {"type": "number", "minimum": 1, "maximum": 10}, "seed": {"type": "integer"}, "prompt": {"type": "string"}}


class TestPrepare:
    async def _ensure(self):
        return await prep.ensure_program(prompt=PROMPT, tool_id="t", ctx=ctx(SCHEMA), instructions="",
                                         lora_items=[], project_id=None, profile_id="p")

    async def test_prepares_once_then_caches(self, stub):
        calls, replies = stub
        replies.append(f"```python\n{TRAIN_M}```")
        entry = await self._ensure()
        assert entry["params"] == {"guidance": {"type": "number", "minimum": 1, "maximum": 10}}
        assert {c["id"] for c in entry["choices"]} >= {"weather", "umbrella", "clothing", "hairstyle"}
        assert "[" not in entry["example"]
        again = await self._ensure()
        assert again["key"] == entry["key"] and len(calls) == 1  # one model call writes the program

    async def test_concurrent_runs_share_one_prepare(self, stub):
        import asyncio
        calls, replies = stub
        replies.append(f"```python\n{TRAIN_M}```")
        first, second = await asyncio.gather(self._ensure(), self._ensure())
        assert first["key"] == second["key"] and len(calls) == 1

    async def test_canvas_size_does_not_change_the_key(self, stub):
        calls, replies = stub
        replies.append(f"```python\n{TRAIN_M}```")
        sized = {**ctx(SCHEMA), "enhance": {"is_video": False, "width": 1024, "height": 1024}}
        unsized = {**ctx(SCHEMA), "enhance": {"is_video": False, "width": None, "height": None}}
        a = await prep.ensure_program(prompt=PROMPT, tool_id="t", ctx=sized, instructions="", lora_items=[], project_id=None, profile_id="p")
        b = await prep.ensure_program(prompt=PROMPT, tool_id="t", ctx=unsized, instructions="", lora_items=[], project_id=None, profile_id="p")
        assert a["key"] == b["key"] and len(calls) == 1

    async def test_retries_with_the_problem(self, stub):
        calls, replies = stub
        replies.append('```python\nemit("A woman on a platform")\n```')  # drops the user list + protected text
        replies.append(f"```python\n{TRAIN_M}```")
        entry = await self._ensure()
        assert entry["attempts"] == 2 and not entry["warnings"]
        feedback = calls[1][-1]["content"]
        assert "EXACT_1" in feedback and "{rainy|foggy|bright}" in feedback

    async def test_a_pick_that_never_reaches_the_prompt_is_sent_back(self, stub):
        calls, replies = stub
        replies.append("```python\n" + TRAIN_M.replace('"morning, wearing", clothing,', '"morning,"') + "```")
        replies.append(f"```python\n{TRAIN_M}```")
        entry = await self._ensure()
        assert entry["attempts"] == 2
        assert 'pick("clothing")' in calls[1][-1]["content"]

    async def test_marks_asked_for_choices_as_from_text(self, stub):
        _, replies = stub
        replies.append("```python\n" + TRAIN_M.replace('label="Clothing", line=2', 'label="Clothing", added=True') + "```")
        entry = await self._ensure()
        clothing = next(c for c in entry["choices"] if c["id"] == "clothing")
        assert clothing["source"] == "text" and clothing["line"] == 2

    async def test_one_call_writes_the_program_with_the_models_style_guide(self, stub):
        calls, replies = stub
        replies.append(f"```python\n{TRAIN_M}```")
        await self._ensure()
        assert len(calls) == 1
        assert "STYLE GUIDE" in calls[0][0]["content"] and "[EXACT_1]" in calls[0][1]["content"]
        assert "Enhanced prompt" not in calls[0][1]["content"]

    async def test_enhance_off_keeps_the_users_words(self, stub):
        calls, replies = stub
        replies.append(f"```python\n{TRAIN_M}```")
        kept = await prep.ensure_program(prompt=PROMPT, tool_id="t", ctx=ctx(SCHEMA), instructions="",
                                         lora_items=[], project_id=None, profile_id="p", elaborate=False)
        assert len(calls) == 1 and "STYLE GUIDE" not in calls[0][0]["content"]
        assert "keeping the user's words" in calls[0][1]["content"]
        assert kept["elaborate"] is False
        replies.append(f"```python\n{TRAIN_M}```")
        rich = await self._ensure()
        assert rich["key"] != kept["key"]  # a separate program per mode

    async def test_keyword_models_keep_words_as_tags(self, stub):
        calls, replies = stub
        replies.append(f"```python\n{TRAIN_M}```")
        await prep.ensure_program(prompt=PROMPT, tool_id="t", ctx={**ctx(SCHEMA), "mode": "keyword"}, instructions="",
                                  lora_items=[], project_id=None, profile_id="p", elaborate=False)
        assert "comma-separated tags" in calls[0][1]["content"]

    async def test_kept_words_that_go_missing_are_sent_back(self, stub):
        calls, replies = stub
        replies.append("```python\n" + TRAIN_M.replace('"A woman waiting for a train on a"', '"A woman for a train on a"') + "```")
        replies.append(f"```python\n{TRAIN_M}```")
        entry = await prep.ensure_program(prompt=PROMPT, tool_id="t", ctx=ctx(SCHEMA), instructions="",
                                          lora_items=[], project_id=None, profile_id="p", elaborate=False)
        assert entry["attempts"] == 1 and any('"waiting"' in w for w in entry["warnings"])  # noted, not retried

    async def test_a_pick_emitted_twice_is_sent_back(self, stub):
        calls, replies = stub
        replies.append("```python\n" + TRAIN_M.replace('", umbrella, ". [EXACT_1]', '", umbrella, ", in", clothing, ". [EXACT_1]') + "```")
        replies.append(f"```python\n{TRAIN_M}```")
        entry = await self._ensure()
        assert entry["attempts"] == 1 and any('pick("clothing") appears more than once' in w for w in entry["warnings"])

    def test_the_enhancer_writes_examples_for_smart_wildcards(self):
        assert prep._for_enhancer("a woman with {{hair style}} on a {red|blue} wall") == "a woman with \u27e8hair style\u27e9 on a {red|blue} wall"

    def test_plain_example_drops_instruction_lines(self):
        assert prep.plain_example("a {{hair}} woman\n# vary her mood\non a {red|blue} wall") == "a [{{hair}}] woman\non a [{red|blue}] wall"

    async def test_no_model_ever_sees_exact_text(self, stub):
        calls, replies = stub
        replies.append(f"```python\n{TRAIN_M}```")
        entry = await self._ensure()
        seen = " ".join(m["content"] for c in calls for m in c)
        assert "Shot on Portra 400" not in seen and "[EXACT_1]" in seen
        assert entry["exact"] == {"EXACT_1": "Shot on Portra 400"}
        assert all("Shot on Portra 400" in prep.realize(entry, seed=s).prompt for s in range(5))

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

    def test_protects_variable_spots(self):
        out = prep.protect_variable_spots("a {{hair style}} on a {red|blue} wall, [keep] {single}")
        assert out == "a [{{hair style}}] on a [{red|blue}] wall, [keep] {single}"

    def test_lora_lookup_only_named(self):
        cands = LORAS + [LoraInfo("Anime lineart", "x", 1.0, "")]
        assert [lo.name for lo in prep.match_loras(PROMPT, cands)] == ["Curtain bangs", "Wolf cut"]
        assert prep.match_loras("a cat on a mat", cands) == []
        assert len(prep.match_loras("use one of my LoRAs", cands)) == 3

    def test_named_wildcards_become_lists(self):
        out = prep.expand_named_lists("a {{color}} car, {{style}}", [{"name": "color", "values": ["red", "blue"]}],
                                      [{"name": "style", "content": "film photo"}])
        assert out == "a {red|blue} car, film photo"


SMART_PROMPT = "A portrait of a woman with {{hair style}} on a {{color}} background."
SMART_GOOD = '''
hair = pick("hair_style", ["a sleek bun", "loose waves", "a pixie cut"], label="Hair style", line=1)
color = pick("color", ["teal", "ochre", "pale pink"], label="Color", line=1)
emit("A portrait of a woman with", hair, "on a", color, "background.")
'''


class TestSmartWildcards:
    async def _ensure(self, prompt):
        return await prep.ensure_program(prompt=prompt, tool_id="t", ctx=ctx({}), instructions="",
                                         lora_items=[], project_id=None, profile_id="p")

    async def test_unknown_double_braces_become_user_choices(self, stub):
        _, replies = stub
        replies.append(f"```python\n{SMART_GOOD}```")
        entry = await self._ensure(SMART_PROMPT)
        by = {c["id"]: c for c in entry["choices"]}
        assert by["hair_style"]["wildcard"] == "hair style" and by["hair_style"]["source"] == "text"
        assert by["hair_style"]["line"] == 1 and by["color"]["wildcard"] == "color"
        assert entry["attempts"] == 1

    async def test_missing_or_leaked_smart_wildcard_is_sent_back(self, stub):
        calls, replies = stub
        replies.append('```python\nemit("A portrait of a woman with {{hair style}} on a teal background.")\n```')
        replies.append(f"```python\n{SMART_GOOD}```")
        entry = await self._ensure(SMART_PROMPT)
        assert entry["attempts"] == 2
        feedback = calls[1][-1]["content"]
        assert 'pick("hair_style"' in feedback and "Don't emit {{" in feedback

    async def test_long_wildcard_names_get_short_labels(self, stub):
        calls, replies = stub
        prompt = "A woman on a platform. {{35mm photographic details, no shallow dof}}"
        long = '''
look = pick("35mm_photographic_details_no_shallow_dof", ["grainy film, deep focus", "crisp 35mm, f/8"], label="{label}", line=1)
emit("A woman on a platform.", look)
'''
        replies.append("```python\n" + long.replace("{label}", "35mm photographic details, no shallow dof") + "```")
        replies.append("```python\n" + long.replace("{label}", "Photo look") + "```")
        entry = await self._ensure(prompt)
        assert entry["attempts"] == 1 and any("too long" in w for w in entry["warnings"])
        replies.clear()
        return
        assert entry["choices"][0]["wildcard"] == "35mm photographic details, no shallow dof"

    async def test_descriptive_name_is_not_an_option(self, stub):
        calls, replies = stub
        prompt = "A woman. {{film look}}"
        replies.append('```python\nlook = pick("film_look", ["film look", "film look"], label="Look", line=1)\nemit("A woman.", look)\n```')
        replies.append('```python\nlook = pick("film_look", ["Portra grain", "HP5 black and white"], label="Look", line=1)\nemit("A woman.", look)\n```')
        entry = await self._ensure(prompt)
        assert entry["attempts"] == 1 and any('never the word "film look" itself' in w for w in entry["warnings"])
        replies.clear()

    def test_descriptive_name_is_cut_from_its_options(self):
        src = 'note = "it’s – fine"\nlook = pick("film_look", ["“Portra” grain", "film look", "HP5"], label="Look")\nemit(note, look)\n'
        out = prep.drop_name_options(src, "A woman. {{film look}}")
        assert '["“Portra” grain", "HP5"]' in out
        assert prep.drop_name_options(src, "A woman, no wildcards.") == src

    async def test_global_wildcards_still_win(self, stub, monkeypatch):
        _, replies = stub
        monkeypatch.setattr("prompt_pipeline._profile_wildcards_and_segments",
                            lambda profile_id: ([{"name": "color", "values": ["red", "blue"]}], []))
        replies.append('''```python
hair = pick("hair_style", ["a sleek bun", "loose waves"], label="Hair style", line=1)
color = pick("color", ["red", "blue"], label="Color", source="list", line=1)
emit("A portrait of a woman with", hair, "on a", color, "background.")
```''')
        entry = await self._ensure(SMART_PROMPT)
        by = {c["id"]: c for c in entry["choices"]}
        assert by["color"]["source"] == "list" and "wildcard" not in by["color"]
        assert by["hair_style"]["wildcard"] == "hair style"


# A structure-only program (pick specs): what the writer replies since pp-20.
TRAIN_S = '''
weather = pick("weather", ["rainy", "foggy", "bright"], label="Weather", source="list", phase=1, line=1)
clothing = pick("clothing", about="her coat in this weather", seed=["a belted olive trench coat"], label="Clothing", phase=2, line=2)
hair = pick_lora("hairstyle", ["Curtain bangs", "Wolf cut"], label="Hairstyle", line=3)
param("guidance", 3.5, 5.5, line=4)
emit("A woman waiting for a train on a", weather, "morning, wearing", clothing, ". [EXACT_1]")
'''


class TestFixInPlace:
    def test_phases_are_added_and_raised_to_fit_the_rule(self):
        from prompt_programs.draws import analyze
        src = ('job = pick("job", about="her job", seed=["nurse"], phase=1)\n'
               'w = pick("w", ["rain", "sun"], source="list")\n'
               'if job == "nurse":\n'
               '    hat = pick("hat", about="a hat", seed=["a cap"], phase=1,\n'
               '    )\n'
               'emit("A", job, w, hat)\n')
        out, notes = prep.fix_phases(src)
        analyze(out)  # passes the dependency rule now
        assert 'source="list", phase=1)' in out and "phase=2," in out
        assert len(notes) == 2
        assert prep.fix_phases(TRAIN_M) == (TRAIN_M, [])  # older programs are left alone

    def test_a_seed_left_in_the_fixed_text_is_cut_only_where_it_stands_alone(self):
        src = ('l = pick("light", about="the light", seed=["dramatic light"], phase=1)\n'
               'emit("a knight, dramatic light, 8k,", l)\n'
               'emit("glints under the dramatic light, posing", l)\n')
        out, notes = prep.fix_duplicates(src)
        assert 'emit("a knight, , 8k,", l)' in out and "under the dramatic light" in out and len(notes) == 1

    def test_line_edits(self):
        src = 'a = pick("a", about="x", seed=["one"],\n    phase=1)\nemit("A", a, "and", a)\n'
        assert prep.apply_line_edits(src, '3: emit("A", a)') == 'a = pick("a", about="x", seed=["one"],\n    phase=1)\nemit("A", a)\n'
        # a whole statement given for its first line replaces all of its lines; prose is ignored
        out = prep.apply_line_edits(src, 'Sure.\n1: a = pick("a", about="x", seed=["one", "two"], phase=1)\nThat fixes it.')
        assert out == 'a = pick("a", about="x", seed=["one", "two"], phase=1)\nemit("A", a, "and", a)\n'
        assert prep.apply_line_edits(src, "2.5: b = 1\n1:") .startswith("    phase=1)\nb = 1\n")
        assert prep.apply_line_edits(src, "No edits needed.") is None


class TestFixInCode:
    def test_an_unplaced_pick_goes_where_its_seed_stands_and_an_unused_hidden_or_added_one_goes(self):
        src = ('e = pick("expr", about="x", seed=["smiling broadly"], phase=1, line=2)\n'
               'h = pick("h", about="x", seed=["red hair"], phase=1,\n    hidden=True)\n'
               'v = pick("v", about="x", seed=["a scarf"], phase=1, added=True)\n'
               'u = pick("u", about="x", seed=["a hat"], phase=1, line=1)\n'
               'emit("A man smiling broadly at a dog.")\n')
        out, notes = prep.fix_unplaced(src)
        assert 'emit("A man ", e, " at a dog.")' in out and "red hair" not in out
        assert "a scarf" not in out  # variety nobody asked for: the program is whole without it
        assert 'u = pick("u"' in out  # a choice that may be the user's goes back to the writer
        assert len(notes) == 3

    def test_syntax_slips_are_put_right_where_the_parser_points(self):
        src = ('a = pick("a", about="x", seed=["one"], phase=1, added=True)\n'
               'emit("A woman with", a, ". The scene is shot with a shallow depth of field, \n'
               '     emphasizing the fabric. High-resolution,\n'
               '     8k.")\n')
        out, notes = prep.fix_quotes(src)
        compile(out, "<program>", "exec")
        assert "field, emphasizing the fabric. High-resolution, 8k." in out and notes
        src = ('# The user wants a portrait. I will add picks for her features,\n'
               'formed by the "detailed face" request.\n'
               'a = pick("a", about="x", seed=["one"], phase=1)\nemit(a)\n')
        out, notes = prep.fix_quotes(src)
        compile(out, "<program>", "exec")
        assert 'a = pick("a"' in out and notes
        broken = 'a = pick("a, about="x", seed=["one"], phase=1)\nemit(a)\n'
        assert prep.fix_quotes(broken)[0] == broken  # nothing it can tell for sure: left for validation

    def test_an_unclosed_fence_still_gives_the_program(self):
        from prompt_programs.runtime import extract_code
        assert extract_code('```python\na = 1\nemit("x")\n') == 'a = 1\nemit("x")\n'

    def test_unmarked_details_count_toward_the_cap_and_dependent_ones_stay(self):
        src = ('job = pick("job", ["nun", "nurse"], source="list", phase=1, line=1)\n'
               'look = pick("look", about=f"how the {job} looks", seed=["tired eyes"], phase=2, line=1)\n'
               'g1 = pick("girl[1].hair", about="x", seed=["red hair"], phase=1, line=1)\n'
               'g2 = pick("girl[2].hair", about="x", seed=["grey hair"], phase=1, line=1)\n'
               'mood = pick("mood", about="x", seed=["calm"], phase=1, line=1)\n'
               'light = pick("light", about="x", seed=["soft light"], phase=1, added=True)\n'
               'sky = pick("sky", about="x", seed=["a clear sky"], phase=1, added=True)\n'
               'season = pick("season", about="the season", seed=["autumn"], phase=1, line=1)\n'
               'emit(job, look, g1, g2, mood, light, sky, season)\n')
        out, notes = prep.trim_added(src, "A {nun|nurse} and two girls, {{season}}")
        # details: look, hair (one per girl), mood, light, sky; {{season}} and the list aren't added
        assert 'sky = "a clear sky"' in out and 'light = "soft light"' in out and len(notes) == 2
        assert 'look = pick(' in out and 'season = pick(' in out and 'g2 = pick(' in out

    STATED = "A {nun|nurse} in her thirties waiting on a rainy platform, {{outfit}}, candid photo"
    STATED_EX = "A candid photo of a [{nun|nurse}] in her thirties waiting on a rainy platform, wearing a grey coat."

    def test_a_pick_holding_what_the_user_stated_becomes_fixed_text(self):
        src = ('job = pick("job", ["nun", "nurse"], label="Job", source="list", phase=1, line=1)\n'
               'age = pick("age", about="her age", seed=["in her thirties"], phase=1, added=True)\n'
               'place = pick("place", about="the setting", seed=["a rainy platform"], phase=1, added=True)\n'
               'outfit = pick("outfit", about=f"what a {job} wears", seed=["a grey coat"], phase=2, line=1)\n'
               'emit("A candid photo of a", job, age, "waiting on", place, ", wearing", outfit, ".")\n')
        assert set(prep.lost_stated(src, self.STATED, self.STATED_EX).values()) == {"thirties", "rainy", "platform"}
        notes = prep.validate(src, self.STATED, [], set(), self.STATED_EX)["notes"]
        assert any('"thirties"' in p and "stays fixed text" in p for p in notes)  # a note; fix_stated repairs it in code
        out, notes = prep.fix_stated(src, self.STATED, self.STATED_EX)
        assert 'age = "in her thirties"' in out and 'place = "a rainy platform"' in out and len(notes) == 2
        assert 'outfit = pick(' in out  # the user's wildcard stays a pick
        assert not prep.validate(out, self.STATED, [], set(), self.STATED_EX)["problems"]

    def test_grammar_is_not_stated_and_unclassifiable_words_are_never_frozen(self):
        src = ('outfit = pick("outfit", about="what she wears", seed=["eine rote Jacke"], phase=1, added=True)\n'
               'emit("Ein Porträt einer Frau, sie trägt", outfit)\n')
        enhanced = "Ein Porträt einer Frau, sie trägt eine rote Jacke."
        assert prep.lost_stated(src, "Eine Frau", enhanced) == {}
        assert prep.fix_stated(src, "Eine Frau", enhanced) == (src, [])
        # One word that is English too ("her") is not enough to call a prompt English.
        assert prep.lost_stated(src, "Eine Frau kommt von rechts her", enhanced) == {}
        assert prep.fix_stated(src, "Eine Frau kommt von rechts her", enhanced) == (src, [])
        # In English, "a"/"her" are grammar: only stated content words count as lost.
        en = ('outfit = pick("outfit", about="what she wears", seed=["a red jacket on her"], phase=1, added=True)\n'
              'emit("A portrait of a woman", outfit)\n')
        assert prep.lost_stated(en, "A portrait of a woman, the light on her", "A portrait of a woman, a red jacket on her, the light") \
            == {"light": "light"}

    def test_a_fixed_copy_of_the_users_words_is_never_cut(self):
        src = ('w = pick("w", about="the weather", seed=["a rainy platform"], phase=1, added=True)\n'
               'emit("A nun waiting, a rainy platform, candid photo", w)\n')
        out, _ = prep.fix_duplicates(src, self.STATED)
        assert "waiting, a rainy platform, candid" in out
        out, notes = prep.fix_stated(src, self.STATED, self.STATED_EX)
        assert out.splitlines()[1] == 'emit("A nun waiting, a rainy platform, candid photo")' and notes

    def test_what_a_hash_line_asks_to_vary_is_shown_and_an_unused_group_goes(self):
        src = ('people = group("people", 3, label="People", line=1)\n'
               'o1 = pick("o1", about="x", seed=["a coat"], phase=2, line=2, hidden=True)\n'
               'o2 = pick("o2", about="x", seed=["a dress"], phase=2,\n    line=2, added=True)\n'
               'h = pick("h", about="x", seed=["grey hair"], phase=2, line=1, hidden=True)\n'
               'emit("Three friends,", o1, o2, h)\n')
        out, notes = prep.fix_requested(src, "Three friends on a bench\n# vary their outfits")
        assert "group(" not in out and "hidden=True" in out.splitlines()[-2] and len(notes) == 3
        assert 'line=2)\n' in out and "added" not in out

    def test_a_generated_pick_named_in_about_is_described_instead(self):
        from prompt_programs.draws import analyze
        src = ('age = pick("people[1].age", about="the first friend\'s age", seed=["an old man"], phase=1)\n'
               'job = pick("job", ["nun", "nurse"], source="list", phase=1)\n'
               'o = pick("o", about=f"what {age} wears as a {job}", seed=["a coat"], phase=2)\n'
               'o2 = pick("o2", about=f"what {age} wears", seed=["a coat"], phase=2)\nemit(age, job, o, o2)\n')
        out, notes = prep.fix_generated_refs(src)
        assert 'about=f"what [the first friend\'s age] wears as a {job}"' in out
        assert 'about="what [the first friend\'s age] wears"' in out and len(notes) == 2
        analyze(out)

    def test_placeholder_brackets_around_a_pick_go(self):
        out, notes = prep.fix_brackets('job = pick("job", ["a", "b"], source="list", phase=1)\nemit("A [", job, "] at work")\n')
        assert 'emit("A ", job, " at work")' in out and notes

    def test_adjacent_bracketed_picks_share_the_literal_between_them(self):
        src = ('a = pick("a", ["x", "y"], source="list", phase=1)\nb = pick("b", ["p", "q"], source="list", phase=1)\n'
               'emit("A [", a, "] in [", b, "]")\n')
        out, notes = prep.fix_brackets(src)
        assert 'emit("A ", a, " in ", b, " ")' in out and notes == ["2 placeholder bracket pair(s) taken out of emit()"]
        compile(out, "<program>", "exec")

    def test_a_wildcards_name_with_an_article_is_not_a_seed(self):
        src = 'brand = pick("brand", about="the brand", seed=["a brand", "Acme"], phase=1)\nemit(brand)\n'
        assert 'seed=["Acme"]' in prep.drop_name_options(src, "a {{brand}} laptop")
        assert prep.is_name_of("The Brands.", "brand") and not prep.is_name_of("a brand new laptop", "brand")

    def test_more_than_three_added_picks_become_fixed_text(self):
        src = "".join(f'p{i} = pick("{n}", about="x", seed=["s{i}"], phase=1, added=True)\n'
                      for i, n in enumerate(["light", "sky", "mood", "pose", "lens"]))
        out, notes = prep.trim_added(src + "emit(p0, p1, p2, p3, p4)\n")
        assert 'p3 = "s3"' in out and 'p4 = "s4"' in out and 'p2 = pick(' in out and len(notes) == 2


class TestFastPrepare:
    async def _ensure(self, prompt=PROMPT, **kw):
        return await prep.ensure_program(prompt=prompt, tool_id="t", ctx=ctx(SCHEMA), instructions="",
                                         lora_items=[], project_id=None, profile_id="p", **kw)

    async def test_structure_only_program(self, stub):
        calls, replies = stub
        replies.append(f"```python\n{TRAIN_S}```")
        entry = await self._ensure()
        by = {c["id"]: c for c in entry["choices"]}
        assert by["clothing"]["about"] == "her coat in this weather" and by["clothing"]["phase"] == 2
        assert by["clothing"]["options"] == ["a belted olive trench coat"] and not entry["warnings"]
        assert entry["attempts"] == 1 and entry["timing"]["calls"][0]["kind"] == "write"
        assert "seed=" in calls[0][0]["content"] and "check every combination" not in calls[0][0]["content"]

    async def test_a_problem_is_fixed_with_line_edits(self, stub):
        calls, replies = stub
        broken = TRAIN_S.replace('"morning, wearing", clothing,', '"morning, wearing a coat"')
        replies.append(f"```python\n{broken}```")
        line = next(i for i, ln in enumerate(broken.strip("\n").splitlines(), 1) if ln.startswith("emit("))
        replies.append(f'{line}: emit("A woman waiting for a train on a", weather, "morning, wearing", clothing, ". [EXACT_1]")')
        entry = await self._ensure()
        assert not entry["warnings"] and [c["kind"] for c in entry["timing"]["calls"]] == ["write", "repair"]
        repair = calls[1][-1]["content"]
        assert 'pick("clothing")' in repair and f"{line}: emit(" in repair  # the problem, and the numbered program

    async def test_a_repair_that_does_not_settle_it_is_followed_by_a_rewrite(self, stub):
        calls, replies = stub
        broken = TRAIN_S.replace('"morning, wearing", clothing,', '"morning, wearing a coat"')
        replies += [f"```python\n{broken}```", "1:", f"```python\n{TRAIN_S}```"]  # the repair deletes a line
        entry = await self._ensure()
        assert [c["kind"] for c in entry["timing"]["calls"]] == ["write", "repair", "write"] and not entry["warnings"]
        assert "Reply with the corrected program only." in calls[2][-1]["content"]

    async def test_a_runaway_reply_is_written_again(self, stub):
        _, replies = stub
        replies += ["```python\nx = 1\n" + "emit('and again')\n" * 5, f"```python\n{TRAIN_S}```"]
        entry = await self._ensure()
        assert entry["attempts"] == 2 and not entry["warnings"]

    async def test_list_and_exact_text_edits_patch_without_the_model(self, stub):
        calls, replies = stub
        replies.append(f"```python\n{TRAIN_S}```")
        first = await self._ensure()
        n = len(calls)
        lists = await self._ensure(PROMPT.replace("{rainy|foggy|bright}", "{rainy|foggy|bright|snowy}"))
        assert lists["patch"] == "lists" and lists["patched_from"] == first["key"] and len(calls) == n
        assert '["rainy", "foggy", "bright", "snowy"]' in lists["program"]
        exact = await self._ensure(PROMPT.replace("Portra 400", "Ektar 100").replace("{rainy|foggy|bright}", "{rainy|foggy|bright|snowy}"))
        assert exact["patch"] == "same" and exact["program"] == lists["program"] and len(calls) == n
        assert prep.realize(exact, seed=3).prompt.endswith("[Shot on Ektar 100]")

    async def test_a_small_text_edit_is_patched_with_one_call(self, stub):
        calls, replies = stub
        replies.append(f"```python\n{TRAIN_S}```")
        await self._ensure()
        n = len(calls)
        edited = PROMPT.replace("A woman waiting", "A man waiting")
        line = next(i for i, ln in enumerate(TRAIN_S.strip("\n").splitlines(), 1) if ln.startswith("emit("))
        replies.append(f'{line}: emit("A man waiting for a train on a", weather, "morning, wearing", clothing, ". [EXACT_1]")')
        entry = await self._ensure(edited)
        assert entry["patch"] == "text" and len(calls) == n + 1 and not entry["warnings"]
        note = calls[-1][-1]["content"]
        assert '"woman" became "man"' in note and "1: A man waiting" in note
        assert "A man waiting" in prep.realize(entry, seed=1).prompt

    async def test_the_patch_writer_can_say_this_is_a_different_prompt(self, stub):
        calls, replies = stub
        replies.append(f"```python\n{TRAIN_S}```")
        first = await self._ensure()
        n = len(calls)
        other = PROMPT.replace("A woman waiting for a train", "A man fishing off a pier")
        replies.append("START OVER")                 # the patch call
        replies.append(f"```python\n{TRAIN_S}```")  # then a fresh write
        entry = await self._ensure(other)
        assert len(calls) == n + 2 and "patched_from" not in entry
        assert "START OVER" in calls[n][-1]["content"]          # it was offered the way out
        assert entry["lineage"] == entry["key"] != first["key"]  # its own options, not the old prompt's
        assert "previous version" not in calls[n + 1][1]["content"]

    async def test_a_patch_that_still_says_what_was_removed_is_prepared_anew(self, stub):
        calls, replies = stub
        replies.append(f"```python\n{TRAIN_S}```")
        await self._ensure()
        edited = PROMPT.replace("A woman waiting", "A man waiting")
        # the patch only touches the seed, so "woman" is still written; the repair changes nothing
        replies += ['2: clothing = pick("clothing", about="his coat", seed=["a grey coat"], label="Clothing", phase=2, line=2)',
                    "No change needed.", f"```python\n{TRAIN_S.replace('A woman', 'A man')}```"]
        entry = await self._ensure(edited)
        assert "patch" not in entry and "A man waiting" in entry["program"]
        assert 'no longer says "woman"' in calls[2][-1]["content"]  # write, patch, repair, then anew

    async def test_try_different_choices_never_patches(self, stub):
        _, replies = stub
        replies.append(f"```python\n{TRAIN_S}```")
        await self._ensure()
        replies.append(f"```python\n{TRAIN_S}```")
        entry = await self._ensure(PROMPT.replace("{rainy|foggy|bright}", "{rainy|foggy}"), force=True)
        assert "patch" not in entry and entry["attempts"] == 1

    async def test_the_options_hook_hears_of_each_new_program(self, stub, monkeypatch):
        _, replies = stub
        heard = []
        monkeypatch.setattr(prep, "on_prepared", lambda entry, **kw: heard.append(entry["key"]))
        replies.append(f"```python\n{TRAIN_S}```")
        first = await self._ensure()
        await self._ensure()  # cached: nothing new
        patched = await self._ensure(PROMPT.replace("{rainy|foggy|bright}", "{rainy|bright}"))
        assert heard == [first["key"], patched["key"]]

    def test_the_placeholder_note_is_only_for_prompts_with_placeholders(self):
        assert not prep._needs_placeholder_note("A lifeguard sitting in a chair")
        assert prep._needs_placeholder_note("A {red|blue} car")
        assert prep._needs_placeholder_note("A sign that says [EXACT_1]")
        assert prep._needs_placeholder_note("A chef\n# vary her age")

    def test_edit_kinds(self):
        assert prep.edit_kind("a {red|blue} car", "a {red|blue|green} car") == "lists"
        assert prep.edit_kind("a woman in a red coat at night", "a man in a red coat at night") == "text"
        assert prep.edit_kind("a woman", "a dog on a skateboard in the city at dusk with fireworks") is None


class TestApplyRun:
    def test_adds_loras_params_and_record(self):
        from routes.generation import _apply_program_run
        updated = {"prompt": "x", "loras": [{"lora": "loras/user.safetensors", "weight": 1.0}]}
        record = {"key": "k", "loras": [{"path": "loras/cb.safetensors", "weight": 0.8}], "params": {"guidance": 12.0, "steps": 3.7}}
        _apply_program_run(updated, record, {"guidance": {"type": "number", "maximum": 10}, "steps": {"type": "integer"}})
        assert updated["loras"][1] == {"lora": "loras/cb.safetensors", "weight": 0.8}
        assert updated["guidance"] == 10 and updated["steps"] == 3
        assert updated["prompt_program"]["key"] == "k"


class TestDrawSeed:
    async def _run(self, image_seed, draw_seed=None):
        from routes.generation import _run_prompt_program
        opts = {"enabled": True, **({"draw_seed": draw_seed} if draw_seed is not None else {})}
        record, _ = await _run_prompt_program(PROMPT, {"seed": image_seed}, opts, ctx=ctx(SCHEMA), tool_id="t",
                                              prompt_options={}, project_id=None, profile_id="p")
        return record

    async def test_draws_are_independent_of_the_image_seed(self, stub):
        _, replies = stub
        replies.append(f"```python\n{TRAIN_M}```")
        same_image = [await self._run(42) for _ in range(12)]
        assert len({r["draw_seed"] for r in same_image}) > 1  # same image seed, fresh draws
        a, b = await self._run(1, draw_seed=7), await self._run(999, draw_seed=7)
        assert a["draw_seed"] == b["draw_seed"] == 7
        assert [d["value"] for d in a["draws"]] == [d["value"] for d in b["draws"]]


class TestSuggestOptions:
    ENTRY = {"prompt": "a woman in {{stylish tank top}}", "example": "a woman in a silk tank top", "elaborate": False,
             "choices": [{"id": "stylish_tank_top", "kind": "pick", "label": "Tank Top", "wildcard": "stylish tank top",
                          "options": ["a silk tank top", "a linen tank top"]},
                         {"id": "look", "kind": "lora", "label": "Look", "options": ["A"]}]}

    async def test_new_options_skip_existing_and_repeats(self, monkeypatch):
        calls = []

        async def fake_ask(messages, project_id):
            calls.append(messages)
            return '```json\n["a silk tank top", "a ribbed cotton tank", "A ribbed cotton tank", "a sheer mesh tank"]\n```'

        monkeypatch.setattr(prep, "_ask_model", fake_ask)
        out = await prep.suggest_options(self.ENTRY, "stylish_tank_top", ["a silk tank top", "a linen tank top"], 2, None)
        assert out == ["a ribbed cotton tank", "a sheer mesh tank"] and len(calls) == 1
        system, user = calls[0][0]["content"], calls[0][1]["content"]
        assert "exactly 2 new options" in system and "{{stylish tank top}}" in system and "a few words" in system
        assert "- a linen tank top" in user

    async def test_retries_once_when_short_and_parses_lines(self, monkeypatch):
        replies = ["- a ribbed cotton tank", "1. a sheer mesh tank\n2. a crochet halter"]

        async def fake_ask(messages, project_id):
            return replies.pop(0)

        monkeypatch.setattr(prep, "_ask_model", fake_ask)
        out = await prep.suggest_options(self.ENTRY, "stylish_tank_top", [], 3, None)
        assert out == ["a ribbed cotton tank", "a sheer mesh tank", "a crochet halter"]

    async def test_only_picks(self):
        with pytest.raises(ProgramError):
            await prep.suggest_options(self.ENTRY, "look", [], 3, None)


class TestRerollEdits:
    def test_removing_every_option_uses_the_added_ones(self):
        src = 'top = pick("top", ["a", "b"], label="Top")\nemit(top)\n'
        edits = {"top": {"remove": ["a", "b"], "add": ["c", "d"]}}
        got = {run(src, s, None, [], set(), None, edits).prompt.lower() for s in range(20)}
        assert got <= {"c", "d"} and got

    def test_removing_everything_with_nothing_added_keeps_the_program_options(self):
        src = 'top = pick("top", ["a", "b"], label="Top")\nemit(top)\n'
        assert run(src, 1, None, [], set(), None, {"top": {"remove": ["a", "b"]}}).prompt.lower() in {"a", "b"}


async def _protected(text, lang, pid, translate):
    """The real masking from prompt_pipeline around a fake translation call."""
    from prompt_pipeline import extract_verbatim, restore_verbatim
    masked, segs = extract_verbatim(text)
    return restore_verbatim(await translate(masked, lang, pid), segs)


class TestLoraChoices:
    def test_trigger_words_can_be_left_out_of_picked_loras(self):
        entry = {"program": 'hair = pick_lora("hairstyle", ["Curtain bangs", "Wolf cut"], label="Hairstyle")\nemit("a woman")\n',
                 "loras": [vars(lo) for lo in LORAS], "params": {}}
        with_t = {prep.realize(entry, seed=s).prompt.lower() for s in range(8)}
        without = {prep.realize(entry, seed=s, triggers=False).prompt.lower() for s in range(8)}
        assert any("cbangs" in p or "wolfcut" in p for p in with_t)
        assert not any("cbangs" in p or "wolfcut" in p for p in without)

    def test_notes_and_triggers_shape_what_the_model_is_told(self):
        from routes.generation import _shape_lora_context
        ctx = [{"name": "Wolf cut", "trigger_words": ["wolfcut"], "notes": "works best at 0.8"}]
        assert _shape_lora_context(ctx, True, True) == ctx
        assert _shape_lora_context(ctx, False, True)[0]["trigger_words"] == []
        assert _shape_lora_context(ctx, True, False)[0]["notes"] == ""
        assert _shape_lora_context([], False, False) == []

    async def test_notes_off_keeps_them_from_the_program_writer(self, stub, monkeypatch):
        calls, replies = stub

        async def noted(tool_id, items, profile_id):
            return list(LORAS), {"Wolf cut": "SECRET-NOTE"}

        monkeypatch.setattr(prep, "lora_candidates", noted)
        replies.append(f"```python\n{TRAIN_M}```")
        await prep.ensure_program(prompt=PROMPT, tool_id="t", ctx=ctx(SCHEMA), instructions="", lora_items=[],
                                  project_id=None, profile_id="p", lora_notes=False)
        assert "SECRET-NOTE" not in " ".join(m["content"] for c in calls for m in c)


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


class TestAcceptanceFakeWritesPrograms:
    """The acceptance sandbox's fake chat model must answer the program writer with a
    program, or every Tool View run on a fresh app is blocked."""

    def test_the_fake_reply_is_a_runnable_program(self):
        from llm import _acceptance_program
        from prompt_programs.runtime import check, extract_code
        msg = prep.build_user_message("acceptance test image\n# keep it simple", "m", "prose", {}, [], {})
        reply = _acceptance_program([{"role": "system", "content": prep._INSTRUCTIONS}, {"role": "user", "content": msg}])
        source = extract_code(reply)
        check(source)
        assert run(source, 1, None, [], set()).prompt.lower() == "acceptance test image"

    def test_user_lists_become_list_picks(self):
        from llm import _acceptance_program
        from prompt_programs.runtime import extract_code
        prompt = "a {red|blue} car on a {sunny|rainy} day"
        msg = prep.build_user_message(prompt, "m", "prose", {}, [], {})
        source = extract_code(_acceptance_program([{"role": "system", "content": prep._INSTRUCTIONS},
                                                   {"role": "user", "content": msg}]))
        checked = prep.validate(source, prompt, [], set())
        assert not checked["problems"]
        assert {run(source, s, None, [], set()).prompt.lower() for s in range(30)} >= {"a red car on a sunny day", "a blue car on a rainy day"}

    def test_other_requests_keep_the_dummy_reply(self):
        from llm import _acceptance_program
        assert _acceptance_program([{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "hi"}]) is None


def test_a_smart_wildcard_written_as_a_list_is_a_problem():
    src = ('season = pick("season", ["spring", "summer"], label="Season", source="list", phase=1, line=1)\n'
           'emit("A girl on a bicycle in", season)\n')
    problems = prep.validate(src, "A girl on a bicycle, {{season}}", [], set())["problems"]
    assert any('has source="list", but the user\'s prompt has no list {spring|summer}' in p
               and "{{season}} is a smart wildcard" in p for p in problems)
    src = ('e = pick("ethnicity", ["asian or euro ethnicity"], source="list", phase=1, line=1)\n'
           'hair = pick("hair", about=f"the hair of a {e} woman", seed=["dark hair"], phase=2, added=True)\n'
           'emit("A portrait of a young woman,", e, ",", hair)\n')
    problems = prep.validate(src, "Portrait of a young woman, {{asian or euro ethnicity}}", [], set())["problems"]
    assert any('pick("ethnicity") has source="list"' in p for p in problems)
    listed = 'season = pick("season", ["spring", "summer"], label="Season", phase=1, line=1)\nemit("A girl,", season)\n'
    assert any("{{season}} is a smart wildcard, not a list" in p
               for p in prep.validate(listed, "A girl, {{season}}", [], set())["problems"])
    ok = 'season = pick("season", about="the season", seed=["spring"], label="Season", phase=1, line=1)\nemit("A girl,", season)\n'
    assert not prep.validate(ok, "A girl, {{season}}", [], set())["problems"]
