"""Fluent vocabulary: curated lists picks bind to with cls=, their pools, the picker's
view of them, the writer's catalog, and article agreement in emitted text."""

import pytest

from prompt_programs import program as prep
from prompt_programs.draws import PickSpec, draw
from prompt_programs.fluent import pool_options
from prompt_programs.judge import FluentSettings
from prompt_programs.options import (
    GeneratedOptions, OptionFiller, OptionStore, ProgramContext, gen_key, generated_pick, generation_messages,
)
from prompt_programs.runtime import ProgramError, discover, run, tidy_text
from prompt_programs.vocab import OPEN_SHARE, TIER_WEIGHTS, load, vocabulary

async def narrow_read(entry, cache, ask, *args, **kw):
    """narrow_entry with the fake model's reading as the slots' words (slots.build writes them)."""
    entry.setdefault("slot_words", dict(getattr(ask, "read", None) or {}))
    return await narrow_entry(entry, cache, ask, *args, **kw)


PORTRAIT = '''
eth = pick("eth", cls="person.ethnicity", about="her ethnicity", seed=["Korean"], label="Ethnicity", phase=1, line=1)
eyes = pick("eyes", cls="person.eye_color", about="her eye color", seed=["hazel"], label="Eyes", phase=2, line=1)
expr = pick("expr", cls="person.expression", about="her expression", seed=["a soft smile"], label="Expression", phase=2, line=1)
emit("A portrait of a", eth, "woman with", eyes, "eyes and", expr, ".")
'''

OFF = FluentSettings(generate_options=False, fix_model="off")


def program():
    return ProgramContext(key="prog1", signature="a portrait", template="A portrait of a [Ethnicity] woman")


def bound_spec(cls, id="x", about="something"):
    return PickSpec(id, "X", about, 2, "text", "pick", ["a seed"], [], cls)


class FakeGen:
    def __init__(self):
        self.calls = []

    async def __call__(self, job):
        self.calls.append(job)
        return [f"generated {job.round}.{i}" for i in range(4)], "fake"


class TestTheVocabulary:
    def test_it_loads_with_unique_leaves_and_frames(self):
        v = vocabulary()
        assert v.version.startswith("vocab-") and v.leaves and v.nodes
        for leaf in v.leaves.values():
            assert "___" in leaf.frame, leaf.id
            assert leaf.values, leaf.id
            assert all(val.tier in TIER_WEIGHTS for val in leaf.values), leaf.id
            assert leaf.id.rsplit(".", 1)[0] in v.nodes, leaf.id

    def test_person_leaves_are_there_and_some_are_closed(self):
        v = vocabulary()
        assert v.get("person.eye_color").closed and not v.get("person.expression").closed
        assert v.get("nope") is None and v.get(None) is None

    def test_context_defaults_filter_fantasy_values_out(self):
        leaf = vocabulary().get("person.eye_color")
        plain = {x.text for x in leaf.eligible()}
        fantasy = {x.text for x in leaf.eligible({"genre": "fantasy"})}
        assert plain and fantasy - plain  # fantasy-only colors appear only in fantasy

    def test_a_list_the_defaults_would_empty_keeps_its_own_world(self):
        v = vocabulary()
        for lid in ("person.outfit.period", "person.outfit.fantasy", "person.outfit.scifi"):
            assert v.get(lid).eligible()  # bound means the image is in that world
        fantasy = {x.text for x in v.get("person.eye_color").eligible()}
        assert {x.text for x in v.get("person.eye_color").eligible({"genre": "fantasy"})} - fantasy  # gates still hold

    def test_facial_hair_can_be_none(self):
        assert vocabulary().get("person.facial_hair").value("a clean-shaven face") is not None

    def test_examples_are_a_stable_spread(self):
        leaf = vocabulary().get("person.expression")
        a, b = leaf.examples("k"), leaf.examples("k")
        assert a == b and len(a) == 10 and len(set(a)) == 10 and leaf.examples("other") != a

    def test_the_catalog_lists_person_and_animal_ids_without_sample_values(self):
        cat = vocabulary().catalog()
        assert "- person.eye_color: adjective" in cat and "interior_space" not in cat
        assert "- animal.dog_breed: noun phrase" in cat and "- animal.cat_coat:" in cat
        assert "orange tabby" not in cat
        assert "medium brown" not in cat  # no fixed samples (a shade name like "hazel" is a facet, not a sample)

    def test_places_months_and_seasons_are_offered_by_name(self):
        cat = vocabulary().catalog()
        for lid in ("place.country", "place.city", "place.us_state", "scene.month", "scene.season"):
            assert f"- {lid}:" in cat
        country = vocabulary().get("place.country")
        assert country.closed and country.value("Japan") is not None and country.value("the Netherlands") is not None
        assert all("," not in v.text for v in country.values)   # names, never a description of the place
        assert len(country.values) > 190 and {"Europe", "East Asia"} <= set(country.local_facets["area"])
        assert [v.text for v in vocabulary().get("scene.month").values][:2] == ["January", "February"]
        assert len(vocabulary().get("place.us_state").values) == 50
        season = vocabulary().get("scene.season")
        assert sorted(v.text for v in season.values if v.tier == "typical") == ["autumn", "spring", "summer", "winter"]

    def test_every_place_sits_under_an_area_chip(self):
        from prompt_programs.fluent import list_groups
        for lid in ("place.country", "place.city", "place.us_state"):
            leaf = vocabulary().get(lid)
            texts = [v.text for v in leaf.values]
            areas = list_groups(leaf, texts)["area"]
            assert {o for os in areas.values() for o in os} == set(texts), lid
        country = vocabulary().get("place.country")
        south = set(list_groups(country, [v.text for v in country.values])["area"]["South America"])
        assert {"Brazil", "Argentina", "Peru", "Guyana"} <= south


    def test_a_leaf_defined_twice_is_an_error(self, tmp_path):
        for root in ("a", "b"):
            d = tmp_path / root / "person"
            d.mkdir(parents=True)
            (d / "_node.json").write_text('{"id": "person"}')
            (d / "eyes.json").write_text('{"values": [{"text": "brown", "tier": "typical"}]}')
        with pytest.raises(ValueError):
            load((tmp_path / "a", tmp_path / "b"))


