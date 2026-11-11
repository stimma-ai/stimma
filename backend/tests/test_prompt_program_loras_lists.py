"""LoRA names stay out of the prompt, short LoRA names resolve, one user list can fill
several places, and a prepare that runs too long stops (Fluent on canary, 2026-11-08)."""
import asyncio

import pytest

from prompt_programs import prepare as prep
from prompt_programs.draws import draw
from prompt_programs.runtime import LoraInfo, ProgramError, lora_names, run, _lora_key
from prompt_programs.store import ProgramStore


async def fake_style(*a, **kw):
    return "STYLE GUIDE: write rich prose.", []

LORAS = [
    LoraInfo("KREA2 hairshop bobcut v1", "k/bobcut.safetensors", 0.7, ""),
    LoraInfo("StyleMaster Bob cut & Fringe krea2 V1", "k/sm.safetensors", 0.8, ""),
    LoraInfo("KREA2 hairshop pixie v1", "k/pixie.safetensors", 0.6, ""),
    LoraInfo("KREA2 hairshop curly v1", "k/curly.safetensors", 0.6, "curlz"),
    LoraInfo("KREA2 hairshop braids v1", "k/braids.safetensors", 0.6, ""),
]
BY_KEY = {_lora_key(lo.name): lo for lo in LORAS}


class TestLoraNames:
    def test_short_names_resolve_to_the_one_listed_name(self):
        assert lora_names(["bobcut", "pixie", "KREA2 hairshop curly v1"], BY_KEY) == [
            "KREA2 hairshop bobcut v1", "KREA2 hairshop pixie v1", "KREA2 hairshop curly v1"]

    def test_ambiguous_or_unknown_names_are_dropped(self):
        # "hairshop" names four LoRAs; "mohawk" names none
        assert lora_names(["hairshop", "mohawk", "braids"], BY_KEY) == ["KREA2 hairshop braids v1"]

    def test_none_known_still_fails(self):
        with pytest.raises(ProgramError, match="none of"):
            run('b = pick_lora("b", ["mohawk"])\nemit("x")', 1, None, LORAS, set())

    def test_short_names_draw_and_turn_on_the_listed_lora(self):
        src = 'b = pick_lora("hair", ["bobcut", "pixie"], label="Hair")\nemit("Two friends on a sofa.")\n'
        seen = set()
        for s in range(30):
            r = run(src, s, None, LORAS, set())
            seen.add(r.loras[0].name)
            assert r.loras[0].path in ("k/bobcut.safetensors", "k/pixie.safetensors")
        assert seen == {"KREA2 hairshop bobcut v1", "KREA2 hairshop pixie v1"}


SPARK_EMIT = '''b = pick_lora("hair_lora", ["KREA2 hairshop curly v1", "KREA2 hairshop pixie v1"], label="Hair", line=5)
emit("Two friends on a beige sofa, harsh flash.", "\\n", b)
'''


class TestLoraNameNeverEmitted:
    def test_emitting_the_pick_writes_nothing(self):
        for s in range(20):
            r = run(SPARK_EMIT, s, None, LORAS, set())
            assert "hairshop" not in r.prompt.lower()
            assert r.prompt.startswith(("curlz, Two friends", "Two friends"))  # the trigger still goes in
            assert len(r.loras) == 1

    def test_the_value_still_compares_and_looks_up(self):
        src = ('b = pick_lora("b", ["curly", "pixie"])\n'
               'words = {"KREA2 hairshop curly v1": "curly hair"}.get(b, "straight hair")\n'
               'emit("A woman,", words)\n')
        got = {run(src, s, None, LORAS, set()).prompt for s in range(30)}
        assert {p.removeprefix("curlz, ") for p in got} == {"A woman, curly hair", "A woman, straight hair"}

    def test_draw_path_skips_it_too(self):
        src = ('b = pick_lora("b", ["curly", "pixie"], phase=1)\n'
               'emit("Two friends on a beige sofa.", b)\n')
        for s in range(10):
            r = draw(src, s, None, LORAS, set())
            assert "hairshop" not in r.prompt.lower() and r.loras

    def test_validate_flags_a_name_written_into_text(self):
        src = ('b = pick_lora("b", ["curly", "pixie"], line=1)\n'
               'emit(f"Two friends, {b} style.")\n')
        problems = prep.validate(src, "two friends, pick a hair lora: curly or pixie", LORAS, set())["problems"]
        assert any("the value pick_lora() returns is the LoRA's name" in p for p in problems)


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



