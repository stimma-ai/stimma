"""LoRA names stay out of the prompt, short LoRA names resolve, one user list can fill
several places, and a prepare that runs too long stops (Fluent on canary, 2026-11-08)."""
import asyncio

import pytest

from prompt_programs import prepare as prep
from prompt_programs.draws import draw
from prompt_programs.runtime import LoraInfo, ProgramError, lora_names, run, _lora_key
from prompt_programs.store import ProgramStore

LORAS = [
    LoraInfo("KREA2 bodyshop flatchest v1", "k/flat.safetensors", 0.7, ""),
    LoraInfo("PornMaster Flat chest & Innie krea2 V1", "k/pm.safetensors", 0.8, ""),
    LoraInfo("KREA2 bodyshop torpedo v1", "k/torpedo.safetensors", 0.6, ""),
    LoraInfo("KREA2 bodyshop acups v1", "k/acups.safetensors", 0.6, "acupz"),
    LoraInfo("KREA2 bodyshop bcups v1", "k/bcups.safetensors", 0.6, ""),
]
BY_KEY = {_lora_key(lo.name): lo for lo in LORAS}


class TestLoraNames:
    def test_short_names_resolve_to_the_one_listed_name(self):
        assert lora_names(["flatchest", "torpedo", "KREA2 bodyshop acups v1"], BY_KEY) == [
            "KREA2 bodyshop flatchest v1", "KREA2 bodyshop torpedo v1", "KREA2 bodyshop acups v1"]

    def test_ambiguous_or_unknown_names_are_dropped(self):
        # "bodyshop" names four LoRAs; "ghostnipples" names none
        assert lora_names(["bodyshop", "ghostnipples", "bcups"], BY_KEY) == ["KREA2 bodyshop bcups v1"]

    def test_none_known_still_fails(self):
        with pytest.raises(ProgramError, match="none of"):
            run('b = pick_lora("b", ["ghostnipples"])\nemit("x")', 1, None, LORAS, set())

    def test_short_names_draw_and_turn_on_the_listed_lora(self):
        src = 'b = pick_lora("breasts", ["flatchest", "torpedo"], label="Breasts")\nemit("Two friends on a sofa.")\n'
        seen = set()
        for s in range(30):
            r = run(src, s, None, LORAS, set())
            seen.add(r.loras[0].name)
            assert r.loras[0].path in ("k/flat.safetensors", "k/torpedo.safetensors")
        assert seen == {"KREA2 bodyshop flatchest v1", "KREA2 bodyshop torpedo v1"}


SPARK_EMIT = '''b = pick_lora("breast_lora", ["KREA2 bodyshop acups v1", "KREA2 bodyshop torpedo v1"], label="Breasts", line=5)
emit("Two friends on a beige sofa, harsh flash.", "\\n", b)
'''


class TestLoraNameNeverEmitted:
    def test_emitting_the_pick_writes_nothing(self):
        for s in range(20):
            r = run(SPARK_EMIT, s, None, LORAS, set())
            assert "bodyshop" not in r.prompt.lower()
            assert r.prompt.startswith(("acupz, Two friends", "Two friends"))  # the trigger still goes in
            assert len(r.loras) == 1

    def test_the_value_still_compares_and_looks_up(self):
        src = ('b = pick_lora("b", ["acups", "torpedo"])\n'
               'words = {"KREA2 bodyshop acups v1": "small chest"}.get(b, "full chest")\n'
               'emit("A woman,", words)\n')
        got = {run(src, s, None, LORAS, set()).prompt for s in range(30)}
        assert {p.removeprefix("acupz, ") for p in got} == {"A woman, small chest", "A woman, full chest"}

    def test_draw_path_skips_it_too(self):
        src = ('b = pick_lora("b", ["acups", "torpedo"], phase=1)\n'
               'emit("Two friends on a beige sofa.", b)\n')
        for s in range(10):
            r = draw(src, s, None, LORAS, set())
            assert "bodyshop" not in r.prompt.lower() and r.loras

    def test_validate_flags_a_name_written_into_text(self):
        src = ('b = pick_lora("b", ["acups", "torpedo"], line=1)\n'
               'emit(f"Two friends, {b} style.")\n')
        problems = prep.validate(src, "two friends, pick a breast lora: acups or torpedo", LORAS, set())["problems"]
        assert any("LoRA names" in p for p in problems)


