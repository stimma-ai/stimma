"""Fluent vocabulary: curated lists picks bind to with cls=, their pools, the picker's
view of them, the writer's catalogue, and article agreement in emitted text."""

import pytest

from prompt_programs import prepare as prep
from prompt_programs.draws import NullJudge, PickSpec, draw
from prompt_programs.fluent import pool_options
from prompt_programs.judge import FluentSettings
from prompt_programs.options import (
    GeneratedOptions, OptionFiller, OptionStore, ProgramContext, gen_key, generated_pick, generation_messages,
)
from prompt_programs.runtime import ProgramError, discover, run, tidy_text
from prompt_programs.vocab import OPEN_SHARE, TIER_WEIGHTS, load, vocabulary

PORTRAIT = '''
eth = pick("eth", cls="person.ethnicity", about="her ethnicity", seed=["Korean"], label="Ethnicity", phase=1, line=1)
eyes = pick("eyes", cls="person.eye_color", about="her eye colour", seed=["hazel"], label="Eyes", phase=2, line=1)
expr = pick("expr", cls="person.expression", about="her expression", seed=["a soft smile"], label="Expression", phase=2, line=1)
emit("A portrait of a", eth, "woman with", eyes, "eyes and", expr, ".")
'''

OFF = FluentSettings(generate_options=False)


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
        assert plain and fantasy - plain  # fantasy-only colours appear only in fantasy

    def test_examples_are_a_stable_spread(self):
        leaf = vocabulary().get("person.expression")
        a, b = leaf.examples("k"), leaf.examples("k")
        assert a == b and len(a) == 10 and len(set(a)) == 10 and leaf.examples("other") != a

    def test_the_catalogue_lists_person_ids_without_sample_values(self):
        cat = vocabulary().catalogue()
        assert "- person.eye_color: adjective" in cat and "interior_space" not in cat
        assert "hazel" not in cat  # no fixed samples: they'd end up in every program's text

    def test_the_writer_reads_the_catalogue(self):
        assert "{vocabulary}" not in prep._INSTRUCTIONS and "person.eye_color" in prep._INSTRUCTIONS

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
        assert v.resolve("person.face") is None and v.resolve("interior.bedroom") is None
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
            r = draw(PORTRAIT, seed, None, [], None, None, None, options=opts, judge=NullJudge())
            got = {d.id: d for d in r.draws}
            assert got["eth"].value in {x.text for x in v.get("person.ethnicity").values}
            assert got["eyes"].value in {x.text for x in v.get("person.eye_color").eligible()}
            assert got["eyes"].cls == "person.eye_color"
            opts.reset()

    def test_a_list_the_vocabulary_lost_draws_unbound(self):
        src = PORTRAIT.replace("person.eye_color", "person.gone")
        r = draw(src, 1, None, [], None, None, None, options=GeneratedOptions(None, program()), judge=NullJudge())
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
        rt = runtime_for(entry, store=OptionStore(tmp_path), judge=NullJudge(), cfg=OFF)
        first = draw(PORTRAIT, 12, None, [], None, None, None, options=rt.options, judge=NullJudge())
        rev = first.revision
        assert any(isinstance(v, list) for v in rev["pools"].values())  # bound pools are recorded whole
        v = vocabulary()
        for lid in ("person.expression", "person.eye_color", "person.ethnicity"):  # a new vocabulary release
            leaf = v.leaves[lid]
            monkeypatch.setitem(v.leaves, lid, dataclasses.replace(leaf, values=tuple(reversed(leaf.values[1:]))))
        rt2 = runtime_for(entry, store=OptionStore(tmp_path), judge=NullJudge(), cfg=OFF, revision=rev)
        again = draw(PORTRAIT, 12, None, [], None, None, None, options=rt2.options, judge=NullJudge())
        assert again.prompt == first.prompt

    def test_a_revision_replays_after_its_list_is_removed(self, tmp_path, monkeypatch):
        from prompt_programs.fluent import runtime_for
        entry = {"key": "p", "program": PORTRAIT, "loras": [], "params": {}, "mode": "prose",
                 "choices": discover(PORTRAIT)["choices"]}
        rt = runtime_for(entry, store=OptionStore(tmp_path), judge=NullJudge(), cfg=OFF)
        first = draw(PORTRAIT, 0, None, [], None, None, None, options=rt.options, judge=NullJudge())
        monkeypatch.delitem(vocabulary().leaves, "person.eye_color")
        rt2 = runtime_for(entry, store=OptionStore(tmp_path), judge=NullJudge(), cfg=OFF, revision=first.revision)
        again = draw(PORTRAIT, 0, None, [], None, None, None, options=rt2.options, judge=NullJudge())
        assert again.prompt == first.prompt

    def test_bound_and_unbound_pools_never_share_generated_options(self):
        a = PickSpec("x", "X", "her expression", 2, "text", "pick", [], [])
        b = PickSpec("x", "X", "her expression", 2, "text", "pick", [], [], "person.expression")
        assert gen_key(a, {}, "sig", "prose", True) != gen_key(b, {}, "sig", "prose", True, cls=b.cls)

    def test_user_edits_apply(self, tmp_path):
        s = bound_spec("person.eye_color")
        edits = {"x": {"remove": ["blue"], "add": ["silver-flecked grey"]}}
        pool = GeneratedOptions(OptionStore(tmp_path), program(), edits=edits).get(s, {})
        assert "blue" not in pool.items and pool.items[-1] == "silver-flecked grey"


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
    ])
    def test_a_and_an_follow_the_next_word(self, text, want):
        assert tidy_text([text]) == want