async def text_endpoint(project_id):
    """A writer endpoint without tool calls: the text protocol."""
    return None, "text"


@pytest.fixture
def slow_model(monkeypatch, tmp_path):
    async def fake_candidates(tool_id, items, profile_id):
        return [], {}

    monkeypatch.setattr(prep, "writer_style", fake_style)
    monkeypatch.setattr(prep, "lora_candidates", fake_candidates)
    monkeypatch.setattr(prep, "_store", lambda profile_id: ProgramStore(tmp_path))
    monkeypatch.setattr(prep, "_writer_endpoint", text_endpoint)  # these fake the text protocol's _ask_model
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


class TestTextProtocolDeadline:
    """Each text-protocol call gets only what's left of the prepare's deadline; a stall
    keeps the best program so far (as the session does)."""
    UNLISTED = 'emit("A woman waiting for a train on a rainy morning.")\n'  # the user's list isn't a pick
    # a pick that never reaches the text: it costs variety, not the user's words, so it runs
    UNUSED = ('w = pick("weather", ["rainy", "foggy"], source="list", label="Weather", phase=1, line=1)\n'
              'x = pick("light", ["soft light", "harsh light"], label="Light", phase=1, line=1)\n'
              'emit("A woman waiting for a train on a", w, "morning.")\n')

    async def test_a_stalled_repair_keeps_the_candidate(self, slow_model, monkeypatch):
        monkeypatch.setattr(prep, "PREPARE_LIMIT_SECONDS", 0.5)
        replies = [f"```python\n{self.UNUSED}```"]

        async def ask(messages, project_id, max_tokens=4096):
            if replies:
                return replies.pop(0)
            await asyncio.sleep(30)  # the repair stalls

        monkeypatch.setattr(prep, "_ask_model", ask)
        entry = await asyncio.wait_for(_ensure(), 5)
        assert entry["program"] == self.UNUSED and entry["attempts"] == 1
        assert entry["partial"] and any("never appears" in p for p in entry["problems"])

    async def test_a_stalled_repair_of_a_program_that_loses_the_users_list_fails(self, slow_model, monkeypatch):
        monkeypatch.setattr(prep, "PREPARE_LIMIT_SECONDS", 0.5)
        replies = [f"```python\n{self.UNLISTED}```"]

        async def ask(messages, project_id, max_tokens=4096):
            if replies:
                return replies.pop(0)
            await asyncio.sleep(30)

        monkeypatch.setattr(prep, "_ask_model", ask)
        with pytest.raises(prep.PrepareFailed) as e:
            await asyncio.wait_for(_ensure(), 5)
        assert "user list" in e.value.problems

    async def test_a_check_that_trips_is_a_problem_not_a_crash(self, slow_model, monkeypatch):
        good = ('w = pick("weather", ["rainy", "foggy"], source="list", label="Weather", line=1)\n'
                'emit("A woman waiting for a train on a", w, "morning.")\n')
        replies = [f"```python\n{good}```"] * 3
        real, tripped = prep.validate, []

        def validate(*a, **kw):
            if not tripped:
                tripped.append(1)
                raise KeyError("label")
            return real(*a, **kw)

        async def ask(messages, project_id, max_tokens=4096):
            return replies.pop(0)

        monkeypatch.setattr(prep, "validate", validate)
        monkeypatch.setattr(prep, "_ask_model", ask)
        entry = await _ensure()
        assert entry["program"] == good and tripped

    async def test_validation_runs_off_the_event_loop(self, slow_model, monkeypatch):
        import threading
        good = ('w = pick("weather", ["rainy", "foggy"], source="list", label="Weather", line=1)\n'
                'emit("A woman waiting for a train on a", w, "morning.")\n')
        real, threads = prep.validate, []

        def validate(*a, **kw):
            threads.append(threading.current_thread())
            return real(*a, **kw)

        async def ask(messages, project_id, max_tokens=4096):
            return f"```python\n{good}```"

        monkeypatch.setattr(prep, "validate", validate)
        monkeypatch.setattr(prep, "_ask_model", ask)
        loop_thread = threading.current_thread()
        entry = await _ensure()
        assert entry["program"] == good and threads and loop_thread not in threads

    async def test_the_fallback_counts_time_from_the_start_of_the_prepare(self, slow_model, monkeypatch):
        import time
        monkeypatch.setattr(prep, "PREPARE_LIMIT_SECONDS", 1.0)

        async def ask(messages, project_id, max_tokens=4096):
            await asyncio.sleep(30)

        monkeypatch.setattr(prep, "_ask_model", ask)
        # a session that took most of the deadline before finding the endpoint makes no tool calls
        with pytest.raises(prep.PrepareTimeout):
            await asyncio.wait_for(prep._prepare_new(
                key="k", store=None, tool_id="t", ctx={"model": "m", "mode": "prose", "enhance": {}}, instructions="",
                source_prompt="A cat.", params={}, loras=[], notes={}, lora_context=[], project_id=None,
                profile_id="p", level="off", started=time.monotonic() - 0.9), 0.5)


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
            {"lora": "k/bobcut.safetensors", "weight": 0.7},      # on in the panel, one the prompt chooses among
            {"lora": "k/phone.safetensors", "weight": 1.0},     # on in the panel, not the prompt's
        ]}
        record = {"key": "k", "loras": [{"path": "k/pixie.safetensors", "weight": 0.6}],
                  "lora_controlled": ["k/bobcut.safetensors", "k/pixie.safetensors", "k/curly.safetensors"]}
        _apply_program_run(updated, record, {})
        assert [x["lora"] for x in updated["loras"]] == ["k/phone.safetensors", "k/pixie.safetensors"]

    def test_a_picked_lora_already_on_stays_once(self):
        from routes.generation import _apply_program_run
        updated = {"prompt": "x", "loras": [{"lora": "k/bobcut.safetensors", "weight": 0.7}]}
        record = {"key": "k", "loras": [{"path": "k/bobcut.safetensors", "weight": 0.7}], "lora_controlled": ["k/bobcut.safetensors"]}
        _apply_program_run(updated, record, {})
        assert [x["lora"] for x in updated["loras"]] == ["k/bobcut.safetensors"]

    def test_records_without_the_list_keep_the_old_behavior(self):
        from routes.generation import _apply_program_run
        updated = {"prompt": "x", "loras": [{"lora": "k/bobcut.safetensors", "weight": 0.7}]}
        _apply_program_run(updated, {"key": "k", "loras": [{"path": "k/pixie.safetensors", "weight": 0.6}]}, {})
        assert [x["lora"] for x in updated["loras"]] == ["k/bobcut.safetensors", "k/pixie.safetensors"]