LIST_PROMPT = "Two friends wearing different colored {hot pink|jet black|teal} bodysuits on a sofa."
TWO_PICKS = '''c1 = pick("color1", ["hot pink", "jet black", "teal"], label="Color 1", line=1)
c2 = pick("color2", ["hot pink", "jet black", "teal"], label="Color 2", line=1)
emit("Two friends wearing different colored", c1, "and", c2, "leather bodysuits on a sofa.")
'''


class TestOneListSeveralPlaces:
    def test_marks_list_and_excludes_earlier(self):
        fixed, notes = prep.fix_list_sources(TWO_PICKS, LIST_PROMPT)
        assert fixed.count('source="list"') == 2
        assert 'exclude=[c1]' in fixed and notes
        for s in range(40):
            r = run(fixed, s, None, [], set())
            vals = {d.id: d.value for d in r.draws}
            assert vals["color1"] != vals["color2"]

    def test_validates_without_the_user_list_complaint(self):
        fixed, _ = prep.fix_list_sources(TWO_PICKS, LIST_PROMPT)
        problems = prep.validate(fixed, LIST_PROMPT, [], set())["problems"]
        assert not any("user list" in p or "more than once" in p for p in problems), problems

    def test_works_on_the_draws_path_after_phases_are_fixed(self):
        src = TWO_PICKS.replace('line=1)', 'phase=1, line=1)')
        fixed, _ = prep.fix_list_sources(src, LIST_PROMPT)
        fixed, _ = prep.fix_phases(fixed)
        for s in range(20):
            r = draw(fixed, s, None, [], set())
            vals = {d.id: d.value for d in r.draws}
            assert vals["color1"] != vals["color2"]

    def test_leaves_other_picks_and_existing_sources_alone(self):
        src = ('c = pick("color", ["hot pink", "jet black", "teal"], source="list", line=1)\n'
               'h = pick("hair", ["a bob", "braids"], label="Hair")\n'
               'emit("A friend in", c, "with", h)\n')
        assert prep.fix_list_sources(src, LIST_PROMPT) == (src, [])

    def test_no_exclude_when_the_list_is_too_short(self):
        src = ('a = pick("a", ["x", "y"], line=1)\nb = pick("b", ["x", "y"], line=1)\nc = pick("c", ["x", "y"], line=1)\n'
               'emit(a, b, c)\n')
        fixed, _ = prep.fix_list_sources(src, "{x|y}")
        assert "exclude=[a]" in fixed and "exclude=[a, b]" not in fixed


@pytest.fixture
def slow_model(monkeypatch, tmp_path):
    async def fake_candidates(tool_id, items, profile_id):
        return [], {}

    async def fake_upsample(*a, **kw):
        return "A woman waiting for a train on a [{rainy|foggy}] morning."

    monkeypatch.setattr(prep, "upsample", fake_upsample)
    monkeypatch.setattr(prep, "lora_candidates", fake_candidates)
    monkeypatch.setattr(prep, "_store", lambda profile_id: ProgramStore(tmp_path))
    monkeypatch.setattr("prompt_pipeline._profile_wildcards_and_segments", lambda profile_id: ([], []))


def _ensure():
    return prep.ensure_program(prompt="A woman waiting for a train on a {rainy|foggy} morning.", tool_id="t",
                               ctx={"model": "m", "mode": "prose", "schema_props": {}, "enhance": {}},
                               instructions="", lora_items=[], project_id=None, profile_id="p")


