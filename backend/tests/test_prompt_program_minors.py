"""Fluent's age policy: under-18 ages are drawn only when asked for, a person under 18 draws
no adult-coded looks from the vocabulary, and the user's own lists and wildcards are theirs.
Adults are not limited in any way."""

import json
import re

import pytest

from prompt_programs.draws import LiteralOptions, PickSpec, draw, person_of
from prompt_programs.fluent import pool_options, program_context, runtime_for
from prompt_programs.judge import FluentSettings
from prompt_programs.narrow import _SYSTEM, NarrowCache, mark_pending, messages_for, narrow_entry
from prompt_programs.options import (
    GeneratedOptions, OptionFiller, OptionStore, ProgramContext, gen_key, generation_messages, program_minors,
)
from prompt_programs.runtime import discover
from prompt_programs.vocab import AGE_LIST, load, minor_ages, template_matches, vocabulary

OFF = FluentSettings(generate_options=False)
SEEDS = range(300)


def ages():
    return vocabulary().get(AGE_LIST)


def is_minor(text):
    v = ages().value(text)
    return v is not None and v.minor


def adult_only(cls):
    return [v.text for v in vocabulary().get(cls).eligible() if v.adult_only]


def coded(value, cls):
    """Whether a drawn (filled) value is one of the list's adult-only values."""
    return any(template_matches(t, str(value)) for t in adult_only(cls))


ONE = '''
age = pick("age", cls="person.age_band", about="her age", seed=["25–29-year-old"], label="Age", phase=1, line=1)
outfit = pick("outfit", cls="person.outfit.summer", about="what she wears at the beach", seed=["a swimsuit"], label="Outfit", phase=1, line=1)
expr = pick("expr", cls="person.expression", about="her expression", seed=["a smile"], label="Expression", phase=1, line=1)
emit("A", age, "person at the beach wearing", outfit, "with", expr, ".")
'''

NO_AGE = '''
outfit = pick("outfit", cls="person.outfit.summer", about="what she wears at the beach", seed=["a swimsuit"], label="Outfit", phase=1, line=1)
expr = pick("expr", cls="person.expression", about="her expression", seed=["a smile"], label="Expression", phase=1, line=1)
emit("A 10-year-old at the beach wearing", outfit, "with", expr, ".")
'''

TWO = '''
kage = pick("kid.age", cls="person.age_band", about="the child's age", seed=["8–10-year-old"], label="Age", phase=1, line=1)
kout = pick("kid.outfit", cls="person.outfit.summer", about="what the child wears", seed=["a swimsuit"], label="Outfit", phase=1, line=1)
kexp = pick("kid.expr", cls="person.expression", about="the child's expression", seed=["a smile"], label="Expression", phase=1, line=1)
mage = pick("mother.age", cls="person.age_band", about="the mother's age", seed=["35–39-year-old"], label="Age", phase=1, line=1)
mout = pick("mother.outfit", cls="person.outfit.summer", about="what the mother wears", seed=["a swimsuit"], label="Outfit", phase=1, line=1)
mexp = pick("mother.expr", cls="person.expression", about="the mother's expression", seed=["a smile"], label="Expression", phase=1, line=1)
emit("A", kage, "child in", kout, "with", kexp, "beside a", mage, "mother in", mout, "with", mexp, ".")
'''


def entry_of(src, prompt="", **extra):
    return {"key": "k", "program": src, "loras": [], "params": {}, "mode": "prose", "prompt": prompt,
            "choices": discover(src)["choices"], **extra}


def draws_of(entry, tmp_path, seeds=SEEDS, pins=None, edits=None, fixed=None):
    rt = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF, edits=edits)
    for seed in seeds:
        r = draw(entry["program"], seed, pins, [], None, fixed, edits, options=rt.options)
        rt.options.reset()
        yield {d.id: d for d in r.draws}


class ModelAsk:
    """Answers narrowing the way a model following the instructions should: `ages` maps the
    words to the age bands it would keep; `read` is the prompt reading's reply."""

    def __init__(self, ages_for=None, read=None):
        self.ages_for, self.read, self.subsets = ages_for or {}, read or {}, []

    async def __call__(self, messages, project_id, max_tokens):
        if "find the words in it" in messages[0]["content"]:
            return json.dumps(self.read)
        self.subsets.append(messages)
        values = json.loads(re.search(r"\n(\[.*?\])\n", messages[1]["content"], re.S).group(1))
        phrase = re.search(r'Which of these fit "(.*?)"', messages[1]["content"]).group(1)
        keep = self.ages_for[phrase]
        return json.dumps([v for v in values if keep(v)])


