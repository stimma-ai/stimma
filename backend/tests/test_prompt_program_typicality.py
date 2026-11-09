"""Typical people: bound person attributes weighted by what's known about the person."""

import collections
import json

import pytest

import prompt_programs.draws as draws_mod
from prompt_programs.draws import NullJudge, draw
from prompt_programs.fluent import runtime_for
from prompt_programs.judge import FluentSettings
from prompt_programs.options import GeneratedOptions, OptionStore, ProgramContext
from prompt_programs.runtime import discover
from prompt_programs.typicality import (
    LEVEL_WEIGHTS, Conditioner, Tables, age_mixture, load, mentions, tables, who_of,
)
from prompt_programs.vocab import load as load_vocab, vocabulary

GREY = {"gray", "white", "salt-and-pepper", "gray-templed dark brown", "white-streaked black"}
CHILD = {"3–4", "5–7", "8–10", "11–12"}
OFF = FluentSettings(generate_options=False)

AGE_THEN_HAIR = '''
age = pick("age", cls="person.age_band", about="the woman's age", seed=["30–34"], label="Age", phase=1, line=1)
hair = pick("hair", cls="person.hair_color", about="her hair color", seed=["black"], label="Hair", phase=1, line=1)
emit("A portrait of a woman aged", age, "with", hair, "hair")
'''

HAIR_THEN_AGE = '''
hair = pick("hair", cls="person.hair_color", about="the man's hair color", seed=["black"], label="Hair", phase=1, line=1)
age = pick("age", cls="person.age_band", about="the man's age", seed=["30–34"], label="Age", phase=2, line=1)
emit("A man aged", age, "with", hair, "hair")
'''

LITTLE_GIRL = '''
hair = pick("hair", cls="person.hair_color", about="the girl's hair color", seed=["black"], label="Hair", phase=1, line=1)
eyes = pick("eyes", cls="person.eye_color", about="the girl's eye color", seed=["brown"], label="Eyes", phase=1, line=1)
emit("Photo of a Japanese little girl with", hair, "hair and", eyes, "eyes, swimming")
'''


def opts():
    return GeneratedOptions(None, ProgramContext(key="typ", signature="people", template="people"))


def many(src, n=300, **kw):
    o = opts()
    out = []
    for seed in range(n):
        r = draw(src, seed, None, [], None, None, None, options=o, judge=NullJudge(), **kw)
        out.append((r, {d.id: d.value for d in r.draws}))
        o.reset()
    return out


@pytest.fixture
def no_tables(monkeypatch):
    monkeypatch.setattr(draws_mod, "typicality_tables", lambda: Tables([], tables().lexicon, ""))


# --------------------------------------------------------------------------- tables

class TestTables:
    def test_the_shipped_tables_load_with_known_levels(self):
        t = tables()
        assert t.version.startswith("typ-") and len(t.tables) >= 10
        assert {"person.age_band", "person.ethnicity", "presentation"} <= set(t.givens)
        allowed = set(LEVEL_WEIGHTS.values())
        for tab in t.tables:
            assert tab.target.startswith("person.")
            for row in tab.rows.values():
                assert set(row.values()) <= allowed

    def test_tables_name_values_the_vocabulary_has(self):
        v = vocabulary()
        for tab in tables().tables:
            leaf = v.get(tab.target)
            assert leaf is not None, tab.target
            known = {x.text for x in leaf.values}
            cells = {c for row in tab.rows.values() for c in row}
            assert len(cells & known) / len(cells) > 0.9, tab.target   # a vocabulary edit may rename a few

    def test_load_reads_tables_and_the_lexicon_and_versions_by_content(self, tmp_path):
        d = tmp_path / "person" / "_typicality"
        d.mkdir(parents=True)
        (d / "age_band.hair_color.json").write_text(json.dumps(
            {"given": "person.age_band", "target": "person.hair_color", "rows": {"5–7": {"gray": "implausible"}}}))
        (d / "stated.json").write_text(json.dumps({"nouns": {"girl": {"gender": "feminine"}}}))
        t = load([tmp_path])
        assert len(t.tables) == 1 and t.tables[0].rows["5–7"]["gray"] == 0.0
        assert t.lexicon["nouns"]["girl"]["gender"] == "feminine"
        assert load([tmp_path]).version == t.version
        (d / "age_band.hair_color.json").write_text(json.dumps(
            {"given": "person.age_band", "target": "person.hair_color", "rows": {"5–7": {"gray": "rare"}}}))
        assert load([tmp_path]).version != t.version

    def test_no_tables_is_an_empty_set(self, tmp_path):
        t = load([tmp_path])
        assert t.tables == [] and t.version == ""

    def test_the_vocabulary_loader_skips_typicality_data(self, tmp_path):
        (tmp_path / "person").mkdir()
        (tmp_path / "person" / "eye_color.json").write_text(json.dumps({"label": "Eyes", "values": [{"text": "blue"}]}))
        before = load_vocab([tmp_path])
        d = tmp_path / "person" / "_typicality"
        d.mkdir()
        (d / "x.y.json").write_text(json.dumps({"given": "a", "target": "b", "rows": {}}))
        after = load_vocab([tmp_path])
        assert list(after.leaves) == ["person.eye_color"]
        assert after.version == before.version   # tables never re-key prepared programs