class TestPrepareLimit:
    async def test_a_stuck_model_stops_at_the_limit(self, slow_model, monkeypatch):
        monkeypatch.setattr(prep, "PREPARE_LIMIT_SECONDS", 0.2)

        async def stuck(messages, project_id, max_tokens=4096):
            await asyncio.sleep(30)

        monkeypatch.setattr(prep, "_ask_model", stuck)
        with pytest.raises(prep.PrepareTimeout):
            await asyncio.wait_for(_ensure(), 5)
        assert not prep._in_flight  # the next run asks again rather than waiting on a dead prepare

    async def test_past_the_soft_budget_it_keeps_what_it_has(self, slow_model, monkeypatch):
        monkeypatch.setattr(prep, "PREPARE_SOFT_SECONDS", 0.0)
        calls = []
        # valid but with a fixable complaint (the label is too long), so it would otherwise repair
        program = ('w = pick("weather", ["rainy", "foggy"], source="list", label="The weather this morning", line=1)\n'
                   'emit("A woman waiting for a train on a", w, "morning.")\n')

        async def ask(messages, project_id, max_tokens=4096):
            calls.append(1)
            return f"```python\n{program}```"

        monkeypatch.setattr(prep, "_ask_model", ask)
        entry = await _ensure()
        assert len(calls) == 1 and entry["attempts"] == 1


class TestListReviewFixes:
    def test_the_same_list_written_twice_draws_freely(self):
        prompt = "A {red|blue} car next to a {red|blue} bicycle."
        src = ('a = pick("car", ["red", "blue"], line=1)\nb = pick("bike", ["red", "blue"], line=1)\n'
               'emit("A", a, "car next to a", b, "bicycle.")\n')
        fixed, _ = prep.fix_list_sources(src, prompt)
        assert fixed.count('source="list"') == 2 and "exclude" not in fixed
        pairs = {tuple(d.value for d in run(fixed, s, None, [], set()).draws) for s in range(40)}
        assert ("red", "red") in pairs and ("blue", "blue") in pairs

    def test_multiline_call_with_trailing_comment(self):
        src = ('c1 = pick("color1", ["hot pink", "jet black", "teal"],\n'
               '         label="Color 1", line=1)\n'
               'c2 = pick(\n    "color2",\n    ["hot pink", "jet black", "teal"],\n    line=1,  # the second friend\n)\n'
               'emit("Two friends in", c1, "and", c2, "bodysuits.")\n')
        fixed, _ = prep.fix_list_sources(src, LIST_PROMPT)
        import ast as _ast
        _ast.parse(fixed)
        assert 'exclude=[c1]' in fixed and fixed.count('source="list"') == 2

    def test_patching_a_shared_list_updates_every_pick(self):
        fixed, _ = prep.fix_list_sources(TWO_PICKS, LIST_PROMPT)
        new_prompt = LIST_PROMPT.replace("teal", "mint")
        patched = prep.patch_lists(fixed, LIST_PROMPT, new_prompt)
        assert patched is not None and patched.count('"mint"') == 2 and '"teal"' not in patched

    def test_patching_one_of_two_identical_lists_is_ambiguous(self):
        old = "A {red|blue} car next to a {red|blue} bicycle."
        src = ('a = pick("car", ["red", "blue"], source="list", line=1)\n'
               'b = pick("bike", ["red", "blue"], source="list", line=1)\nemit("A", a, "car next to a", b, "bicycle.")\n')
        assert prep.patch_lists(src, old, "A {red|green} car next to a {red|blue} bicycle.") is None

    def test_a_list_written_twice_never_gains_exclusions(self):
        prompt = "Two friends in different {red|blue|green} coats beside a {red|blue|green} car."
        src = ('a = pick("coat1", ["red", "blue", "green"], line=1)\nb = pick("coat2", ["red", "blue", "green"], line=1)\n'
               'c = pick("car", ["red", "blue", "green"], line=1)\nemit("Two friends in", a, "and", b, "coats beside a", c, "car.")\n')
        fixed, _ = prep.fix_list_sources(src, prompt)
        assert "exclude" not in fixed and fixed.count('source="list"') == 3

    def test_patch_counts_lists_the_way_it_matches_them(self):
        old = "A {red|blue} car next to a {red | blue} bicycle."
        src = ('a = pick("car", ["red", "blue"], source="list", line=1)\n'
               'b = pick("bike", ["red", "blue"], source="list", line=1)\nemit("A", a, "car next to a", b, "bicycle.")\n')
        assert prep.patch_lists(src, old, "A {red|blue|green} car next to a {red | blue} bicycle.") is None


