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