# --------------------------------------------------------------------------- where=: narrowing a list

from prompt_programs.narrow import NarrowCache, narrow_entry, parse_subset  # noqa: E402

YOUNG = '''
age = pick("age", cls="person.age_band", where="young", about="her age", seed=["20–24"], label="Age", phase=1, line=1)
eyes = pick("eyes", cls="person.eye_color", about="her eye colour", seed=["hazel"], label="Eyes", phase=1, line=1)
emit("A young woman, aged", age, ", with", eyes, "eyes.")
'''


def young_entry(prompt="a young woman with pretty eyes"):
    info = discover(YOUNG)
    return {"key": "y", "program": YOUNG, "loras": [], "params": {}, "mode": "prose", "choices": info["choices"],
            "prompt": prompt}


class FakeAsk:
    """Answers a narrowing question with the values for which `keep` is true, and the
    prompt-reading question with `read` ({choice id: words})."""

    def __init__(self, keep=None, reply=None, read=None):
        self.keep, self.reply, self.read, self.calls, self.reads = keep, reply, read or {}, [], []

    async def __call__(self, messages, project_id, max_tokens):
        import json
        if "find the words in it" in messages[0]["content"]:
            self.reads.append(messages)
            return json.dumps(self.read)
        self.calls.append(messages)
        if self.reply is not None:
            return self.reply
        import json, re
        values = json.loads(re.search(r"\n(\[.*\])\n", messages[1]["content"], re.S).group(1))
        return json.dumps([v for v in values if self.keep(v)])


def young(v):
    return v.split("–")[0].isdigit() and 18 <= int(v.split("–")[0]) < 35