class TestPromptOwnsItsLoras:
    def test_only_the_picked_one_of_the_prompts_loras_runs(self):
        from routes.generation import _apply_program_run
        updated = {"prompt": "x", "loras": [
            {"lora": "k/flat.safetensors", "weight": 0.7},      # on in the panel, one the prompt chooses among
            {"lora": "k/phone.safetensors", "weight": 1.0},     # on in the panel, not the prompt's
        ]}
        record = {"key": "k", "loras": [{"path": "k/torpedo.safetensors", "weight": 0.6}],
                  "lora_controlled": ["k/flat.safetensors", "k/torpedo.safetensors", "k/acups.safetensors"]}
        _apply_program_run(updated, record, {})
        assert [x["lora"] for x in updated["loras"]] == ["k/phone.safetensors", "k/torpedo.safetensors"]

    def test_a_picked_lora_already_on_stays_once(self):
        from routes.generation import _apply_program_run
        updated = {"prompt": "x", "loras": [{"lora": "k/flat.safetensors", "weight": 0.7}]}
        record = {"key": "k", "loras": [{"path": "k/flat.safetensors", "weight": 0.7}], "lora_controlled": ["k/flat.safetensors"]}
        _apply_program_run(updated, record, {})
        assert [x["lora"] for x in updated["loras"]] == ["k/flat.safetensors"]

    def test_records_without_the_list_keep_the_old_behaviour(self):
        from routes.generation import _apply_program_run
        updated = {"prompt": "x", "loras": [{"lora": "k/flat.safetensors", "weight": 0.7}]}
        _apply_program_run(updated, {"key": "k", "loras": [{"path": "k/torpedo.safetensors", "weight": 0.6}]}, {})
        assert [x["lora"] for x in updated["loras"]] == ["k/flat.safetensors", "k/torpedo.safetensors"]


class TestOneLoraPickPerSet:
    PROMPT = "Two friends on a sofa. Pick a breast lora per photo: acups, torpedo, bcups."

    def test_two_picks_from_the_same_set_are_sent_back(self):
        src = ('a = pick_lora("g1_lora", ["acups", "torpedo", "bcups"], line=1)\n'
               'b = pick_lora("g2_lora", ["acups", "torpedo", "bcups"], line=1)\n'
               'emit("Two friends on a sofa.")\n')
        problems = prep.validate(src, self.PROMPT, LORAS, set())["problems"]
        assert any("same LoRAs" in p for p in problems)

    def test_text_that_names_the_loras_is_sent_back(self):
        src = ('b = pick_lora("breasts", ["acups", "torpedo", "bcups"], line=1)\n'
               't = pick("breast_type", ["acups", "torpedo", "bcups"], label="Breasts", line=1)\n'
               'emit("Two friends on a sofa, her", t, "breasts.")\n')
        problems = prep.validate(src, self.PROMPT, LORAS, set())["problems"]
        assert any("names the same things" in p for p in problems)

    def test_one_pick_and_plain_text_pass_those_checks(self):
        src = ('b = pick_lora("breasts", ["acups", "torpedo", "bcups"], line=1)\n'
               'emit("Two friends on a sofa.")\n')
        problems = prep.validate(src, self.PROMPT, LORAS, set())["problems"]
        assert not any("same LoRAs" in p or "names the same things" in p for p in problems)

    def test_an_unrelated_pick_sharing_words_is_left_alone(self):
        hair = [LoraInfo("Long hair", "h/long.safetensors", 1.0, ""), LoraInfo("Short hair", "h/short.safetensors", 1.0, "")]
        src = ('h = pick_lora("hair", ["Long hair", "Short hair"], line=1)\n'
               's = pick("skirt_length", ["long", "short"], label="Skirt", line=1)\n'
               'emit("A woman in a", s, "skirt.")\n')
        problems = prep.validate(src, "A woman in a {long|short} skirt, pick a hair lora", hair, set())["problems"]
        assert not any("names the same things" in p for p in problems)

    def test_picks_in_separate_branches_dont_stack(self):
        src = ('mood = pick("mood", ["calm", "wild"], source="list", line=1)\n'
               'if mood == "calm":\n    a = pick_lora("calm_lora", ["acups", "torpedo"], line=1)\n'
               'else:\n    b = pick_lora("wild_lora", ["acups", "bcups"], line=1)\n'
               'emit("A", mood, "portrait.")\n')
        problems = prep.validate(src, "A {calm|wild} portrait, pick a lora", LORAS, set())["problems"]
        assert not any("same LoRAs" in p for p in problems)