class TestBinding:
    def test_discovery_shows_the_list_and_the_binding(self):
        info = discover(PORTRAIT)
        by = {c["id"]: c for c in info["choices"]}
        eth = vocabulary().get("person.ethnicity")
        assert by["eth"]["cls"] == "person.ethnicity"
        assert by["eth"]["options"] == [x.text for x in eth.eligible()]
        assert "Korean" in by["eth"]["options"]

    def test_an_unknown_list_is_the_writers_mistake(self):
        with pytest.raises(ProgramError, match="isn't a vocabulary list"):
            run(PORTRAIT.replace("person.eye_color", "person.eyes"), 1)

    def test_a_near_certain_typo_resolves_and_a_far_one_does_not(self):
        v = vocabulary()
        assert v.resolve("person.eye_eye_color").id == "person.eye_color"
        assert v.resolve("person.eye_colour").id == "person.eye_color"
        assert v.resolve("person.nostril") is None and v.resolve("interior.bedroom") is None
        src = PORTRAIT.replace("person.eye_color", "person.eye_colour")
        eyes = next(d for d in run(src, 1).draws if d.id == "eyes")
        assert eyes.cls == "person.eye_color"

    def test_an_unknown_list_suggests_the_nearest(self):
        with pytest.raises(ProgramError, match='Did you mean cls="person.ethnicity"'):
            run(PORTRAIT.replace("person.ethnicity", "person.ethnday"), 1)

    def test_a_user_list_cannot_bind(self):
        src = 'x = pick("x", ["a", "b"], source="list", cls="person.eye_color", phase=1)\nemit(x)'
        with pytest.raises(ProgramError, match="never a user list"):
            run(src, 1)

    def test_draws_come_from_the_lists(self):
        opts = GeneratedOptions(None, program())
        v = vocabulary()
        for seed in range(5):
            r = draw(PORTRAIT, seed, None, [], None, None, None, options=opts)
            got = {d.id: d for d in r.draws}
            assert got["eth"].value in {x.text for x in v.get("person.ethnicity").values}
            assert got["eyes"].value in {x.text for x in v.get("person.eye_color").eligible()}
            assert got["eyes"].cls == "person.eye_color"
            opts.reset()

    def test_a_list_the_vocabulary_lost_draws_unbound(self):
        src = PORTRAIT.replace("person.eye_color", "person.gone")
        r = draw(src, 1, None, [], None, None, None, options=GeneratedOptions(None, program()))
        eyes = next(d for d in r.draws if d.id == "eyes")
        assert eyes.value == "hazel" and eyes.cls == "person.gone"  # its seed; the id is kept for replays


class TestBoundPools:
    def test_a_closed_list_is_the_whole_pool_and_never_generates(self, tmp_path):
        store = OptionStore(tmp_path)
        filler = OptionFiller(store, FakeGen())
        s = bound_spec("person.eye_color")
        assert not generated_pick(s)
        opts = GeneratedOptions(store, program(), filler=filler)
        pool = opts.get(s, {})
        leaf = vocabulary().get("person.eye_color")
        assert pool.items == [x.text for x in leaf.eligible()]
        assert pool.weights == [x.weight for x in leaf.eligible()]
        assert "a seed" not in pool.items  # the list replaces the writer's seeds
        opts.request_more(s, {}, "high")
        opts.rewrite_for_prompt(s, {}, ["brown"])
        assert not filler._jobs and not pool.more_coming

    def test_an_open_list_queues_generation_seeded_with_list_examples(self, tmp_path):
        store = OptionStore(tmp_path)
        filler = OptionFiller(store, FakeGen())
        s = bound_spec("person.expression", about="her expression")
        assert generated_pick(s)
        opts = GeneratedOptions(store, program(), filler=filler)
        opts.get(s, {})
        job = filler._jobs[opts.queued[0]][1]
        assert len(job.examples) == 10 and not job.existing
        text = generation_messages(job)[1]["content"]
        assert "curated list" in text and job.examples[0] in text and "a seed" not in text

    def test_generated_options_extend_an_open_list_and_share_its_weight(self, tmp_path):
        store = OptionStore(tmp_path)
        s = bound_spec("person.expression", about="her expression")
        leaf = vocabulary().get("person.expression")
        first = leaf.eligible()[0].text
        key = gen_key(s, {}, program().signature, "prose", True, (), lineage="", cls=s.cls)
        store.append(key, {"round": 0, "options": ["a brand new look", first]})
        pool = GeneratedOptions(store, program()).get(s, {})
        assert pool.items[-1] == "a brand new look" and pool.items.count(first) == 1
        n = len(leaf.eligible())
        assert sum(pool.weights[:n]) == pytest.approx(OPEN_SHARE)
        assert sum(pool.weights[n:]) == pytest.approx(1 - OPEN_SHARE)

    def test_a_replay_reads_the_same_pool_after_generation_grows(self, tmp_path):
        store = OptionStore(tmp_path)
        s = bound_spec("person.expression", about="her expression")
        key = gen_key(s, {}, program().signature, "prose", True, (), lineage="", cls=s.cls)
        store.append(key, {"round": 0, "options": ["look one", "look two"]})
        first = GeneratedOptions(store, program()).get(s, {})
        store.append(key, {"round": 1, "options": ["look three"]})
        again = GeneratedOptions(store, program(), limits={first.key: len(first.items)}).get(s, {})
        assert again.items == first.items and again.weights == pytest.approx(first.weights)

    def test_a_revision_replays_after_the_vocabulary_changes(self, tmp_path, monkeypatch):
        import dataclasses
        from prompt_programs.fluent import runtime_for
        info = discover(PORTRAIT)
        entry = {"key": "p", "program": PORTRAIT, "loras": [], "params": {}, "mode": "prose", "choices": info["choices"]}
        rt = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF)
        first = draw(PORTRAIT, 12, None, [], None, None, None, options=rt.options)
        rev = first.revision
        # bound pools are recorded whole: each by the hash of its contents, kept once (compact.py)
        assert any(isinstance(v, dict) and "$pool" in v for v in rev["pools"].values())
        v = vocabulary()
        for lid in ("person.expression", "person.eye_color", "person.ethnicity"):  # a new vocabulary release
            leaf = v.leaves[lid]
            monkeypatch.setitem(v.leaves, lid, dataclasses.replace(leaf, values=tuple(reversed(leaf.values[1:]))))
        rt2 = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF, revision=rev)
        again = draw(PORTRAIT, 12, None, [], None, None, None, options=rt2.options)
        assert again.prompt == first.prompt

    def test_a_revision_replays_after_its_list_is_removed(self, tmp_path, monkeypatch):
        from prompt_programs.fluent import runtime_for
        entry = {"key": "p", "program": PORTRAIT, "loras": [], "params": {}, "mode": "prose",
                 "choices": discover(PORTRAIT)["choices"]}
        rt = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF)
        first = draw(PORTRAIT, 0, None, [], None, None, None, options=rt.options)
        monkeypatch.delitem(vocabulary().leaves, "person.eye_color")
        rt2 = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF, revision=first.revision)
        again = draw(PORTRAIT, 0, None, [], None, None, None, options=rt2.options)
        assert again.prompt == first.prompt

    def test_bound_and_unbound_pools_never_share_generated_options(self):
        a = PickSpec("x", "X", "her expression", 2, "text", "pick", [], [])
        b = PickSpec("x", "X", "her expression", 2, "text", "pick", [], [], "person.expression")
        assert gen_key(a, {}, "sig", "prose", True) != gen_key(b, {}, "sig", "prose", True, cls=b.cls)

    def test_user_edits_apply(self, tmp_path):
        s = bound_spec("person.eye_color")
        edits = {"x": {"remove": ["blue"], "add": ["silver-flecked gray"]}}
        pool = GeneratedOptions(OptionStore(tmp_path), program(), edits=edits).get(s, {})
        assert "blue" not in pool.items and pool.items[-1] == "silver-flecked gray"