def start(v):
    return int(v.split("–")[0])


ADULT = lambda v: start(v) >= 18                    # noqa: E731  "a woman", "a girl" alone
YOUNG_ADULT = lambda v: 18 <= start(v) < 30         # noqa: E731
CHILD = lambda v: 3 <= start(v) <= 11               # noqa: E731  "a little girl"
TEEN = lambda v: 13 <= start(v) <= 18               # noqa: E731  "a teenage couple"
TEN = lambda v: start(v) == 8                       # noqa: E731  "a 10-year-old"


# --------------------------------------------------------------------------- the data

class TestTheMarkers:
    def test_every_age_under_18_is_opt_in_and_no_adult_age_is(self):
        for v in ages().values:
            assert v.opt_in == v.minor, v.text
        assert minor_ages([v.text for v in ages().values]) == tuple(v.text for v in ages().values if v.minor)
        assert not is_minor("18–19-year-old") and is_minor("15–17-year-old") and is_minor("0–2-year-old")

    def test_adult_coded_values_are_tagged_in_the_person_lists_only(self):
        v = vocabulary()
        tagged = {lid: [x.text for x in lf.values if x.adult_only] for lid, lf in v.leaves.items()}
        assert sum(map(len, tagged.values())) == 24
        assert all(lid.startswith("person.") for lid, t in tagged.items() if t)
        assert "a {main} string bikini with a triangle top and tie-side bottoms" in tagged["person.outfit.summer"]
        assert "a sultry expression with heavy eyelids and softly parted lips" in tagged["person.expression"]
        # ordinary swimwear and sportswear children wear are not tagged
        for text in ("a {main} one-piece swimsuit with a square neckline", "a {main} bikini with a high-waisted bottom"):
            assert not v.get("person.outfit.summer").value(text).adult_only
        assert not any(x.adult_only for x in v.get("person.outfit.athletic").values)
        assert not any(x.opt_in for lid, lf in v.leaves.items() if lid != AGE_LIST for x in lf.values)

    def test_the_markers_reach_the_browser_and_the_content_hash(self, tmp_path):
        import shutil
        from prompt_programs.vocab import ROOT
        d = vocabulary().to_dict()
        age = next(lf for lf in d["leaves"] if lf["id"] == AGE_LIST)
        assert [x.get("opt_in", False) for x in age["values"]] == [x.minor for x in ages().values]
        summer = next(lf for lf in d["leaves"] if lf["id"] == "person.outfit.summer")
        assert sum(1 for x in summer["values"] if x.get("adult_only")) == 3
        shutil.copytree(ROOT, tmp_path / "v")
        p = tmp_path / "v" / "person" / "expression.json"
        raw = json.loads(p.read_text("utf-8"))
        raw["values"][0]["adult_only"] = True
        p.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", "utf-8")
        assert load((tmp_path / "v",)).version != vocabulary().version  # a marker change re-keys programs

    def test_person_of_scopes_a_pick_to_its_person(self):
        assert person_of("friends[2].age") == "friends[2]" == person_of("friends[2].outfit.colours")
        assert person_of("man.outfit") == "man" and person_of("outfit") == "" == person_of("outfit.colours")


# --------------------------------------------------------------------------- rule 1: never unasked