class TestSubjectsGroup:
    def test_hand_written_people_group_by_label(self):
        from prompt_programs.runtime import discover
        src = ('a = pick("g1_hair", ["a bob", "braids"], label="Girl 1 Hair")\n'
               'b = pick("g1_eyes", ["green eyes", "brown eyes"], label="Girl 1 Eyes")\n'
               'c = pick("g2_hair", ["a bob", "braids"], label="Girl 2 Hair")\n'
               'd = pick("g2_eyes", ["green eyes", "brown eyes"], label="Girl 2 Eyes")\n'
               'e = pick("color1", ["red", "blue"], label="Color 1")\n'
               'emit("One with", a, b, "and one with", c, d, e)\n')
        info = discover(src, [], set(), runs=4)
        by = {c["id"]: c for c in info["choices"]}
        assert by["g2_eyes"]["group"] == "girl" and by["g2_eyes"]["index"] == 2 and by["g2_eyes"]["label"] == "Eyes"
        assert "group" not in by["color1"]
        assert info["groups"] == [{"id": "girl", "count": 2, "label": "Girl", "source": "text", "line": None}]

    def test_bracket_ids_without_group_call_get_a_group(self):
        from prompt_programs.runtime import discover
        src = ('a = pick("girl[1].hair", ["a bob", "braids"], label="Hair")\n'
               'b = pick("girl[2].hair", ["a bob", "braids"], label="Hair")\n'
               'emit(a, b)\n')
        info = discover(src, [], set(), runs=4)
        assert info["groups"][0]["id"] == "girl" and info["groups"][0]["count"] == 2

    def test_one_person_is_not_a_group(self):
        from prompt_programs.runtime import discover
        src = 'a = pick("p_hair", ["a bob", "braids"], label="Person 1 Hair")\nemit(a)\n'
        info = discover(src, [], set(), runs=4)
        assert not info["groups"] and "group" not in info["choices"][0]


class TestConditionalStacking:
    def test_a_sometimes_second_pick_is_caught(self):
        src = ('mood = pick("mood", ["calm", "wild", "sad", "happy", "bored"], source="list", line=1)\n'
               'a = pick_lora("main", ["acups", "torpedo"], line=1)\n'
               'if mood == "calm":\n    b = pick_lora("extra", ["acups", "bcups"], line=1)\n'
               'emit("A", mood, "portrait.")\n')
        problems = prep.validate(src, "A {calm|wild|sad|happy|bored} portrait, pick a lora", LORAS, set())["problems"]
        assert any("same LoRAs" in p for p in problems)


class TestSubjectCells:
    def test_alternatives_for_one_cell_stay_flat(self):
        from prompt_programs.runtime import discover
        src = ('w = pick("weather", ["cold", "hot"], source="list", line=1)\n'
               'a = pick("g1_hair", ["a bob", "braids"], label="Girl 1 Hair")\n'
               'if w == "cold":\n    b = pick("g2_hair_cold", ["a beanie", "a hood"], label="Girl 2 Hair")\n'
               'else:\n    b = pick("g2_hair_hot", ["a ponytail", "a bun"], label="Girl 2 Hair")\n'
               'emit(w, a, b)\n')
        info = discover(src, [], set(), runs=24)
        assert not info["groups"] and all("group" not in c for c in info["choices"])