class TestThePicker:
    def test_pool_options_show_the_whole_list_with_tiers(self, tmp_path):
        info = discover(PORTRAIT)
        entry = {"key": "p", "program": PORTRAIT, "loras": [], "params": {}, "mode": "prose",
                 "choices": info["choices"]}
        out = pool_options(entry, store=OptionStore(tmp_path), cfg=OFF)
        eth = vocabulary().get("person.ethnicity")
        assert len(out["options"]["eth"]) == len(eth.eligible()) > 60  # uncapped
        meta = out["vocab"]["eyes"]
        assert meta["cls"] == "person.eye_color" and meta["closed"] is True
        assert set(meta["tiers"].values()) <= {"typical", "plausible", "unusual", "generated"}
        assert out["vocab"]["expr"]["closed"] is False

    def test_pool_options_carry_every_group_an_option_is_in(self, tmp_path):
        info = discover(PORTRAIT)
        entry = {"key": "p", "program": PORTRAIT, "loras": [], "params": {}, "mode": "prose",
                 "choices": info["choices"]}
        out = pool_options(entry, store=OptionStore(tmp_path), cfg=OFF)
        leaf = vocabulary().get("person.eye_color")
        groups = out["vocab"]["eyes"]["groups"]
        shown = out["options"]["eyes"]
        assert set(groups) == {f for f in leaf.local_facets if any(f in (leaf.value(o).tags or {}) for o in shown)}
        for facet, parts in groups.items():
            names = leaf.local_facets[facet]
            assert [n for n in names if n in parts] == list(parts)   # the list's order
            for part, options in parts.items():
                assert options and all(part in leaf.value(o).tags[facet] for o in options)
        # an option in several parts sits in each of them
        facet = next(iter(groups))
        several = [o for o in shown if len(leaf.value(o).tags.get(facet) or []) > 1]
        assert several and all(sum(o in os for os in groups[facet].values()) > 1 for o in several)
        # descent has no local facets: its declared heritages are its groups
        eth = out["vocab"]["eth"]["groups"]
        assert list(eth) == ["group"] and "Korean" in eth["group"]["east_asian"]

    def test_list_groups_skip_long_lists_and_untagged_values(self):
        from prompt_programs.fluent import PARTS_MAX, list_groups
        from prompt_programs.vocab import Leaf, Value
        values = (Value("jet black", "typical", {"shade": ["black"]}), Value("ash brown", "typical", {"shade": ["brunette"]}),
                  Value("salt and pepper", "typical", {"shade": ["black", "gray"]}), Value("shaved", "typical"))
        leaf = Leaf("x.hair", "Hair", "", "", "", "", (), True, {}, values,
                    local_facets={"length": ("short", "long"), "shade": ("black", "brunette", "gray")})
        texts = [v.text for v in values]
        assert list_groups(leaf, [*texts, "my own"]) == {
            "shade": {"black": ["jet black", "salt and pepper"], "brunette": ["ash brown"], "gray": ["salt and pepper"]}}
        assert list_groups(leaf, ["shaved"]) == {}
        assert list_groups(leaf, [*texts, *(f"more {i}" for i in range(PARTS_MAX))]) == {}
        assert list_groups(Leaf("x.plain", "Plain", "", "", "", "", (), True, {}, values), texts) == {}


class TestArticles:
    @pytest.mark.parametrize("text,want", [
        ("a Irish woman", "An Irish woman"), ("an Korean man", "A Korean man"), ("a hour", "An hour"),
        ("an unicorn", "A unicorn"), ("an European", "A European"), ("a umbrella", "An umbrella"),
        ("a Ukrainian woman", "A Ukrainian woman"), ("a LED lamp", "An LED lamp"), ("an USB cable", "A USB cable"),
        ("She has a oval face.", "She has an oval face."), ("A portrait of a athletic man", "A portrait of an athletic man"),
        ("Plan A in action", "Plan A in action"), ("a bottle of vitamin A oil", "A bottle of vitamin A oil"),
        ("an unimpressed woman", "An unimpressed woman"), ("a uniform", "A uniform"), ("an university", "A university"),
        ("grade A eggs", "Grade A eggs"), ('He said "a apple"', 'He said "an apple"'),
        ('a sign reading "A is for apple"', 'A sign reading "A is for apple"'),
        ("a diagram with labels (A and B)", "A diagram with labels (A and B)"),
        ("a 80-year-old man", "An 80-year-old man"), ("an 65-year-old man", "A 65-year-old man"),
        ("a 8-year-old girl", "An 8-year-old girl"), ("a 11-year-old", "An 11-year-old"),
        ("a 18-year-old", "An 18-year-old"), ("an 13-year-old", "A 13-year-old"),
        ("a 1980s car", "A 1980s car"), ("a 18,000-seat arena", "An 18,000-seat arena"), ("an 110 km road", "A 110 km road"),
        ("An honest, elderly woman.", "An honest, elderly woman."), ("an hour, then", "An hour, then"),
        ("a 8, then a 9", "An 8, then a 9"),
    ])
    def test_a_and_an_follow_the_next_word(self, text, want):
        assert tidy_text([text]) == want


# --------------------------------------------------------------------------- where=: narrowing a list

from prompt_programs.narrow import NarrowCache, narrow_entry, parse_subset  # noqa: E402

YOUNG = '''
age = pick("age", cls="person.age_band", where="young", about="her age", seed=["20-year-old"], label="Age", phase=1, line=1)
eyes = pick("eyes", cls="person.eye_color", about="her eye color", seed=["hazel"], label="Eyes", phase=1, line=1)
emit("A young", age, "woman with", eyes, "eyes.")
'''


def young_entry(prompt="a young woman with pretty eyes"):
    info = discover(YOUNG)
    return {"key": "y", "program": YOUNG, "loras": [], "params": {}, "mode": "prose", "choices": info["choices"],
            "prompt": prompt}


def pretty_entry():
    """YOUNG with the writer's where= on her eyes too: words nothing on the eye color list fits."""
    src = YOUNG.replace('about="her eye color"', 'where="pretty", about="her eye color"')
    return {"key": "p", "program": src, "loras": [], "params": {}, "mode": "prose", "choices": discover(src)["choices"],
            "prompt": "a young woman with pretty eyes"}


class FakeAsk:
    """Answers a narrowing question with the values for which `keep` is true, and the
    prompt-reading question with `read` ({choice id: words})."""

    def __init__(self, keep=None, reply=None, read=None):
        self.keep, self.reply, self.read, self.calls, self.reads = keep, reply, read or {}, [], []

    async def __call__(self, messages, project_id, max_tokens):
        self.calls.append(messages)
        if self.reply is not None:
            return self.reply
        import json, re
        values = json.loads(re.search(r"\n(\[.*\])\n", messages[1]["content"], re.S).group(1))
        return json.dumps([v for v in values if self.keep(v)])


def young(v):
    return v.split("-")[0].isdigit() and 18 <= int(v.split("-")[0]) < 35