class TestWhere:
    def test_where_is_recorded_on_the_choice(self):
        by = {c["id"]: c for c in discover(YOUNG)["choices"]}
        assert by["age"]["where"] == "young" and "where" not in by["eyes"]

    def test_parse_subset_keeps_the_lists_order_and_ignores_strangers(self):
        assert parse_subset('Sure: ["25–29", "18–19", "a teenager"]', ["18–19", "20–24", "25–29"]) == ["18–19", "25–29"]
        assert parse_subset("no list here", ["a"]) is None
        assert parse_subset("[]", ["a"]) == []

    async def test_an_entry_is_narrowed_and_the_answer_cached(self, tmp_path):
        entry, ask = young_entry(), FakeAsk(young)
        await narrow_entry(entry, NarrowCache(tmp_path), ask)
        assert entry["filters"]["age"] == [v for v in [x.text for x in vocabulary().get("person.age_band").eligible()] if young(v)]
        assert "eyes" not in entry["filters"]  # no where=, no narrowing
        by = {c["id"]: c for c in entry["choices"]}
        assert by["age"]["options"] == entry["filters"]["age"]
        again = young_entry()
        await narrow_entry(again, NarrowCache(tmp_path), ask)
        assert len(ask.calls) == 1 and again["filters"] == entry["filters"]  # "young" on ages: asked once

    async def test_nothing_fitting_or_an_unreadable_answer_leaves_the_pick_unbound(self, tmp_path):
        for ask in (FakeAsk(lambda v: False), FakeAsk(reply="I can't tell.")):
            entry = young_entry()
            notes = await narrow_entry(entry, NarrowCache(tmp_path / str(id(ask))), ask)
            by = {c["id"]: c for c in entry["choices"]}
            assert entry["filters"]["age"] == [] and "cls" not in by["age"] and notes

    async def test_the_prompts_own_words_narrow_a_pick_the_writer_left_open(self, tmp_path):
        src = YOUNG.replace(', where="young"', "")  # the writer forgot where=
        entry = {"key": "b", "program": src, "loras": [], "params": {}, "mode": "prose",
                 "choices": discover(src)["choices"], "prompt": "a young woman with brown eyes"}
        ask = FakeAsk(lambda v: "brown" in v or young(v), read={"age": "young woman", "eyes": "brown eyes"})
        await narrow_entry(entry, NarrowCache(tmp_path), ask)
        assert entry["filters"]["eyes"] and all("brown" in v for v in entry["filters"]["eyes"])
        assert entry["filters"]["age"] and all(young(v) for v in entry["filters"]["age"])
        by = {c["id"]: c for c in entry["choices"]}
        assert by["age"]["where"] == "young woman" and by["eyes"]["where"] == "brown eyes"
        assert len(ask.reads) == 1  # one reading per prompt

    async def test_words_the_prompt_doesnt_contain_are_ignored(self, tmp_path):
        entry = young_entry("a woman reading")
        ask = FakeAsk(young, read={"eyes": "green eyes"})  # invented: not in the prompt
        await narrow_entry(entry, NarrowCache(tmp_path), ask)
        assert "eyes" not in entry["filters"] and entry["filters"]["age"]  # age still narrowed by where=

    async def test_a_bound_wildcard_narrows_by_its_own_words(self, tmp_path):
        entry = young_entry()
        for c in entry["choices"]:
            if c["id"] == "eyes":
                c["wildcard"] = "dark eyes"
        await narrow_entry(entry, NarrowCache(tmp_path), FakeAsk(lambda v: "brown" in v))
        assert entry["filters"]["eyes"] and all("brown" in v for v in entry["filters"]["eyes"])

    async def test_draws_and_pools_keep_to_the_subset(self, tmp_path):
        from prompt_programs.fluent import runtime_for
        entry = young_entry()
        await narrow_entry(entry, NarrowCache(tmp_path), FakeAsk(young))
        rt = runtime_for(entry, store=OptionStore(tmp_path / "o"), judge=NullJudge(), cfg=OFF)
        for seed in range(8):
            r = draw(YOUNG, seed, None, [], None, None, None, options=rt.options, judge=NullJudge())
            assert young(next(d for d in r.draws if d.id == "age").value)
            rt.options.reset()
        out = pool_options(entry, store=OptionStore(tmp_path / "o"), cfg=OFF)
        assert out["options"]["age"] and all(young(v) for v in out["options"]["age"])

    async def test_an_unbound_fallback_generates_within_the_words(self, tmp_path):
        from prompt_programs.fluent import program_context
        entry = young_entry()
        await narrow_entry(entry, NarrowCache(tmp_path), FakeAsk(lambda v: False))
        store = OptionStore(tmp_path / "o")
        filler = OptionFiller(store, FakeGen())
        opts = GeneratedOptions(store, program_context(entry), filler=filler)
        spec = PickSpec("age", "Age", "her age", 1, "text", "pick", ["20–24"], [], "person.age_band")
        pool = opts.get(spec, {})
        assert pool.items == ["20–24"]  # its seed, while generated options are written
        job = filler._jobs[opts.queued[0]][1]
        assert 'own words: "young"' in generation_messages(job)[1]["content"]

    async def test_an_open_list_generates_from_the_subset_with_the_words_as_a_rule(self, tmp_path):
        from prompt_programs.fluent import program_context
        src = YOUNG.replace('cls="person.age_band", where="young"', 'cls="person.expression", where="happy"')
        info = discover(src)
        entry = {"key": "h", "program": src, "loras": [], "params": {}, "mode": "prose", "choices": info["choices"]}
        await narrow_entry(entry, NarrowCache(tmp_path), FakeAsk(lambda v: "smile" in v or "grin" in v))
        store = OptionStore(tmp_path / "o")
        filler = OptionFiller(store, FakeGen())
        opts = GeneratedOptions(store, program_context(entry), filler=filler)
        spec = PickSpec("age", "Age", "her age", 1, "text", "pick", [], [], "person.expression")
        pool = opts.get(spec, {})
        assert pool.items and all(("smile" in v or "grin" in v) for v in pool.items)
        job = filler._jobs[opts.queued[0]][1]
        assert job.examples and all(("smile" in v or "grin" in v) for v in job.examples)
        assert 'own words: "happy"' in generation_messages(job)[1]["content"]