class TestLorasShownToTheModels:
    def test_writer_sees_choosable_loras_with_their_words_and_notes_spelled_out(self):
        loras = [LoraInfo("KREA2 bodyshop acups v1", "k/a", 0.6, ""), LoraInfo("Wolf cut", "k/w", 0.9, "wolfcut")]
        msg = prep.build_user_message("pick a lora", "A woman.", "m", "prose", {}, loras, {"Wolf cut": "short layered hair"})
        assert '- "KREA2 bodyshop acups v1" (trigger words: none; notes: none)' in msg
        assert '- "Wolf cut" (trigger words: "wolfcut"; notes: short layered hair)' in msg
        assert "never in emit()" in msg

    def test_enhancer_guidance_lists_only_loras_with_something_to_say(self):
        from routes.prompt_enhancement import _lora_guidance
        assert _lora_guidance([{"name": "ultra real krea2", "trigger_words": [], "notes": ""}]) == ""
        g = _lora_guidance([{"name": "ultra real krea2", "trigger_words": [], "notes": ""},
                            {"name": "Wolf cut", "trigger_words": ["wolfcut"], "notes": ""}])
        assert "ultra real krea2" not in g and '"wolfcut"' in g and "never write a LoRA's name" in g

    def test_names_the_enhancer_slipped_in_are_cut(self):
        loras = [LoraInfo("ultra real krea2", "k/u"), LoraInfo("KNP 000003000", "k/k"), LoraInfo("facial krea", "k/f")]
        text = "A woman in a kitchen, ultra real krea2, KNP 000003000, facial krea, harsh flash."
        assert prep.drop_lora_names(text, loras, "a woman, pick a lora") == "A woman in a kitchen, harsh flash."

    def test_validate_flags_any_listed_lora_name_in_the_text(self):
        loras = LORAS + [LoraInfo("ultra real krea2", "k/u")]
        src = 'emit("A woman in a kitchen, ultra real krea2, harsh flash.")\n'
        problems = prep.validate(src, "a woman in a kitchen, pick a lora", loras, set())["problems"]
        assert any("LoRA names" in p for p in problems)

    async def test_enhancer_only_hears_about_loras_that_are_on_and_have_words_or_notes(self, monkeypatch, tmp_path):
        seen = {}

        async def fake_upsample(prompt, ctx, instructions, lora_context, project_id, profile_id):
            seen["ctx"] = lora_context
            return "A woman in a kitchen, ultra real krea2."

        async def fake_candidates(tool_id, items, profile_id):
            return [LoraInfo("ultra real krea2", "k/u", 0.8, "", on=True),
                    LoraInfo("Wolf cut", "k/w", 0.9, "wolfcut", on=True),
                    LoraInfo("KREA2 bodyshop acups v1", "k/a", 0.6, "", on=False)], {}

        async def ask(messages, project_id, max_tokens=4096):
            seen["writer"] = messages[1]["content"]
            return '```python\nemit("A woman in a kitchen.")\n```'

        monkeypatch.setattr(prep, "upsample", fake_upsample)
        monkeypatch.setattr(prep, "lora_candidates", fake_candidates)
        monkeypatch.setattr(prep, "_ask_model", ask)
        monkeypatch.setattr(prep, "_store", lambda profile_id: ProgramStore(tmp_path))
        monkeypatch.setattr("prompt_pipeline._profile_wildcards_and_segments", lambda profile_id: ([], []))
        await prep.ensure_program(prompt="A woman in a kitchen. # pick a lora", tool_id="t",
                                  ctx={"model": "m", "mode": "prose", "schema_props": {}, "enhance": {}},
                                  instructions="", lora_items=[], project_id=None, profile_id="p")
        assert [c["name"] for c in seen["ctx"]] == ["Wolf cut"]
        assert "ultra real krea2" not in seen["writer"].split("(End of the enhanced prompt.)")[0]