class TestWhere:
    def test_where_is_recorded_on_the_choice(self):
        by = {c["id"]: c for c in discover(YOUNG)["choices"]}
        assert by["age"]["where"] == "young" and "where" not in by["eyes"]

    def test_parse_subset_keeps_the_lists_order_and_ignores_strangers(self):
        assert parse_subset('Sure: ["25–29", "18–19", "a teenager"]', ["18–19", "20–24", "25–29"]) == ["18–19", "25–29"]
        assert parse_subset("no list here", ["a"]) is None
        assert parse_subset("[]", ["a"]) == []
        assert parse_subset('```json\n["ALL"]\n```', ["a", "b"]) == ["a", "b"]

    async def test_an_entry_is_narrowed_and_the_answer_cached(self, tmp_path):
        entry, ask = young_entry(), FakeAsk(young)
        await narrow_read(entry, NarrowCache(tmp_path), ask)
        assert entry["filters"]["age"] == [v for v in [x.text for x in vocabulary().get("person.age_band").eligible()] if young(v)]
        assert "eyes" not in entry["filters"]  # no where=, no narrowing
        by = {c["id"]: c for c in entry["choices"]}
        assert by["age"]["options"] == entry["filters"]["age"]
        again = young_entry()
        await narrow_read(again, NarrowCache(tmp_path), ask)
        assert len(ask.calls) == 1 and again["filters"] == entry["filters"]  # "young" on ages: asked once

    async def test_nothing_fitting_or_an_unreadable_answer_leaves_the_pick_unbound(self, tmp_path):
        for ask in (FakeAsk(lambda v: False), FakeAsk(reply="I can't tell.")):
            entry = pretty_entry()
            notes = await narrow_read(entry, NarrowCache(tmp_path / str(id(ask))), ask)
            by = {c["id"]: c for c in entry["choices"]}
            assert entry["filters"]["eyes"] == [] and "cls" not in by["eyes"] and notes

    async def test_a_list_never_drawn_without_keeps_its_whole_list_when_nothing_fits(self, tmp_path):
        # Ages generated to fit words nothing in the list fits include children: the age list stays.
        assert vocabulary().get("person.age_band").strict and not vocabulary().get("person.eye_color").strict
        entry = pretty_entry()
        notes = await narrow_read(entry, NarrowCache(tmp_path), FakeAsk(lambda v: False))
        by = {c["id"]: c for c in entry["choices"]}
        assert "age" not in entry["filters"] and by["age"]["cls"] == "person.age_band"
        assert any("whole list" in n for n in notes)


    async def test_draws_and_pools_keep_to_the_subset(self, tmp_path):
        from prompt_programs.fluent import runtime_for
        entry = young_entry()
        await narrow_read(entry, NarrowCache(tmp_path), FakeAsk(young))
        rt = runtime_for(entry, store=OptionStore(tmp_path / "o"), cfg=OFF)
        for seed in range(8):
            r = draw(YOUNG, seed, None, [], None, None, None, options=rt.options)
            assert young(next(d for d in r.draws if d.id == "age").value)
            rt.options.reset()
        out = pool_options(entry, store=OptionStore(tmp_path / "o"), cfg=OFF)
        # The picker lists the whole list: the subset fits, the rest is drawn only once ticked.
        tiers = out["vocab"]["age"]["tiers"]
        assert [v for v in out["options"]["age"] if tiers[v] != "opt_in"] == entry["filters"]["age"]
        assert out["vocab"]["age"]["reach"]["fits"] == entry["filters"]["age"]

    async def test_an_unbound_fallback_generates_within_the_words(self, tmp_path):
        from prompt_programs.fluent import program_context
        entry = pretty_entry()
        await narrow_read(entry, NarrowCache(tmp_path), FakeAsk(lambda v: False))
        store = OptionStore(tmp_path / "o")
        filler = OptionFiller(store, FakeGen())
        opts = GeneratedOptions(store, program_context(entry), filler=filler)
        spec = PickSpec("eyes", "Eyes", "her eye color", 1, "text", "pick", ["hazel"], [], "person.eye_color")
        pool = opts.get(spec, {})
        assert pool.items == ["hazel"]  # its seed, while generated options are written
        job = filler._jobs[opts.queued[0]][1]
        assert 'own words: "pretty"' in generation_messages(job)[1]["content"]

    async def test_an_open_list_generates_from_the_subset_with_the_words_as_a_rule(self, tmp_path):
        from prompt_programs.fluent import program_context
        src = YOUNG.replace('cls="person.age_band", where="young"', 'cls="person.expression", where="happy"')
        info = discover(src)
        entry = {"key": "h", "program": src, "loras": [], "params": {}, "mode": "prose", "choices": info["choices"]}
        await narrow_read(entry, NarrowCache(tmp_path), FakeAsk(lambda v: "smile" in v or "grin" in v))
        store = OptionStore(tmp_path / "o")
        filler = OptionFiller(store, FakeGen())
        opts = GeneratedOptions(store, program_context(entry), filler=filler)
        spec = PickSpec("age", "Age", "her age", 1, "text", "pick", [], [], "person.expression")
        pool = opts.get(spec, {})
        drawn = [v for v, w in zip(pool.items, pool.weights) if w > 0]
        assert drawn and all(("smile" in v or "grin" in v) for v in drawn)
        assert all(w == 0 for v, w in zip(pool.items, pool.weights) if v not in drawn)  # the rest stands by
        job = filler._jobs[opts.queued[0]][1]
        assert job.examples and all(("smile" in v or "grin" in v) for v in job.examples)
        assert 'own words: "happy"' in generation_messages(job)[1]["content"]


# --------------------------------------------------------------------------- templates, palettes, local facets

from prompt_programs.vocab import _leaf, fill, tags_match, template_matches  # noqa: E402

PALETTE = {"label": "Colors", "description": "a color scheme", "pos": "color scheme", "frame": "in ___",
           "facets": [], "closed": True,
           "local_facets": {"color_family": ["red", "blue", "black"], "tone": ["dark", "bright"]},
           "values": [
               {"text": "red, white and gray", "tier": "typical", "roles": {"main": "red", "accent": "white", "neutral": "gray"},
                "tags": {"color_family": ["red"], "tone": ["bright"]}},
               {"text": "navy, white and gray", "tier": "typical", "roles": {"main": "navy", "accent": "white", "neutral": "gray"},
                "tags": {"color_family": ["blue"], "tone": ["dark"]}},
               {"text": "black, gray and white", "tier": "typical", "roles": {"main": "black", "accent": "gray", "neutral": "white"},
                "tags": {"color_family": ["black"], "tone": ["dark"]}}]}
OUTFITS = {"label": "Test outfit", "description": "whole looks", "pos": "noun phrase", "frame": "wearing ___",
           "facets": [], "closed": True, "slots": "person.palette",
           "local_facets": {"sport": ["running", "formal"]},
           "values": [
               {"text": "a {main} technical T-shirt and {accent} running shorts", "tier": "typical", "tags": {"sport": ["running"]}},
               {"text": "a {main} tuxedo with a {accent} shirt", "tier": "typical", "tags": {"sport": ["formal"]},
                "palette": {"tone": ["dark"]}},
               {"text": "a white karate gi", "tier": "typical", "tags": {"sport": ["running"]}}]}

DRESSED = '''
outfit = pick("outfit", cls="person.outfit.test", about="what she wears", seed=["a red T-shirt"], label="Outfit", phase=1, line=1)
emit("A woman wearing", outfit, ".")
'''


@pytest.fixture
def dressed(monkeypatch):
    v = vocabulary()
    monkeypatch.setitem(v.leaves, "person.palette", _leaf("person.palette", PALETTE))
    monkeypatch.setitem(v.leaves, "person.outfit.test", _leaf("person.outfit.test", OUTFITS))
    return v


def draw_dressed(seed, **kw):
    return draw(DRESSED, seed, kw.pop("pins", None), [], None, kw.pop("fixed", None), kw.pop("edits", None),
                options=kw.pop("options", None) or GeneratedOptions(None, program()), **kw)


class FixSpy:
    """A fix judge that records what it is asked and flags nothing."""
    version, cut = "spy", 0.5

    def __init__(self):
        self.items = []

    def p_wrong(self, items):
        self.items += list(items)
        return [0.0 for _ in items]