class TestUnasked:
    def test_no_age_stated_never_draws_under_18(self, tmp_path):
        got = [d["age"].value for d in draws_of(entry_of(ONE), tmp_path)]
        assert not any(map(is_minor, got)) and len(set(got)) > 8   # adults still vary

    def test_without_the_options_service_too(self):
        for seed in SEEDS:
            r = draw(ONE, seed, None, [], None, None, None, options=LiteralOptions())
            assert not is_minor(next(d.value for d in r.draws if d.id == "age"))

    async def test_skipped_or_failed_narrowing_draws_adults(self, tmp_path):
        skipped = entry_of(ONE, "a person at the beach")
        assert mark_pending(skipped)
        unreadable = entry_of(ONE, "a person at the beach")

        async def broken(messages, project_id, max_tokens):
            raise RuntimeError("down")
        await narrow_entry(unreadable, NarrowCache(tmp_path / "n"), broken)
        assert unreadable["narrow_pending"]
        for e in (skipped, unreadable):
            assert not program_minors(e)
            assert not any(is_minor(d["age"].value) for d in draws_of(e, tmp_path / "o", range(120)))

    def test_standby_ages_are_in_the_pool_at_weight_zero(self, tmp_path):
        opts = GeneratedOptions(OptionStore(tmp_path), program_context(entry_of(ONE)))
        pool = opts.get(PickSpec("age", "Age", "her age", 1, "text", "pick", [], [], AGE_LIST), {})
        w = dict(zip(pool.items, pool.weights))
        assert {o for o, x in w.items() if x == 0} == {v.text for v in ages().values if v.minor}
        assert all(x > 0 for o, x in w.items() if not is_minor(o))

    def test_a_pool_of_only_standby_values_draws_nothing_unpinned(self):
        src = 'a = pick("a", cls="person.age_band", about="age", seed=["x"], label="Age", phase=1)\nemit(a)'
        from prompt_programs.draws import DrawAborted
        young = [v.text for v in ages().values if v.minor]
        edits = {"a": {"remove": [v.text for v in ages().values if not v.minor]}}
        ctx = program_context(entry_of(src))
        with pytest.raises(DrawAborted):
            draw(src, 1, None, [], None, None, edits, options=GeneratedOptions(None, ctx, edits=edits))
        r = draw(src, 1, {"a": young[2:4]}, [], None, None, edits, options=GeneratedOptions(None, ctx, edits=edits))
        assert r.draws[0].value in young[2:4]


    def test_an_old_revision_pool_draws_no_unasked_age(self, tmp_path):
        """A revision recorded before ages under 18 were opt-in holds them at a positive weight."""
        e = entry_of(ONE)
        first = draw(ONE, 1, None, [], None, None, None,
                     options=runtime_for(e, store=OptionStore(tmp_path), cfg=OFF).options)
        rev = json.loads(json.dumps(first.revision))
        key = next(k for k in rev["pools"] if k.startswith("age:"))
        rev["pools"][key] = [[v.text, 1.0] for v in ages().values]
        got = []
        rt = runtime_for(e, store=OptionStore(tmp_path), cfg=OFF, revision=rev)
        for seed in range(150):
            r = draw(ONE, seed, None, [], None, None, None, options=rt.options)
            rt.options.reset()
            got.append(next(d.value for d in r.draws if d.id == "age"))
        assert not any(map(is_minor, got))
        # an image that really had an age under 18 (the record keeps it) replays it exactly
        r = draw(ONE, 3, None, [], None, {"age": "8–10-year-old"}, None,
                 options=runtime_for(e, store=OptionStore(tmp_path), cfg=OFF, revision=rev).options)
        assert next(d.value for d in r.draws if d.id == "age") == "8–10-year-old"


# --------------------------------------------------------------------------- narrowing: asked, and "a girl"