class TestOneLoraPickPerSet:
    PROMPT = "Two friends on a sofa. Pick a hair lora per photo: curly, pixie, braids."

    def test_two_picks_from_the_same_set_are_sent_back(self):
        src = ('a = pick_lora("g1_lora", ["curly", "pixie", "braids"], line=1)\n'
               'b = pick_lora("g2_lora", ["curly", "pixie", "braids"], line=1)\n'
               'emit("Two friends on a sofa.")\n')
        problems = prep.validate(src, self.PROMPT, LORAS, set())["problems"]
        assert any("same LoRAs" in p for p in problems)

    def test_text_that_names_the_loras_is_sent_back(self):
        src = ('b = pick_lora("hair", ["curly", "pixie", "braids"], line=1)\n'
               't = pick("hair_type", ["KREA2 hairshop curly v1", "KREA2 hairshop pixie v1"], label="Hair", line=1)\n'
               'emit("Two friends on a sofa, her", t, "hair.")\n')
        problems = prep.validate(src, self.PROMPT, LORAS, set())["notes"]
        assert any("names the same things" in p for p in problems)

    def test_a_pick_that_shares_words_with_the_loras_is_not_their_names(self):
        # exact names only: "curly" is a word of "KREA2 hairshop curly v1", not its name
        src = ('b = pick_lora("hair", ["curly", "pixie", "braids"], line=1)\n'
               't = pick("hair_type", ["curly", "pixie", "braids"], label="Hair", line=1)\n'
               'emit("Two friends on a sofa, her", t, "hair.")\n')
        notes = prep.validate(src, self.PROMPT, LORAS, set())["notes"]
        assert not any("names the same things" in p for p in notes)

    def test_one_pick_and_plain_text_pass_those_checks(self):
        src = ('b = pick_lora("hair", ["curly", "pixie", "braids"], line=1)\n'
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
               'if mood == "calm":\n    a = pick_lora("calm_lora", ["curly", "pixie"], line=1)\n'
               'else:\n    b = pick_lora("wild_lora", ["curly", "braids"], line=1)\n'
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
               'a = pick_lora("main", ["curly", "pixie"], line=1)\n'
               'if mood == "calm":\n    b = pick_lora("extra", ["curly", "braids"], line=1)\n'
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
        loras = [LoraInfo("KREA2 hairshop curly v1", "k/a", 0.6, ""), LoraInfo("Wolf cut", "k/w", 0.9, "wolfcut")]
        msg = prep.build_user_message("pick a lora", "m", "prose", {}, loras, {"Wolf cut": "short layered hair"})
        assert '- "KREA2 hairshop curly v1" (trigger words: none; notes: none)' in msg
        assert '- "Wolf cut" (trigger words: "wolfcut"; notes: short layered hair)' in msg
        assert "never in emit()" in msg

    def test_enhancer_guidance_lists_only_loras_with_something_to_say(self):
        from routes.prompt_enhancement import _lora_guidance
        assert _lora_guidance([{"name": "ultra real krea2", "trigger_words": [], "notes": ""}]) == ""
        g = _lora_guidance([{"name": "ultra real krea2", "trigger_words": [], "notes": ""},
                            {"name": "Wolf cut", "trigger_words": ["wolfcut"], "notes": ""}])
        assert "ultra real krea2" not in g and '"wolfcut"' in g and "never write a LoRA's name" in g

    def test_validate_flags_any_listed_lora_name_in_the_text(self):
        loras = LORAS + [LoraInfo("ultra real krea2", "k/u")]
        src = 'emit("A woman in a kitchen, ultra real krea2, harsh flash.")\n'
        problems = prep.validate(src, "a woman in a kitchen, pick a lora", loras, set())["problems"]
        assert any("LoRA names" in p for p in problems)

    async def test_style_guide_hears_only_about_loras_that_are_on_and_have_words_or_notes(self, monkeypatch, tmp_path):
        seen = {}

        async def style(prompt, ctx, instructions, lora_context, project_id, profile_id, level="expand"):
            seen["ctx"] = lora_context
            return "STYLE GUIDE", []

        async def fake_candidates(tool_id, items, profile_id):
            return [LoraInfo("ultra real krea2", "k/u", 0.8, "", on=True),
                    LoraInfo("Wolf cut", "k/w", 0.9, "wolfcut", on=True),
                    LoraInfo("KREA2 hairshop curly v1", "k/a", 0.6, "", on=False)], {}

        async def ask(messages, project_id, max_tokens=4096):
            return '```python\nemit("A woman in a kitchen.")\n```'

        monkeypatch.setattr(prep, "writer_style", style)
        monkeypatch.setattr(prep, "lora_candidates", fake_candidates)
        monkeypatch.setattr(prep, "_ask_model", ask)
        monkeypatch.setattr(prep, "_writer_endpoint", text_endpoint)  # fakes the text protocol's _ask_model
        monkeypatch.setattr(prep, "_store", lambda profile_id: ProgramStore(tmp_path))
        monkeypatch.setattr("prompt_pipeline._profile_wildcards_and_segments", lambda profile_id: ([], []))
        await prep.ensure_program(prompt="A woman in a kitchen. # pick a lora", tool_id="t",
                                  ctx={"model": "m", "mode": "prose", "schema_props": {}, "enhance": {}},
                                  instructions="", lora_items=[], project_id=None, profile_id="p")
        assert [c["name"] for c in seen["ctx"]] == ["Wolf cut"]


class TestLoraNamesInText:
    def flagged(self, text, prompt="a woman, pick a lora"):
        loras = [LoraInfo("Dress", "k/d"), LoraInfo("Curtain bangs", "k/c"), LoraInfo("studio krea", "k/f"),
                 LoraInfo("XYZ 000003000", "k/k")]
        src = f'emit("{text}")\n'
        return [p for p in prep.validate(src, prompt, loras, set())["problems"] if "name of a LoRA" in p]

    def test_an_exact_lora_name_the_user_didnt_write_is_sent_back(self):
        assert self.flagged("Soft light, studio krea.")
        assert self.flagged("A woman with curtain bangs.")
        assert self.flagged("Portrait, XYZ 000003000.")

    def test_a_name_the_user_wrote_stays(self):
        assert not self.flagged("A woman wearing a dress.", "a woman wearing a dress, pick a lora")

    def test_words_for_the_lora_thats_on_are_only_noted(self):
        loras = [LoraInfo("Braided Crown", "k/b"), LoraInfo("Pixie Cut XL", "k/p")]
        src = ('h = pick_lora("hair", ["Braided Crown", "Pixie Cut XL"], phase=1, line=1)\n'
               'words = {"Braided Crown": "her hair in a braided crown"}.get(h, "")\n'
               'emit("A woman at a bus stop,", words, ".")\n')
        checked = prep.validate(src, "A woman at a bus stop, pick a hairstyle lora", loras, set())
        assert not any("LoRA" in p for p in checked["problems"])
        assert any('names the LoRA "Braided Crown" while it is on' in n for n in checked["notes"])

    def test_a_name_that_is_a_trigger_word_is_the_loras_own(self):
        # the runtime adds "curtain bangs" with the Curtain Bangs LoRA: the program can't leave it out
        loras = [LoraInfo("Curtain Bangs", "k/c", 1.0, "curtain bangs"), LoraInfo("Pixie Cut XL", "k/p", 1.0, "pixiecut")]
        src = 'h = pick_lora("hair", ["Curtain Bangs", "Pixie Cut XL"], phase=1, line=1)\nemit("A girl on a swing.")\n'
        checked = prep.validate(src, "A girl on a swing, choose a hair lora", loras, set())
        assert not any("LoRA" in p for p in checked["problems"])

    def test_whole_names_only(self):
        # part of a name, or a name inside a longer word, is not the name
        assert not self.flagged("prestudio kreative, a dressmaker, curtains")


class TestArticles:
    def test_an_article_before_a_value_that_has_one_collapses(self):
        from prompt_programs.runtime import tidy_text
        assert tidy_text(["A", "a spontaneous photo of a woman. She has a", "a warm smile."]) == "A spontaneous photo of a woman. She has a warm smile."
        assert tidy_text(["A cat and a dog"]) == "A cat and a dog"

    def test_a_joining_word_before_a_value_that_has_one_collapses(self):
        from prompt_programs.runtime import tidy_text
        assert tidy_text(["A photo of a cat", "with", "with tufted ears", ", in", "in a sunlit garden", "."]) == \
            "A photo of a cat with tufted ears, in a sunlit garden."
        assert tidy_text(["A woman,", "her", "her chestnut hair", "loose."]) == "A woman, her chestnut hair loose."
        # only at a seam after a few joining words: a doubled word inside a part, or after a long part, is as written
        assert tidy_text(["They had had enough."]) == "They had had enough."
        assert tidy_text(["a tall man standing by the old harbor wall in", "in a red coat"]) == \
            "A tall man standing by the old harbor wall in in a red coat"


class TestOptionContinuity:
    def test_a_patched_program_keeps_the_pools_of_picks_it_didnt_touch(self):
        from prompt_programs.draws import PickSpec
        from prompt_programs.options import GeneratedOptions, ProgramContext

        spec = PickSpec("eye_color", "Eye Color", "her eye color", 2, "text", "pick", ["emerald green"], [])
        v1 = ProgramContext(key="p1", signature="a woman with {eyes}", template="a woman with {eyes}", lineage="p1")
        v2 = ProgramContext(key="p2", signature="a tall woman with {eyes}", template="a tall woman with {eyes}", lineage="p1")
        other = ProgramContext(key="p3", signature="a tall woman with {eyes}", template="a tall woman with {eyes}", lineage="p3")
        k1 = GeneratedOptions(None, v1)._where(spec, {})[1]
        assert GeneratedOptions(None, v2)._where(spec, {})[1] == k1      # same lineage: same options
        assert GeneratedOptions(None, other)._where(spec, {})[1] != k1   # a new prompt: its own

    def test_a_wildcard_in_the_users_words_bounds_its_options(self):
        from prompt_programs.draws import PickSpec
        from prompt_programs.options import GeneratedOptions, OptionJob, ProgramContext, generation_messages
        spec = PickSpec("1970s_or_1980s_cars", "Cars", "the parked cars", 1, "text", "pick", ["a Ford Granada"], [])
        prog = ProgramContext(key="p", signature="a street", template="a street of [Cars]", lineage="p",
                              intents=(("1970s_or_1980s_cars", "1970s or 1980s cars"),))
        plain = ProgramContext(key="p", signature="a street", template="a street of [Cars]", lineage="p")
        assert GeneratedOptions(None, prog)._where(spec, {})[1] != GeneratedOptions(None, plain)._where(spec, {})[1]
        job = OptionJob("k", spec, {}, prog, "a street", 0)
        user = generation_messages(job)[1]["content"]
        assert '"1970s or 1980s cars"' in user and "rule, not an example" in user


def test_trigger_words_the_program_writes_for_a_picked_lora_are_cut():
    from prompt_programs import prepare as prep
    from prompt_programs.runtime import LoraInfo
    loras = [LoraInfo("Kodak Film Grain", "a.safetensors", trigger="kodakgrain"),
             LoraInfo("Watercolor Wash", "b.safetensors", trigger="wtrclr style, soft wash")]
    src = ('style = pick_lora("style", ["Kodak Film Grain", "Watercolor Wash"], label="Style", phase=1, line=1)\n'
           'words = {"Kodak Film Grain": "kodakgrain", "Watercolor Wash": "wtrclr style, painted"}.get(style, "")\n'
           'emit("A street at night, kodakgrain,", words, ", soft wash.")\n')
    out, notes = prep.fix_trigger_words(src, loras, "A street at night, choose a style lora, soft wash")
    assert '"Kodak Film Grain": ""' in out and '"Watercolor Wash": "painted"' in out
    assert 'emit("A street at night", words, ", soft wash.")' in out  # the user wrote "soft wash": it stays
    assert len(notes) == 2
    compile(out, "<program>", "exec")
    # without a pick_lora the words are the user's or the style guide's: left alone
    plain = 'emit("A street at night, kodakgrain")\n'
    assert prep.fix_trigger_words(plain, loras, "A street at night") == (plain, [])