# --------------------------------------------------------------------------- reading people

class TestReading:
    def test_a_stated_child_and_descent(self):
        (m,) = mentions("Photo of a beautiful japanese little girl swimming")
        facts = dict(m.facts)
        assert {b for b, _ in facts["person.age_band"]} <= CHILD
        assert facts["person.ethnicity"] == (("Japanese", 1.0),)
        assert facts["presentation"] == (("feminine", 1.0),)

    def test_numbers_and_decades(self):
        (m,) = mentions("a portrait of a 16 y.o. boy")
        assert {b for b, _ in dict(m.facts)["person.age_band"]} == {"15–17"}
        (m,) = mentions("a woman in her 40s reading")
        assert {b for b, _ in dict(m.facts)["person.age_band"]} == {"40–44", "45–49"}
        (m,) = mentions("A portrait of a woman aged 25–29 with black hair")
        assert dict(m.facts)["person.age_band"] == (("25–29", 1.0),)
        assert m.stated == (("person.hair_color", "black"),)

    def test_a_place_word_is_not_the_persons_descent(self):
        (m,) = mentions("a Japanese garden with a woman")
        assert "person.ethnicity" not in dict(m.facts)

    def test_two_people_keep_their_own_ages(self):
        g, d = mentions("an old woman and a little girl")
        assert min(int(b.split("–")[0]) for b, _ in dict(g.facts)["person.age_band"]) >= 65
        assert {b for b, _ in dict(d.facts)["person.age_band"]} <= CHILD

    def test_a_stated_adult_has_no_lean_but_no_child_bands(self):
        (m,) = mentions("a woman on a bench")
        assert "person.age_band" not in dict(m.facts) and m.ages[0] >= 18

    def test_who_a_pick_is_about(self):
        assert who_of("the girl's hair color", "Hair", "hair").noun == "girl"
        assert who_of("her eye color", "Eyes", "eyes").gender == "feminine"
        assert who_of("his beard", "Beard", "beard").gender == "masculine"
        assert who_of("", "", "grandmother.hair").noun == "grandmother"

    def test_young_spreads_evenly_over_young_adult_bands(self):
        mix = dict(age_mixture(18, 34))
        assert set(mix) == {"18–19", "20–24", "25–29", "30–34"}
        assert abs(sum(mix.values()) - 1) < 1e-6


# --------------------------------------------------------------------------- weighting