class TestNarrowing:
    def test_the_narrowing_model_is_told_a_girl_alone_is_no_child(self):
        assert '"A girl" or "a boy" alone is a' in _SYSTEM and "young adult" in _SYSTEM
        assert "a boy or a girl is under 18" not in _SYSTEM
        user = messages_for(ages(), "girl", [v.text for v in ages().eligible()], "her age")[1]["content"]
        listed = json.loads(user.rsplit(": ", 1)[1])
        assert listed == [v.text for v in ages().values if v.minor]  # the opt-in values, named as such
        assert "only when the description asks for them" in user
        assert "only when asked" not in messages_for(vocabulary().get("person.eye_color"), "dark", ["brown"])[1]["content"]

    def test_the_reader_quotes_the_kind_of_person_for_their_age(self):
        from prompt_programs.narrow import _READ_SYSTEM
        assert '"two kids"' in _READ_SYSTEM and "copy it for their age" in _READ_SYSTEM

    def test_the_writer_is_told_too(self):
        from prompt_programs import prepare as prep
        assert '"A girl"\n  or "a boy" alone is a young adult' in prep._INSTRUCTIONS
        assert 'never choose those for anyone else' in prep._INSTRUCTIONS

    @pytest.mark.parametrize("prompt,words,keep,minor", [
        ("a girl in a cafe", "girl", YOUNG_ADULT, False),
        ("a boy on a skateboard", "boy", YOUNG_ADULT, False),
        ("a woman at the beach", "woman", ADULT, False),
        ("a little girl at a birthday party", "little girl", CHILD, True),
        ("a teenage boy at prom", "teenage boy", TEEN, True),
    ])
    async def test_asked_for_ages_and_a_girl(self, tmp_path, prompt, words, keep, minor):
        e = entry_of(ONE, prompt)
        await narrow_entry(e, NarrowCache(tmp_path / "n"), ModelAsk({words: keep}, read={"age": words}))
        assert bool(program_minors(e)) is minor
        got = [d for d in draws_of(e, tmp_path / "o", range(150))]
        assert all(keep(d["age"].value) for d in got)
        assert any(is_minor(d["age"].value) for d in got) is minor
        if minor:
            assert not any(coded(d["outfit"].value, "person.outfit.summer") for d in got)
            assert not any(coded(d["expr"].value, "person.expression") for d in got)
        else:  # adults are not limited: the adult-coded looks are still in their pools
            assert set(adult_only("person.expression")) <= set(got[0]["expr"].options)

    async def test_a_life_stage_where_asks_in_code(self, tmp_path):
        src = ONE.replace('about="her age"', 'where={"life_stage": "child"}, about="her age"')
        e = entry_of(src, "a child at the beach")
        await narrow_entry(e, NarrowCache(tmp_path / "n"), ModelAsk({}, read={}))
        assert e["filters"]["age"] and all(is_minor(v) for v in e["filters"]["age"])
        assert dict(program_minors(e))[""] == tuple(e["filters"]["age"])

    async def test_a_stated_age_with_no_age_pick_is_read(self, tmp_path):
        e = entry_of(NO_AGE, "a 10-year-old at the beach")
        ask = ModelAsk({"10-year-old": TEN}, read={"stated_age": "10-year-old"})
        await narrow_entry(e, NarrowCache(tmp_path / "n"), ask)
        assert e["ages"] == {"": ["8–10-year-old"]} and "stated_age" not in e["filters"]
        assert dict(program_minors(e)) == {"": ("8–10-year-old",)}
        for d in draws_of(e, tmp_path / "o", range(150)):
            assert not coded(d["outfit"].value, "person.outfit.summer") and not coded(d["expr"].value, "person.expression")
        # a woman's stated age is read too, and limits nothing
        w = entry_of(NO_AGE, "a woman at the beach")
        await narrow_entry(w, NarrowCache(tmp_path / "n"), ModelAsk({"woman": ADULT}, read={"stated_age": "woman"}))
        assert not program_minors(w)

    async def test_an_unfinished_stated_age_is_tried_again(self, tmp_path):
        e = entry_of(NO_AGE, "a 10-year-old at the beach")

        async def no_read(messages, project_id, max_tokens):
            return "no idea"
        await narrow_entry(e, NarrowCache(tmp_path / "n"), no_read)
        assert e["narrow_pending"]["stated_age"]["age_of"] == "" and "ages" not in e


# --------------------------------------------------------------------------- rule 2: one person's age, their pools