class TestTemplates:
    def test_fill_match_and_tags(self):
        t = "a {main} technical T-shirt and {accent} running shorts"
        assert fill(t, {"main": "navy", "accent": "white"}) == "a navy technical T-shirt and white running shorts"
        assert fill(t, None) == "a technical T-shirt and running shorts"
        assert template_matches(t, "a navy technical T-shirt and white running shorts")
        assert not template_matches(t, "a navy hoodie")
        assert tags_match({"tone": ["dark"]}, {"tone": ["dark", "bright"]}) and not tags_match({}, {"tone": "dark"})

    def test_a_template_draws_its_palette_and_reads_filled(self, dressed):
        for seed in range(12):
            r = draw_dressed(seed)
            got = {d.id: d for d in r.draws}
            outfit = got["outfit"]
            assert "{" not in r.prompt
            if "karate gi" in outfit.value:  # a fixed-color look draws no Colors
                assert "outfit.colors" not in got
                continue
            colors = dressed.leaves["person.palette"].value(got["outfit.colors"].value)
            assert outfit.value in r.prompt and "{" not in outfit.value
            assert any(template_matches(t, outfit.value) for t in outfit.options)
            if "tuxedo" in outfit.value:  # its palette restriction: dark schemes only
                assert "dark" in colors.tags["tone"]
            assert got["outfit.colors"].cls == "person.palette"
            assert got["outfit.colors"].label == "Colors"

    def test_discovery_lists_the_colors_and_the_example_reads_filled(self, dressed):
        info = discover(DRESSED)
        by = {c["id"]: c for c in info["choices"]}
        assert by["outfit"]["options"][0].startswith("a {main}") and by["outfit.colors"]["cls"] == "person.palette"
        assert "{" not in info["example"]

    def test_a_kept_filled_look_keeps_its_template_and_palette(self, dressed):
        first = draw_dressed(3)
        keep = {d.id: d.value for d in first.draws}
        again = draw_dressed(99, fixed=keep)
        assert again.prompt == first.prompt

    def test_removing_a_filled_look_removes_its_template(self, dressed):
        for seed in range(10):
            edits = {"outfit": {"remove": ["a navy technical T-shirt and white running shorts"]}}
            r = draw_dressed(seed, edits=edits, options=GeneratedOptions(None, program(), edits=edits))
            assert "running shorts" not in r.prompt

    def test_the_fix_judge_reads_filled_looks(self, dressed):
        from prompt_programs.fix import score_draw
        spy = FixSpy()
        for seed in range(6):
            score_draw(spy, draw_dressed(seed), "a woman")
        assert spy.items and not any("{" in it.value or "{" in it.state for it in spy.items)

    def test_a_revision_replays_a_template_draw(self, dressed, tmp_path):
        from prompt_programs.fluent import runtime_for
        entry = {"key": "d", "program": DRESSED, "loras": [], "params": {}, "mode": "prose",
                 "choices": discover(DRESSED)["choices"]}
        rt = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF)
        first = draw(DRESSED, 5, None, [], None, None, None, options=rt.options)
        rt2 = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF, revision=first.revision)
        assert draw(DRESSED, 5, None, [], None, None, None, options=rt2.options).prompt == first.prompt

    def test_a_kept_look_alone_keeps_its_colors(self, dressed):
        first = draw_dressed(4)
        look = next(d.value for d in first.draws if d.id == "outfit")
        for seed in range(6):
            assert draw_dressed(50 + seed, fixed={"outfit": look}).prompt == first.prompt

    def test_a_pinned_template_reads_filled_in_the_fix_judges_context(self, dressed):
        from prompt_programs.fix import score_draw
        spy = FixSpy()
        src = DRESSED.replace('emit("A woman wearing", outfit, ".")',
                              'pose = pick("pose", about="her pose", seed=["standing", "sitting"], label="Pose", phase=1)\n'
                              'emit("A woman wearing", outfit, ",", pose, ".")')
        r = draw(src, 2, {"outfit": ["a {main} technical T-shirt and {accent} running shorts"]}, [], None, None, None,
                 options=GeneratedOptions(None, program()))
        score_draw(spy, r, "a woman")
        assert "{" not in r.prompt and spy.items and not any("{" in it.state for it in spy.items)

    def test_a_replay_keeps_its_colors_after_the_palette_changes(self, dressed, tmp_path, monkeypatch):
        import dataclasses
        from prompt_programs.fluent import runtime_for
        entry = {"key": "d", "program": DRESSED, "loras": [], "params": {}, "mode": "prose",
                 "choices": discover(DRESSED)["choices"]}
        rt = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF)
        first = draw(DRESSED, 5, None, [], None, None, None, options=rt.options)
        pal = dressed.leaves["person.palette"]
        recolored = tuple(dataclasses.replace(v, roles={k: "chartreuse" for k in v.roles}) for v in pal.values)
        monkeypatch.setitem(dressed.leaves, "person.palette", dataclasses.replace(pal, values=recolored))
        rt2 = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF, revision=first.revision)
        assert draw(DRESSED, 5, None, [], None, None, None, options=rt2.options).prompt == first.prompt
        monkeypatch.delitem(dressed.leaves, "person.outfit.test")  # the outfit list itself removed
        rt3 = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF, revision=first.revision)
        assert "{" not in draw(DRESSED, 5, None, [], None, None, None, options=rt3.options).prompt

    def test_colors_turned_off_leave_the_look_without_them(self, dressed):
        edits = {"outfit.colors": {"off": True}}
        for seed in range(6):
            r = draw_dressed(seed, edits=edits, options=GeneratedOptions(None, program(), edits=edits))
            assert "{" not in r.prompt and not any(d.id == "outfit.colors" for d in r.draws)
            assert not any(c in r.prompt for c in ("navy", "red ", "black,"))

    def test_colors_show_whenever_the_outfit_does(self, dressed):
        by = {c["id"]: c for c in discover(DRESSED)["choices"]}
        assert "parent" not in by["outfit.colors"] and "when" not in by["outfit.colors"]

    def test_facet_filters_keep_their_own_pools_and_old_keys(self, dressed):
        def entry_with(where):
            src = DRESSED.replace('label="Outfit"', f'label="Outfit", where={where!r}')
            e = {"key": "f", "program": src, "loras": [], "params": {}, "mode": "prose",
                 "choices": discover(src)["choices"], "prompt": "a woman"}
            e["filters"] = {"outfit": [OUTFITS["values"][0]["text"]]}
            return e
        from prompt_programs.fluent import program_context
        spec = PickSpec("outfit", "Outfit", "what she wears", 1, "text", "pick", [], [], "person.outfit.test")
        a = GeneratedOptions(None, program_context(entry_with({"sport": "running"})))._where(spec, {})
        b = GeneratedOptions(None, program_context(entry_with({"sport": "formal"})))._where(spec, {})
        assert a[0] != b[0] and a[1] != b[1]  # revision keys and generated pools stay apart
        assert a[0].endswith("where {'sport': 'running'}")  # the key revisions recorded before

    def test_the_catalog_shows_parts_and_hides_the_palette(self, dressed):
        cat = dressed.catalog()
        line = next(ln for ln in cat.splitlines() if ln.startswith("- person.outfit.test"))
        assert "Colors vary separately" in line and "sport = running | formal" in line and "color_family = red" in line
        assert "- person.palette" not in cat