class TestWeighting:
    def test_age_conditions_hair(self):
        rows = many(AGE_THEN_HAIR, 600)
        young = [v for _, v in rows if int(v["age"].split("–")[0]) < 35]
        old = [v for _, v in rows if int(v["age"].split("–")[0]) >= 65]
        assert young and old
        young_grey = sum(v["hair"] in GREY for v in young) / len(young)
        old_grey = sum(v["hair"] in GREY for v in old) / len(old)
        assert young_grey < 0.08 and old_grey > 0.4

    def test_a_stated_woman_never_draws_a_childs_age(self):
        assert not any(v["age"] in CHILD for _, v in many(AGE_THEN_HAIR, 300))

    def test_a_given_drawn_after_its_target_follows_it(self):
        rows = many(HAIR_THEN_AGE, 800)
        grey = [v for _, v in rows if v["hair"] in {"gray", "white"}]
        assert grey
        assert sum(int(v["age"].split("–")[0]) < 35 for v in grey) / len(grey) < 0.1

    def test_stated_text_conditions_bound_picks(self):
        rows = many(LITTLE_GIRL, 400)
        assert not any(v["hair"] in {"gray", "white", "salt-and-pepper"} for _, v in rows)
        light = sum(v["eyes"] in {"blue", "green", "gray", "pale blue"} for _, v in rows) / len(rows)
        assert 0 < light < 0.1   # rare, not gone

    def test_without_tables_draws_are_as_before(self, no_tables):
        rows = many(LITTLE_GIRL, 300)
        assert any(v["hair"] in GREY for _, v in rows)
        assert all("typicality" not in r.revision for r, _ in rows)

    def test_the_same_seed_draws_the_same(self):
        o = opts()
        a = draw(AGE_THEN_HAIR, 42, None, [], None, None, None, options=o, judge=NullJudge())
        b = draw(AGE_THEN_HAIR, 42, None, [], None, None, None, options=opts(), judge=NullJudge())
        assert a.prompt == b.prompt and a.revision == b.revision

    def test_a_pin_is_never_dropped(self):
        rows = many(LITTLE_GIRL, 20)
        o = opts()
        for seed in range(20):
            r = draw(LITTLE_GIRL, seed, {"hair": ["gray"]}, [], None, None, None, options=o, judge=NullJudge())
            assert "gray hair" in r.prompt
        assert rows

    def test_a_replayed_value_is_kept(self):
        o = opts()
        r = draw(LITTLE_GIRL, 3, None, [], None, {"hair": "white"}, None, options=o, judge=NullJudge())
        assert "white hair" in r.prompt

    def test_user_lists_and_stated_text_are_untouched(self):
        src = '''
who = pick("who", ["little girl", "old man"], source="list", label="Who", phase=1, line=1)
hair = pick("hair", ["gray", "black"], source="list", label="Hair", phase=1, line=1)
eyes = pick("eyes", cls="person.eye_color", about="their eyes", seed=["brown"], label="Eyes", phase=2, line=1)
emit("A", who, "with", hair, "hair, gray hair at the temples, and", eyes, "eyes")
'''
        rows = many(src, 300)
        combos = collections.Counter((v["who"], v["hair"]) for _, v in rows)
        assert combos[("little girl", "gray")] > 40   # a user list draws as written
        assert all("gray hair at the temples" in r.prompt for r, _ in rows)

    def test_a_user_list_value_conditions_a_bound_pick(self):
        src = '''
who = pick("who", ["child", "elderly person"], source="list", label="Who", phase=1, line=1)
hair = pick("hair", cls="person.hair_color", about="their hair color", seed=["brown"], label="Hair", phase=2, line=1)
emit("A", who, "with", hair, "hair")
'''
        rows = many(src, 400)
        kids = [v for _, v in rows if v["who"] == "child"]
        elders = [v for _, v in rows if v["who"] == "elderly person"]
        assert not any(v["hair"] in {"gray", "white", "salt-and-pepper"} for v in kids)
        assert sum(v["hair"] in GREY for v in elders) / len(elders) > 0.4

    def test_each_person_is_conditioned_on_their_own_details(self):
        src = '''
g = pick("grandmother.hair", cls="person.hair_color", about="the grandmother's hair color", seed=["white"], label="Her hair", phase=1, line=1)
k = pick("granddaughter.hair", cls="person.hair_color", about="the granddaughter's hair color", seed=["brown"], label="Girl's hair", phase=1, line=1)
emit("A grandmother with", g, "hair and her little granddaughter with", k, "hair")
'''
        rows = many(src, 300)
        assert sum(v["grandmother.hair"] in GREY for _, v in rows) / len(rows) > 0.4
        assert not any(v["granddaughter.hair"] in {"gray", "white", "salt-and-pepper"} for _, v in rows)

    def test_each_person_in_a_group_loop_follows_their_own_age(self):
        src = '''
n = group("people", 3, label="Friends", line=1)
parts = []
for i in range(n):
    age = pick(f"people[{i+1}].age", cls="person.age_band", about="this person's age", seed=["25–29"], label="Age", phase=1, line=1)
    hair = pick(f"people[{i+1}].hair", cls="person.hair_color", about="this person's hair color", seed=["black"], label="Hair", phase=2, line=1)
    parts.append(["a person aged", age, "with", hair, "hair"])
emit("Three friends at a picnic:", parts)
'''
        young = old = young_grey = old_grey = 0
        for _, v in many(src, 400):
            for i in (1, 2, 3):
                lo = int(v[f"people[{i}].age"].split("–")[0])
                grey = v[f"people[{i}].hair"] in GREY
                if lo < 35:
                    young, young_grey = young + 1, young_grey + grey
                elif lo >= 65:
                    old, old_grey = old + 1, old_grey + grey
        assert young_grey / young < 0.02 and old_grey / old > 0.5

    def test_one_persons_drawn_age_never_narrows_anothers(self):
        src = '''
a1 = pick("girl[1].age", cls="person.age_band", about="the first woman's age", seed=["20–24"], label="Age", phase=1, line=1)
h1 = pick("girl[1].hair", cls="person.hair_color", about="her hair color", seed=["black"], label="Hair", phase=1, line=1)
a2 = pick("girl[2].age", cls="person.age_band", about="the second woman's age", seed=["20–24"], label="Age", phase=1, line=1)
h2 = pick("girl[2].hair", cls="person.hair_color", about="her hair color", seed=["black"], label="Hair", phase=1, line=1)
emit("Two women: one aged", a1, "with", h1, "hair, and one aged", a2, "with", h2, "hair")
'''
        rows = [v for _, v in many(src, 600)]
        old_young = [v for v in rows if int(v["girl[1].age"].split("–")[0]) >= 65 and int(v["girl[2].age"].split("–")[0]) < 35]
        assert len(old_young) > 15   # the second woman's age is drawn on its own
        assert not any(v["girl[2].hair"] in {"gray", "white", "salt-and-pepper"} for v in old_young)
        assert sum(v["girl[1].hair"] in GREY for v in old_young) / len(old_young) > 0.5

    def test_a_pending_beard_keeps_a_person_out_of_childhood(self):
        src = '''
age = pick("age", cls="person.age_band", about="the person's age", seed=["30–34"], label="Age", phase=1, line=1)
beard = pick("beard", cls="person.facial_hair", about="the person's facial hair", seed=["light stubble"], label="Beard", phase=1, line=1)
emit("A person aged", age, "with", beard)
'''
        assert not any(v["age"] in CHILD for _, v in many(src, 400))

    def test_the_picker_still_lists_every_value(self):
        (r, _), = many(LITTLE_GIRL, 1)
        hair = next(d for d in r.draws if d.id == "hair")
        assert "gray" in hair.options

    def test_classes_without_tables_draw_as_before(self, monkeypatch):
        src = '''
expr = pick("expr", cls="person.expression", about="her expression", seed=["a smile"], label="Expression", phase=1, line=1)
emit("A little girl with", expr)
'''
        on = [r.prompt for r, _ in many(src, 50)]
        monkeypatch.setattr(draws_mod, "typicality_tables", lambda: Tables([], tables().lexicon, ""))
        assert [r.prompt for r, _ in many(src, 50)] == on

    def test_level_weights_multiply_across_givens(self):
        c = Conditioner()
        sig = (("person.age_band", (("20–24", 1.0),)), ("person.ethnicity", (("Korean", 1.0),)))
        m = c.weights("person.hair_color", sig, ["gray", "black"])
        age = next(t for t in c.tabs.for_target("person.hair_color") if t.given == "person.age_band")
        eth = next(t for t in c.tabs.for_target("person.hair_color") if t.given == "person.ethnicity")
        assert m["gray"] == pytest.approx(age.rows["20–24"]["gray"] * eth.rows["Korean"]["gray"])
        assert m["black"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- replays

class TestReplay:
    def _entry(self, src):
        info = discover(src)
        return {"key": "typ", "program": src, "loras": [], "params": {}, "mode": "prose", "choices": info["choices"]}

    def test_a_revision_replays_after_the_tables_change(self, tmp_path, monkeypatch):
        entry = self._entry(LITTLE_GIRL)
        firsts = []
        for seed in range(30):
            rt = runtime_for(entry, store=OptionStore(tmp_path), judge=NullJudge(), cfg=OFF)
            firsts.append(draw(LITTLE_GIRL, seed, None, [], None, None, None, options=rt.options, judge=NullJudge()))
        assert all(isinstance(f.revision.get("typicality"), dict) for f in firsts)
        monkeypatch.setattr(draws_mod, "typicality_tables", lambda: Tables([], tables().lexicon, ""))  # a new release
        for seed, first in enumerate(firsts):
            rt = runtime_for(entry, store=OptionStore(tmp_path), judge=NullJudge(), cfg=OFF, revision=first.revision)
            again = draw(LITTLE_GIRL, seed, None, [], None, None, None, options=rt.options, judge=NullJudge(),
                         typicality=rt.typicality)
            assert again.prompt == first.prompt

    def test_a_revision_from_before_typicality_replays_without_it(self, tmp_path, monkeypatch):
        entry = self._entry(LITTLE_GIRL)
        monkeypatch.setattr(draws_mod, "typicality_tables", lambda: Tables([], tables().lexicon, ""))
        old = []
        for seed in range(30):
            rt = runtime_for(entry, store=OptionStore(tmp_path), judge=NullJudge(), cfg=OFF)
            old.append(draw(LITTLE_GIRL, seed, None, [], None, None, None, options=rt.options, judge=NullJudge()))
        monkeypatch.setattr(draws_mod, "typicality_tables", tables)   # typicality ships
        for seed, first in enumerate(old):
            rt = runtime_for(entry, store=OptionStore(tmp_path), judge=NullJudge(), cfg=OFF, revision=first.revision)
            assert rt.typicality == "off"
            again = draw(LITTLE_GIRL, seed, None, [], None, None, None, options=rt.options, judge=NullJudge(),
                         typicality=rt.typicality)
            assert again.prompt == first.prompt