class TestPerPerson:
    async def test_a_minor_loses_adult_coded_looks_and_the_adult_beside_them_does_not(self, tmp_path):
        e = entry_of(TWO, "a child and her mother at the pool")
        ask = ModelAsk({"child": CHILD, "mother": ADULT}, read={"kid.age": "child", "mother.age": "mother"})
        await narrow_entry(e, NarrowCache(tmp_path / "n"), ask)
        assert set(dict(program_minors(e))) == {"kid"}
        mother_pools = set()
        for d in draws_of(e, tmp_path / "o", range(200)):
            assert is_minor(d["kid.age"].value) and not is_minor(d["mother.age"].value)
            assert not set(adult_only("person.outfit.summer")) & set(d["kid.outfit"].options)
            assert not coded(d["kid.expr"].value, "person.expression")
            mother_pools |= set(d["mother.outfit"].options) | set(d["mother.expr"].options)
        assert set(adult_only("person.outfit.summer")) | set(adult_only("person.expression")) <= mother_pools

    def test_a_picked_age_under_18_draws_and_counts_as_asking(self, tmp_path):
        e = entry_of(ONE, "a person at the beach")
        for d in draws_of(e, tmp_path, range(60), pins={"age": ["11–12-year-old"]}):
            assert d["age"].value == "11–12-year-old"
            assert not set(adult_only("person.outfit.summer")) & set(d["outfit"].options)
        out = pool_options(e, {"age": ["11–12-year-old"]}, store=OptionStore(tmp_path / "p"), cfg=OFF)
        tiers = out["vocab"]["age"]["tiers"]
        assert {o for o, t in tiers.items() if t == "opt_in"} == {v.text for v in ages().values if v.minor}
        assert not set(adult_only("person.outfit.summer")) & set(out["options"]["outfit"])
        plain = pool_options(e, store=OptionStore(tmp_path / "q"), cfg=OFF)
        assert set(adult_only("person.outfit.summer")) <= set(plain["options"]["outfit"])

    def test_an_added_or_kept_age_under_18_counts_too(self, tmp_path):
        e = entry_of(ONE, "a person at the beach")
        for kw in ({"edits": {"age": {"add": ["5–7-year-old"]}}}, {"fixed": {"age": "5–7-year-old"}}):
            for d in draws_of(e, tmp_path, range(40), **kw):
                assert not set(adult_only("person.expression")) & set(d["expr"].options)

    async def test_generated_options_are_written_for_the_age_in_their_own_pool(self, tmp_path):
        e = entry_of(NO_AGE, "a 10-year-old at the beach")
        await narrow_entry(e, NarrowCache(tmp_path / "n"), ModelAsk({"10-year-old": TEN}, read={"stated_age": "10-year-old"}))
        store = OptionStore(tmp_path / "o")

        class Gen:
            async def __call__(self, job):
                return ["x"], "fake"
        filler = OptionFiller(store, Gen())
        opts = GeneratedOptions(store, program_context(e), filler=filler)
        draw(NO_AGE, 1, None, [], None, None, None, options=opts)
        jobs = [j for _, j in filler._jobs.values()]
        assert jobs and all(j.spec.minor == ("8–10-year-old",) for j in jobs)
        text = generation_messages(jobs[0])[1]["content"]
        assert "a person under 18 (8–10 years old)" in text
        assert not any(coded(x, j.spec.cls) for j in jobs for x in j.examples)
        adult = PickSpec("outfit", "Outfit", "what she wears", 1, "text", "pick", [], [], "person.outfit.summer")
        kid = PickSpec(**{**vars(adult), "minor": ("8–10-year-old",)})
        assert gen_key(adult, {}, "s", "prose", True, cls=adult.cls) != gen_key(kid, {}, "s", "prose", True, cls=kid.cls,
                                                                                 minor=kid.minor)
        assert gen_key(adult, {}, "s", "prose", True, cls=adult.cls) == gen_key(adult, {}, "s", "prose", True,
                                                                                cls=adult.cls, minor=())

    async def test_a_revision_replays_the_filtered_pool(self, tmp_path):
        e = entry_of(ONE, "a little girl at the beach")
        await narrow_entry(e, NarrowCache(tmp_path / "n"), ModelAsk({"little girl": CHILD}, read={"age": "little girl"}))
        rt = runtime_for(e, store=OptionStore(tmp_path / "o"), cfg=OFF)
        first = draw(ONE, 5, None, [], None, None, None, options=rt.options)
        keys = [k for k in first.revision["pools"] if k.startswith(("outfit:", "expr:"))]
        assert len(keys) == 2 and all(k.endswith("| under 18") for k in keys)
        again = draw(ONE, 5, None, [], None, None, None,
                     options=runtime_for(e, store=OptionStore(tmp_path / "o"), cfg=OFF, revision=first.revision).options)
        assert again.prompt == first.prompt


# --------------------------------------------------------------------------- rule 3: the user's own words

class TestTheUsersOwn:
    def test_a_user_list_is_never_filtered(self, tmp_path):
        bikini = "a red string bikini"
        src = ('age = pick("age", cls="person.age_band", about="her age", seed=["x"], label="Age", phase=1, line=1)\n'
               f'look = pick("look", ["{bikini}", "a sundress"], source="list", label="Look", phase=1, line=1)\n'
               'emit("A", age, "girl in", look)')
        e = entry_of(src)
        seen = {d["look"].value for d in draws_of(e, tmp_path, range(60), pins={"age": ["8–10-year-old"]})}
        assert bikini in seen

    async def test_a_bound_wildcard_is_never_filtered(self, tmp_path):
        e = entry_of(ONE, "a little girl at the beach in {{beachwear}}")
        for c in e["choices"]:
            if c["id"] == "outfit":
                c["wildcard"] = "beachwear"
        await narrow_entry(e, NarrowCache(tmp_path / "n"),
                           ModelAsk({"little girl": CHILD, "beachwear": lambda v: True}, read={"age": "little girl"}))
        assert program_minors(e) and program_context(e).wildcards == ("outfit",)
        d = next(draws_of(e, tmp_path / "o", range(1)))
        assert set(adult_only("person.outfit.summer")) <= set(d["outfit"].options)
        assert not set(adult_only("person.expression")) & set(d["expr"].options)  # her other details still are

    def test_a_users_added_value_stays(self, tmp_path):
        mine = "a sequined showgirl leotard"
        e = entry_of(ONE)
        d = next(draws_of(e, tmp_path, range(1), pins={"age": ["8–10-year-old"]},
                          edits={"outfit": {"add": [mine]}}))
        assert mine in d["outfit"].options


def test_the_program_context_carries_no_minors_for_an_adult_program():
    assert ProgramContext.of(entry_of(ONE)).minors == ()