class TestLocalFacetWhere:

    def test_generator_examples_respect_a_templates_palette(self, dressed):
        opts = GeneratedOptions(None, program())
        leaf = dressed.leaves["person.outfit.test"]
        spec = PickSpec("outfit", "Outfit", "what she wears", 1, "text", "pick", [], [], leaf.id)
        for k in range(20):
            for ex in opts._examples(leaf, spec, f"k{k}"):
                if "tuxedo" in ex:
                    assert ex.split()[1] in ("navy", "black")  # dark schemes only

    async def test_a_facet_filter_narrows_in_code_and_routes_colors(self, dressed, tmp_path):
        src = DRESSED.replace('label="Outfit"', 'label="Outfit", where={"sport": "running", "color_family": "blue"}')
        entry = {"key": "w", "program": src, "loras": [], "params": {}, "mode": "prose",
                 "choices": discover(src)["choices"], "prompt": "a woman in blue running kit"}
        ask = FakeAsk(lambda v: True)
        await narrow_read(entry, NarrowCache(tmp_path), ask)
        assert not ask.calls  # no narrowing call: the tags decide
        # running looks whose main garment takes the color asked for: the white karate gi drops out
        assert entry["filters"]["outfit"] == [v["text"] for v in OUTFITS["values"]
                                              if "running" in v["tags"]["sport"] and "{main}" in v["text"]]
        assert entry["filters"]["outfit.colors"] == ["navy, white and gray"]
        from prompt_programs.fluent import program_context
        opts = GeneratedOptions(None, program_context(entry))
        for seed in range(6):
            r = draw(src, seed, None, [], None, None, None, options=opts)
            assert "tuxedo" not in r.prompt and "karate gi" not in r.prompt and "navy" in r.prompt
            opts.reset()


OLIVE = {**PALETTE, "values": [{"text": "olive, cream and tan", "tier": "typical",
                                "roles": {"main": "olive", "accent": "cream", "neutral": "tan"},
                                "tags": {"color_family": ["red"], "tone": ["dark"]}}]}
COATS = {**OUTFITS, "values": [{"text": "a {main} trench coat over a {accent} sweater", "tier": "typical",
                                "tags": {"sport": ["formal"]}}]}


class TestArticleTidy:
    """The emitted text's tidy writes "an olive trench coat" for a filled "a {main} trench
    coat": validation reads the value as the tidy writes it, so it isn't sent back to the
    writer as a value that "never appears" (it can't be repaired: the writer never wrote it)."""

    @pytest.fixture
    def olive(self, monkeypatch):
        v = vocabulary()
        monkeypatch.setitem(v.leaves, "person.palette", _leaf("person.palette", OLIVE))
        monkeypatch.setitem(v.leaves, "person.outfit.test", _leaf("person.outfit.test", COATS))
        return v


    def test_the_judge_and_the_highlight_find_the_value_as_emitted(self, olive):
        from prompt_programs.fix import mask, prompt_view
        from prompt_programs.program import realized_text
        from prompt_programs.runtime import run
        r = run(DRESSED, 11)
        text = realized_text(r.prompt)
        assert mask(text, "a olive trench coat over a cream sweater", "Outfit") == "A woman wearing [Outfit]."
        view = prompt_view(r)
        (s, e, cid), = view["spans"]
        assert cid == "outfit" and text[s:e] == "an olive trench coat over a cream sweater"


# --------------------------------------------------------------------------- the Colors id before US spelling

class TestOldColorsIds:
    """Builds before the US spelling named a look's Colors pick "<look>.colours". What they
    recorded (prepared programs, revisions, pins, kept values, edits, an agent's keep_choices)
    still loads and replays: those ids are read as ".colors"."""

    def _entry(self):
        return {"key": "d", "program": DRESSED, "loras": [], "params": {}, "mode": "prose", "prompt": "a woman",
                "choices": discover(DRESSED)["choices"]}

    @staticmethod
    def _older(rev):
        """A revision as an older build wrote it: its pool keys name the Colors pick ".colours"."""
        pools = {k.replace("outfit.colors", "outfit.colours"): v for k, v in rev["pools"].items()}
        assert pools != rev["pools"]
        return {**rev, "pools": pools}

    @pytest.fixture
    def realize(self, dressed, tmp_path, monkeypatch):
        """prep.realize as a run calls it (it builds its own runtime), drawing offline."""
        import prompt_programs.fluent as fluent
        monkeypatch.setattr(fluent, "settings", lambda: OFF)
        monkeypatch.setattr(fluent, "_profile_store", lambda pid: OptionStore(tmp_path))
        entry = self._entry()
        return lambda **kw: prep.realize(entry, **kw)

    def test_an_older_revision_replays_exactly(self, realize, dressed, monkeypatch):
        import dataclasses
        pal = dressed.leaves["person.palette"]
        recolored = dataclasses.replace(
            pal, values=tuple(dataclasses.replace(v, roles={k: "chartreuse" for k in v.roles}) for v in pal.values))
        replayed = 0
        for seed in range(8):
            first = realize(seed=seed)
            if "outfit.colors" not in {d.id for d in first.draws}:
                continue
            # the palette changes after the record: only the recorded pool gives the same colors
            monkeypatch.setitem(dressed.leaves, "person.palette", recolored)
            again = realize(seed=seed, revision=self._older(first.revision))
            assert again.prompt == first.prompt and "chartreuse" not in again.prompt
            monkeypatch.setitem(dressed.leaves, "person.palette", pal)
            replayed += 1
        assert replayed

    def test_older_pins_kept_values_and_edits_still_hold(self, realize):
        scheme = PALETTE["values"][1]["text"]
        look = OUTFITS["values"][0]["text"]
        for seed in range(6):
            r = realize(seed=seed, pins={"outfit": [look], "outfit.colours": [scheme]})
            assert next(d.value for d in r.draws if d.id == "outfit.colors") == scheme
            assert "navy technical T-shirt" in r.prompt
            off = realize(seed=seed, pins={"outfit": [look]}, edits={"outfit.colours": {"off": True}})
            assert not any(d.id.endswith(".colors") for d in off.draws) and "{" not in off.prompt
        kept = realize(seed=1, pins={"outfit": [look]}, fixed={"outfit.colours": scheme})
        assert next(d.value for d in kept.draws if d.id == "outfit.colors") == scheme

    def test_a_stored_older_program_loads_under_current_ids(self, tmp_path):
        from prompt_programs.store import ProgramStore
        store = ProgramStore(tmp_path)
        old = {"key": "a" * 32, "program": DRESSED, "filters": {"outfit.colours": ["navy, white and gray"], "outfit": ["x"]},
               "choices": [{"id": "outfit", "label": "Outfit"},
                           {"id": "woman.outfit.colours", "label": "Colours", "follows": "woman.outfit"},
                           {"id": "outfit.colours", "label": "Colors", "follows": "outfit"}]}
        store.put("a" * 32, old)
        got = store.get("a" * 32)
        assert [c["id"] for c in got["choices"]] == ["outfit", "woman.outfit.colors", "outfit.colors"]
        assert got["choices"][2]["follows"] == "outfit" and got["choices"][1]["follows"] == "woman.outfit"
        assert got["filters"] == {"outfit.colors": ["navy, white and gray"], "outfit": ["x"]}
        new = {**old, "filters": {"outfit": ["x"]}, "choices": [{"id": "outfit"}]}
        store.put("b" * 32, new)
        assert store.get("b" * 32) == new  # nothing old: read as stored

    def test_an_agents_older_keep_choices_name_the_colors(self):
        from routes.generation import pins_for_kept_choices
        entry = {"choices": [{"id": "outfit", "label": "Outfit"}, {"id": "outfit.colors", "label": "Colors"}]}
        assert pins_for_kept_choices(entry, {"outfit.colours": "navy, white and gray"}) == \
            {"outfit.colors": ["navy, white and gray"]}

    def test_revision_pool_keys_are_renamed_by_id_only(self):
        rev = {"id": "r", "pools": {
            "friends[2].outfit.colours: the colours of what she wears | outfit.colours=navy": 3,
            "outfit: what she wears | colours=red": 2, "weather: the colours of the sky": 1}}
        assert sorted(prep.current_revision(rev)["pools"]) == [
            "friends[2].outfit.colors: the colours of what she wears | outfit.colors=navy",
            "outfit: what she wears | colours=red", "weather: the colours of the sky"]
        assert prep.current_revision({"pools": {"a": 1}}) == {"pools": {"a": 1}}

    def test_an_older_program_with_old_facet_names_still_draws(self, tmp_path):
        """A program written against the old vocabulary (where={"colour_family": ...}, a "grey"
        shade) still draws: an unknown facet value matches nothing, so the whole list is used."""
        from prompt_programs.fluent import runtime_for
        src = ('outfit = pick("outfit", cls="person.outfit.casual", about="what she wears", seed=["a red T-shirt"], '
               'label="Outfit", phase=1, line=1, where={"colour_family": "grey"})\n'
               'hair = pick("hair", cls="person.hair_color", about="her hair colour", seed=["black"], label="Hair", '
               'phase=1, line=2, where={"shade": "grey"})\n'
               'emit("A woman with", hair, "hair wearing", outfit, ".")')
        entry = {"key": "o", "program": src, "loras": [], "params": {}, "mode": "prose", "prompt": "a woman",
                 "choices": discover(src)["choices"]}
        for seed in range(6):
            r = prep.realize(entry, seed=seed, runtime=runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF))
            assert r.prompt and "{" not in r.prompt


