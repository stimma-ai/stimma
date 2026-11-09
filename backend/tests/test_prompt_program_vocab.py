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
        assert eyes.value == "hazel" and not eyes.cls  # its seed


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
    ])
    def test_a_and_an_follow_the_next_word(self, text, want):
        assert tidy_text([text]) == want