class TestSharesAndComposedLists:
    """A list may give its parts fixed shares of the draws, and a list may be composed of
    other lists' values (a face is two or three features)."""

    def test_a_parts_share_does_not_depend_on_how_many_values_it_has(self):
        look = vocabulary().get("camera.look")
        by_part = {}
        for v in look.values:
            by_part.setdefault(v.tags["intent"][0], []).append(v)
        total = sum(v.weight for v in look.values)
        assert abs(sum(v.weight for v in by_part["sharp"]) / total - 0.2) < 1e-9
        assert abs(sum(v.weight for v in by_part["soft_background"]) / total - 0.05) < 1e-9
        assert len(by_part["sharp"]) != len(by_part["soft_background"])

    def test_a_part_with_no_share_is_drawn_only_when_asked_for(self):
        selfie = vocabulary().get("camera.selfie_framing")
        group = [v for v in selfie.values if v.tags["kind"] == ["group"]]
        assert group and all(v.opt_in for v in group)
        drawn, standby = selfie.pool_values()
        assert not {v.text for v in group} & {v.text for v in drawn} and {v.text for v in group} <= {v.text for v in standby}
        asked, _ = selfie.pool_values([v.text for v in group])
        assert asked == group and all(v.weight > 0 for v in asked)

    def test_a_face_is_two_or_three_features_of_different_lists(self):
        v = vocabulary()
        face = v.get("person.face")
        parts = {lid: {x.text for x in lf.values} for lid, lf in v.leaves.items() if lid.startswith("person.feature.")}
        assert len(parts) == 9 and len(face.values) == 3000 and len({x.text for x in face.values}) == 3000
        assert face.listed and not any(v.get(lid).listed for lid in parts)
        assert [x.text for x in face.values] == [x.text for x in load().get("person.face").values]

    def test_a_face_fits_the_persons_age(self):
        v = vocabulary()
        face, age = v.get("person.face"), v.get("person.age_band")
        pool = [(x.text, x.weight) for x in face.values]

        def at(band):
            return {o for o, w in face.weigh(pool, [("life_stage", age.context_tags(band, "life_stage"))]) if w > 0}
        child, old = at("5-year-old"), at("75-year-old")
        lines = {x.text for x in face.values if "deep wrinkles" in x.text or "age spots" in x.text}
        assert lines and not lines & child and lines <= old
        assert {x.text for x in face.values if "baby-round" in x.text}.isdisjoint(old)
        # Removing what doesn't fit leaves the other faces their weight: nothing is scaled up to fill the gap.
        kept = dict(face.weigh(pool, [("life_stage", ("child",))]))
        assert all(kept[o] in (0.0, w) for o, w in pool)

    def test_a_feature_of_one_sex_is_drawn_only_for_that_sex(self):
        face = vocabulary().get("person.face")
        gendered = [x for x in face.values if x.tags["presentation"] != ["feminine", "masculine"]]
        assert gendered and all(x.opt_in and len(x.tags["presentation"]) == 1 for x in gendered)
        men = {x.text for x in face.matching({"presentation": "masculine"})}
        assert {x.text for x in gendered if x.tags["presentation"] == ["masculine"]} <= men
        assert not {x.text for x in gendered if x.tags["presentation"] == ["feminine"]} & men


class TestGrayingFollowsAge:
    """Gray hair is drawn as it is seen: never before thirty, seldom in the thirties, more with age."""
    SOME = {"salt-and-pepper", "gray-templed dark brown", "white-streaked black"}
    FULL = {"gray", "white"}

    def pool(self, band):
        from prompt_programs.vocab import vocabulary
        v = vocabulary()
        age = next(x for x in v.get("person.age_band").values if x.text == band)
        fams = tuple(age.tags["graying"]) + tuple("~" + f for f in (age.less_common.get("graying") or ()))
        leaf = v.get("person.hair_color")
        items = [(x.text, x.weight) for x in leaf.values if not x.opt_in]
        got = dict(leaf.weigh(items, [("graying", fams)]))
        total = sum(got.values())
        return {k: w / total for k, w in got.items()}

    def share(self, band, names):
        return sum(w for k, w in self.pool(band).items() if k in names)

    def test_nobody_under_thirty_is_gray(self):
        for band in ("15-year-old", "18-year-old", "20-year-old", "25-year-old"):
            assert self.share(band, self.SOME | self.FULL) == 0

    def test_it_grows_with_age(self):
        thirties, forties = self.share("30-year-old", self.SOME | self.FULL), self.share("40-year-old", self.SOME | self.FULL)
        fifties, sixties = self.share("50-year-old", self.SOME | self.FULL), self.share("60-year-old", self.SOME | self.FULL)
        eighties = self.share("80-year-old", self.FULL)
        assert 0 < thirties < 0.05 < forties < fifties < sixties and eighties > 0.5
        assert self.share("35-year-old", self.FULL) == 0

    def test_the_users_words_for_gray_hair_win_at_any_age(self):
        """A list narrowed to gray for a young person keeps it: a context never empties a pool."""
        from prompt_programs.vocab import vocabulary
        leaf = vocabulary().get("person.hair_color")
        narrowed = [(x.text, x.weight if x.text == "gray" else 0.0) for x in leaf.values if not x.opt_in]
        got = dict(leaf.weigh(narrowed, [("graying", ("none",))]))
        assert got["gray"] > 0

    def test_the_nose_list_names_no_caricature(self):
        from prompt_programs.vocab import vocabulary
        noses = " ".join(x.text for x in vocabulary().get("person.feature.nose").values)
        for word in ("hooked", "points downward", "prominent", "slit-like", "widens a lot"):
            assert word not in noses


class TestAgeList:
    """One value per year, and only the ages under 18 are opt-in."""

    def test_every_year_is_unique_and_only_minors_are_opt_in(self):
        from prompt_programs.vocab import vocabulary
        leaf = vocabulary().get("person.age_band")
        ages = [0 if v.text == "newborn" else int(v.text.split("-")[0]) for v in leaf.values]
        assert ages == list(range(111))
        assert all(v.opt_in == (a < 18) and v.minor == (a < 18) for v, a in zip(leaf.values, ages))


class TestOutfitsKnowWhoTheyAreFor:
    """Every outfit says who it is conventionally worn by, so a man asked for by name isn't
    drawn a dress. An outfit anyone wears carries both parts."""

    OUTFITS = ("athletic", "casual", "cold_weather", "fantasy", "formal", "period", "scifi", "sleep_lounge", "smart", "summer")
    # Checked by hand against the lists: worn by women, never left for a man.
    FEMININE = {
        "person.outfit.casual": ["a {main} knee-length jersey dress with short sleeves",
                                 "a {main} sweatshirt and {neutral} jersey leggings"],
        "person.outfit.cold_weather": ["a {main} teddy-fleece coat over a {accent} long-sleeved jersey dress and {neutral} wool tights"],
        "person.outfit.smart": ["a {main} blouse and a {neutral} pencil skirt", "a {accent} jersey top and a {main} pantsuit"],
        "person.outfit.formal": ["a {main} satin gown with a full skirt", "a {main} crepe jumpsuit with wide tailored legs"],
        "person.outfit.summer": ["a {main} cotton sundress with a gathered waist"],
        "person.outfit.sleep_lounge": ["a white cotton nightgown with long sleeves"],
        "person.outfit.period": ["a {main} wool kirtle over a cream linen shift"],
        "person.outfit.fantasy": ["a {main} hooded cloak over a {neutral} wool dress"],
    }
    # Worn by anyone: left for both.
    ANYONE = {
        "person.outfit.casual": ["a {main} cotton T-shirt and straight blue jeans"],
        "person.outfit.smart": ["a {main} wool suit with a {accent} shirt"],
        "person.outfit.athletic": ["a white cotton karate gi with matching pants"],
        "person.outfit.scifi": ["a {main} flight jumpsuit with {accent} reinforced seams"],
    }

    def leaves(self):
        v = vocabulary()
        return [v.get(f"person.outfit.{n}") for n in self.OUTFITS]

    def test_every_outfit_carries_a_presentation(self):
        for leaf in self.leaves():
            assert leaf.local_facets["presentation"] == ("feminine", "masculine"), leaf.id
            for x in leaf.values:
                got = x.tags.get("presentation")
                assert got and set(got) <= {"feminine", "masculine"}, (leaf.id, x.text)

    def test_the_masculine_part_leaves_no_dresses(self):
        from prompt_programs.vocab import tags_match
        v = vocabulary()
        for lid, texts in self.FEMININE.items():
            leaf = v.get(lid)
            men = {x.text for x in leaf.values if tags_match(x.tags, {"presentation": "masculine"})}
            women = {x.text for x in leaf.values if tags_match(x.tags, {"presentation": "feminine"})}
            for t in texts:
                assert leaf.value(t) is not None, t
                assert t not in men and t in women, t
        for lid, texts in self.ANYONE.items():
            leaf = v.get(lid)
            for t in texts:
                assert set(leaf.value(t).tags["presentation"]) == {"feminine", "masculine"}, t


class TestShortForms:
    """The chooser shows a chosen value in a small pill, so every value the person, camera and
    light builders draw from has a name short enough for one. A face is composed of pieces,
    each with its own short form, so the composed list is left out."""

    ROOTS = ("person.", "camera.", "lighting.")
    LIMIT = 24

    def leaves(self):
        return [lf for lf in vocabulary().leaves.values()
                if lf.id.startswith(self.ROOTS) and lf.id != "person.face"]

    def test_every_long_value_has_a_short_form_that_fits(self):
        from prompt_programs.vocab import is_template
        leaves = self.leaves()
        assert len(leaves) > 40
        for leaf in leaves:
            for v in leaf.values:
                if v.short:
                    assert 0 < len(v.short) <= self.LIMIT, (leaf.id, v.short)
                    assert not is_template(v.short) and "{" not in v.short, (leaf.id, v.short)
                    assert v.short.split(" ")[0].lower() not in ("a", "an", "the"), (leaf.id, v.short)
                else:
                    assert len(v.text) <= self.LIMIT, (leaf.id, v.text)

    def test_the_loader_reads_the_short_form_and_falls_back_to_the_value(self):
        v = vocabulary()
        outfit = v.get("person.outfit.casual")
        assert outfit.short("a {main} flannel shirt and {neutral} denim jeans") == "flannel shirt and jeans"
        # A drawn outfit is the template filled with colors; its pill names no colors.
        assert outfit.short("a red flannel shirt and navy denim jeans") == "flannel shirt and jeans"
        light = v.get("lighting.natural")
        assert light.short("low golden-hour sun raking across the scene") == "golden hour"
        assert v.get("person.eye_color").short("hazel") == "hazel"
        assert outfit.short("something the list never had") == "something the list never had"
        assert any(x.get("short") for lf in v.to_dict()["leaves"] if lf["id"] == "lighting.natural" for x in lf["values"])


class TestDogBreeds:
    """A teaching list: about two hundred real breeds nobody could name from memory, browsed by
    breed group, with size to narrow by and the common breeds drawn most."""

    def test_about_two_hundred_breeds_each_once(self):
        leaf = vocabulary().get("animal.dog_breed")
        texts = [v.text for v in leaf.values]
        assert 200 <= len(texts) <= 240
        assert len({t.lower() for t in texts}) == len(texts)

    def test_every_breed_sits_in_one_group_with_a_size(self):
        from prompt_programs.fluent import list_groups
        leaf = vocabulary().get("animal.dog_breed")
        groups, sizes = leaf.local_facets["breed_group"], leaf.local_facets["size"]
        assert {"herding", "hound", "sighthound", "terrier", "toy", "working", "sporting"} <= set(groups)
        for v in leaf.values:
            assert len(v.tags["breed_group"]) == 1 and v.tags["breed_group"][0] in groups, v.text
            assert len(v.tags["size"]) == 1 and v.tags["size"][0] in sizes, v.text
        texts = [v.text for v in leaf.values]
        by_group = list_groups(leaf, texts)["breed_group"]
        assert sorted(o for os in by_group.values() for o in os) == sorted(texts)

    def test_common_breeds_are_typical_and_rare_ones_are_not(self):
        leaf = vocabulary().get("animal.dog_breed")
        tier = {v.text: v.tier for v in leaf.values}
        for t in ("Labrador retriever", "golden retriever", "German shepherd", "beagle", "French bulldog"):
            assert tier[t] == "typical", t
        for t in ("Azawakh", "Lancashire heeler", "Kishu Ken", "Bergamasco", "otterhound"):
            assert tier[t] == "unusual", t
        assert sum(1 for x in tier.values() if x == "typical") < len(tier) // 5
