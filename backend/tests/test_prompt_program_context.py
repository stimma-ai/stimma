"""Context facets: a drawn value gives context to the picks that follow it in the same scope.

A person's descent weights that person's skin, eye and hair families; a scene's time of day,
season, indoor or outdoor setting and climate weight its light, weather and clothes. All of it
is vocabulary data (vocab/facets.json "context", each list's "context"); the engine only
matches tag sets, orders takers after givers, and never touches the user's own lists, pins
or wildcards."""

import collections
import json
import re

import pytest

from prompt_programs.fill import CONTEXT_VERSION, PickSpec
from tests.slot_fixtures import analyze
from tests.slot_fixtures import draw
from prompt_programs.fluent import runtime_for
from prompt_programs.judge import FluentSettings
from prompt_programs.narrow import NarrowCache, narrow_entry
from prompt_programs.options import GeneratedOptions, OptionStore, ProgramContext
from prompt_programs.fill import ProgramError
from tests.slot_fixtures import discover
from prompt_programs.vocab import LESS, given_families, vocabulary

async def narrow_read(entry, cache, ask, *args, **kw):
    """narrow_entry with the fake model's reading as the slots' words (slots.build writes them)."""
    entry.setdefault("slot_words", dict(getattr(ask, "read", None) or {}))
    return await narrow_entry(entry, cache, ask, *args, **kw)


OFF = FluentSettings(generate_options=False)


def V():
    return vocabulary()


from tests.slot_fixtures import entry_of  # noqa: E402


def draws_of(entry, tmp_path, seeds, pins=None, context=True, edits=None):
    rt = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF, edits=edits)
    rt.options.context = context
    for seed in seeds:
        r = draw(entry["program"], seed, pins, [], None, None, edits, options=rt.options)
        rt.options.reset()
        yield r, {d.id: d for d in r.draws}


def family(cls, facet, text):
    """A value's typical families on a facet (less-common ones left out)."""
    return {f for f in V().get(cls).context_tags(text, facet) or () if not f.startswith(LESS)}


def less_common(cls, facet, text):
    return {f[len(LESS):] for f in V().get(cls).context_tags(text, facet) or () if f.startswith(LESS)}


def mismatched(cls, facet, text, descent):
    """A drawn value tagged on the facet with no family the descent gives, typical or less common."""
    tags = family(cls, facet, text)
    return bool(tags) and not tags & (family("person.ethnicity", facet, descent) |
                                      less_common("person.ethnicity", facet, descent))


def shares(lid, facet, descent):
    """Each family's share of a list's natural (tagged) weight for a person of this descent."""
    lf, eth = V().get(lid), V().get("person.ethnicity")
    items = [(x.text, x.weight) for x in lf.pool_values()[0]]
    got = [(o, w) for o, w in lf.weigh(items, [(facet, eth.context_tags(descent, facet))])
           if lf.context_tags(o, facet)]
    total = sum(w for _, w in got)
    return {f: sum(w for o, w in got if f in lf.context_tags(o, facet)) / total
            for f in V().context[facet]["values"]}


ONE = '''
hair = pick("hair", cls="person.hair_color", about="her hair color", seed=["black"], label="Hair", phase=1, line=1)
eyes = pick("eyes", cls="person.eye_color", about="her eye color", seed=["brown"], label="Eyes", phase=1, line=2)
descent = pick("descent", cls="person.ethnicity", about="her descent", seed=["Korean"], label="Descent", phase=1, line=3)
skin = pick("skin", cls="person.skin_tone", about="her skin", seed=["fair"], label="Skin", phase=1, line=4)
emit("A", descent, "woman with", hair, "hair,", eyes, "eyes and", skin, "skin")
'''

TWO = '''
wd = pick("woman.descent", cls="person.ethnicity", about="her descent", seed=["Korean"], label="Descent", phase=1, line=1)
wh = pick("woman.hair", cls="person.hair_color", about="her hair color", seed=["black"], label="Hair", phase=2, line=2)
md = pick("man.descent", cls="person.ethnicity", about="his descent", seed=["Irish"], label="Descent", phase=1, line=3)
mh = pick("man.hair", cls="person.hair_color", about="his hair color", seed=["red"], label="Hair", phase=2, line=4)
emit("A", wd, "woman with", wh, "hair and a", md, "man with", mh, "hair")
'''

SCENE = '''
t = pick("time", cls="scene.time_of_day", about="the time of day", seed=["dusk"], label="Time", phase=1, line=1)
light = pick("light", cls="lighting.natural", about="the light", seed=["moonlight"], label="Light", phase=2, line=2)
room = pick("room", cls="interior_space.room", about="the room", seed=["a kitchen"], label="Room", phase=1, line=3)
emit("A cook in", room, "at", t, ", lit by", light)
'''


# --------------------------------------------------------------------------- the data

class TestTheData:
    def test_every_context_facet_has_tags_on_both_sides(self):
        v = V()
        assert v.context, "facets.json declares context facets"
        for facet, spec in v.context.items():
            assert spec.get("scope") in ("person", "scene"), facet
            givers = [lf for lf in v.leaves.values() if facet in lf.gives]
            takers = [lf for lf in v.leaves.values() if facet in lf.takes]
            if spec.get("given") == "program":   # no list gives it: the program says it (person(presentation=...))
                assert takers and not givers, facet
                assert any(lf.context_tags(x.text, facet) for lf in takers for x in lf.values), f"no taker tags {facet}"
                continue
            assert givers and takers, facet
            assert any(lf.context_tags(x.text, facet) for lf in givers for x in lf.values), f"no giver tags {facet}"
            assert any(lf.context_tags(x.text, facet) for lf in takers for x in lf.values), f"no taker tags {facet}"

    def test_lists_only_name_declared_facets_and_values(self):
        v = V()
        for lf in v.leaves.values():
            assert set(lf.gives) <= set(v.context), lf.id
            assert set(lf.takes) <= set(v.context), lf.id
            assert not set(lf.gives) & set(lf.takes), f"{lf.id} gives and takes the same facet"
            for f, (mode, factor) in lf.takes.items():
                assert mode in ("rare", "never", "drop") and (mode != "rare" or 0 < factor < 1), (lf.id, f)
                if f in lf.less:   # the middle level sits between kept and the mismatch
                    assert factor < lf.less[f] < 1, (lf.id, f)
            if lf.stated:
                assert lf.gives and len({v.scope(f) for f in lf.gives}) == 1, lf.id
            for f in {*lf.gives, *lf.takes}:
                spec = v.context[f]
                allowed = set(spec.get("values") or (v.facets.get(f) or {}).get("values") or [])
                allowed |= set(spec.get("neutral") or ())
                assert allowed, f
                for x in lf.values:
                    tags = lf.context_tags(x.text, f) or ()
                    typical = {t for t in tags if not t.startswith(LESS)}
                    less = {t[len(LESS):] for t in tags if t.startswith(LESS)}
                    assert typical | less <= allowed, (lf.id, x.text, f)
                    assert not typical & less, f"{x.text}: {f} both typical and less common"
                    if less:   # a giver's less-common family needs every taker to say what it costs
                        assert f in lf.gives and all(f in t.less for t in v.leaves.values() if f in t.takes), f

    def test_every_descent_has_coloring_families(self):
        eth = V().get("person.ethnicity")
        assert set(eth.gives) == {"skin_family", "eye_family", "hair_family", "texture"} and eth.stated
        for x in eth.values:
            for f in eth.gives:
                assert eth.context_tags(x.text, f), f"{x.text} has no {f}"
            assert x.tags.get("region"), f"{x.text} has no region"

    # The one group across a region border: Afghan and Pashtun (South Asia) with Tajik (Central Asia).
    NEIGHBORS = {"afghan": {"South Asia", "Central Asia"}}

    def test_every_descent_is_in_a_declared_group_of_one_region(self):
        """Coloring is declared per named group, and a group never lumps peoples of unrelated
        regions together because their coloring coincides."""
        eth = V().get("person.ethnicity")
        members = collections.defaultdict(list)
        for x in eth.values:
            assert x.group in eth.groups, f"{x.text} has no declared group"
            members[x.group].append(x)
        assert set(members) == set(eth.groups), "a declared group with no member"
        for name, xs in members.items():
            assert eth.groups[name].get("about"), name
            regions = {r for x in xs for r in x.tags["region"]}
            assert len(regions) == 1 or regions == self.NEIGHBORS.get(name), (name, regions)

    def test_native_american_descents_have_their_own_group(self):
        eth = V().get("person.ethnicity")
        assert {x.text for x in eth.values if x.group == eth.value("Navajo").group} == {"Navajo", "Cherokee"}
        assert eth.value("Navajo").group != eth.value("Vietnamese").group

    def test_central_asian_descents_are_tagged_central_asian(self):
        eth = V().get("person.ethnicity")
        for d in ("Kazakh", "Uzbek", "Kyrgyz", "Turkmen", "Tajik"):
            assert eth.value(d).tags["region"] == ["Central Asia"], d
        for d in ("Afghan", "Pashtun"):
            assert eth.value(d).tags["region"] == ["South Asia"], d

    def test_mixed_populations_favor_everything_on_purpose(self):
        eth = V().get("person.ethnicity")
        for d in ("South African", "Brazilian"):
            x = eth.value(d)
            assert "deliberately wide" in eth.groups[x.group]["about"], d
            for f in eth.gives:
                assert family("person.ethnicity", f, d) == set(V().context[f]["values"]), (d, f)


class TestTypicalLooks:
    """A descent word means that heritage's typical look, with the range people would recognize."""

    def test_nordic_eyes_are_mostly_light_and_blonde_leads(self):
        for d in ("Swedish", "Norwegian", "Danish", "Finnish"):
            eyes, hair = shares("person.eye_color", "eye_family", d), shares("person.hair_color", "hair_family", d)
            assert eyes["light"] > 0.6 and 0.1 < eyes["brown"] < 0.3, (d, eyes)
            assert max(hair, key=hair.get) == "blonde" and hair["blonde"] > 0.45, (d, hair)
            assert hair["brown"] > 0.25 and hair["dark_brown"] < 0.1 and hair["black"] < 0.03, (d, hair)

    def test_southern_europeans_are_mostly_brown_eyed(self):
        for d in ("Italian", "Spanish", "Portuguese", "Greek", "Chilean", "Argentinian", "Afghan"):
            eyes = shares("person.eye_color", "eye_family", d)
            assert eyes["brown"] > 0.5 and 0.08 < eyes["light"] < 0.25, (d, eyes)

    def test_irish_lean_light_eyed_with_brown_present(self):
        for d in ("Irish", "Scottish", "Welsh", "English"):
            eyes = shares("person.eye_color", "eye_family", d)
            assert eyes["light"] > 0.5 and eyes["brown"] > 0.1, (d, eyes)

    def test_french_eyes_sit_between_south_and_north(self):
        light = {d: shares("person.eye_color", "eye_family", d)["light"] for d in ("Italian", "French", "Irish", "Swedish")}
        assert light["Italian"] < light["French"] < light["Irish"] < light["Swedish"], light

    def test_red_hair_is_most_common_for_irish_scottish_welsh(self):
        eth = V().get("person.ethnicity")
        base = shares("person.hair_color", "hair_family", "Brazilian")["red"]   # favors every family: the baseline
        red = {x.text: shares("person.hair_color", "hair_family", x.text)["red"] for x in eth.values}
        for d in ("Irish", "Scottish", "Welsh"):
            assert base + 0.05 < red[d] < 0.5, (d, red[d], base)
            assert red[d] > max(r for o, r in red.items() if o not in ("Irish", "Scottish", "Welsh")), d

    def test_rare_keeps_every_mismatch_possible(self):
        """Natural coloring is weighted, never excluded: each descent still draws some of
        every family, and no descent's mismatch share is above a few percent."""
        v, eth = V(), V().get("person.ethnicity")
        for lid, facet, cap in [("person.skin_tone", "skin_family", 0.03), ("person.eye_color", "eye_family", 0.05),
                                ("person.hair_color", "hair_family", 0.08)]:
            lf = v.get(lid)
            assert lf.takes[facet][0] == "rare"
            items = [(x.text, x.weight) for x in lf.pool_values()[0]]
            for d in eth.values:
                got = lf.weigh(items, [(facet, eth.context_tags(d.text, facet))])
                assert all(w > 0 for _, w in got), (lid, d.text)
                miss = sum(w for o, w in got if mismatched(lid, facet, o, d.text)) / sum(w for _, w in got)
                assert miss <= cap, (lid, d.text, miss)

    def test_untagged_values_keep_their_share(self):
        """Gray, white and dyed hair are untagged: descent moves weight among natural shades only."""
        lf = V().get("person.hair_color")
        items = [(x.text, x.weight) for x in lf.pool_values()[0]]
        got = dict(lf.weigh(items, [("hair_family", ("black", "dark_brown"))]))
        untagged = [o for o, _ in items if not lf.context_tags(o, "hair_family")]
        assert {"gray", "white", "rose pink"} <= set(untagged)
        share = lambda d: sum(d[o] for o in untagged) / sum(d.values())  # noqa: E731
        assert share(got) == pytest.approx(share(dict(items)))
        assert got["black"] > dict(items)["black"] and got["golden blonde"] < dict(items)["golden blonde"]


# --------------------------------------------------------------------------- the engine rule



class TestWeighting:
    def test_descent_weights_that_persons_coloring(self, tmp_path):
        e = entry_of(ONE)
        miss = collections.Counter()
        n = 300
        for arm in (False, True):
            for r, d in draws_of(e, tmp_path / str(arm), range(n), context=arm):
                desc = d["descent"].value
                miss[arm] += mismatched("person.eye_color", "eye_family", d["eyes"].value, desc)
                miss[arm] += mismatched("person.skin_tone", "skin_family", d["skin"].value, desc)
        assert miss[False] > 0.4 * n and miss[True] < 0.1 * n, miss
        assert miss[True] > 0   # rare, not never

    def test_scope_per_person(self, tmp_path):
        e = entry_of(TWO)
        pins = {"woman.descent": ["Japanese"], "man.descent": ["Irish"]}
        wh, mh = collections.Counter(), collections.Counter()
        for r, d in draws_of(e, tmp_path, range(200), pins=pins):
            wh[bool(family("person.hair_color", "hair_family", d["woman.hair"].value) & {"blonde", "red"})] += 1
            mh[bool(family("person.hair_color", "hair_family", d["man.hair"].value) & {"blonde", "red"})] += 1
            pool = next(k for k in r.revision["pools"] if k.startswith("man.hair:"))
            assert "hair_family=brown,dark_brown,red,~blonde" in pool
        assert wh[True] < 20 and mh[True] > 40, (wh, mh)

    def test_never_filters_and_the_scene_scope_reaches_every_pick(self, tmp_path):
        e = entry_of(SCENE)
        for r, d in draws_of(e, tmp_path, range(80), pins={"time": ["midnight"]}):
            light = V().get("lighting.natural").value(d["light"].value)
            assert light is not None and "night" in light.tags["time_of_day"], d["light"].value
            assert light.tags["space"] == "any" or "indoor" in light.tags["space"]   # a kitchen: no outdoor-only light
            weights = dict(zip(d["light"].options, [None] * len(d["light"].options)))
            assert "harsh midday sun" in weights   # still shown (the picker can pin it), weight 0

    def test_a_pinned_taker_value_still_draws(self, tmp_path):
        e = entry_of(SCENE)
        got = {d["light"].value for _, d in draws_of(e, tmp_path, range(5),
                                                    pins={"time": ["midnight"], "light": ["harsh midday sun"]})}
        assert got == {"harsh midday sun"}


class TestTheUsersOwn:
    def test_a_user_list_is_never_weighted(self, tmp_path):
        src = ('descent = pick("descent", cls="person.ethnicity", about="her descent", seed=["Korean"], label="Descent", phase=1, line=1)\n'
               'hair = pick("hair", ["golden blonde", "black"], source="list", label="Hair", phase=2, line=2)\n'
               'emit("A", descent, "woman with", hair, "hair")')
        got = collections.Counter(d["hair"].value for _, d in draws_of(entry_of(src), tmp_path, range(200),
                                                                        pins={"descent": ["Japanese"]}))
        assert 70 < got["golden blonde"] < 130, got

    def test_ticked_values_are_never_weighted(self, tmp_path):
        got = collections.Counter(d["hair"].value for _, d in draws_of(
            entry_of(ONE), tmp_path, range(200), pins={"descent": ["Japanese"], "hair": ["golden blonde", "black"]}))
        assert 70 < got["golden blonde"] < 130, got


    def test_a_users_added_value_keeps_its_weight(self, tmp_path):
        mine = "silver-blue ombre"
        edits = {"hair": {"add": [mine]}}
        got = collections.Counter(d["hair"].value for _, d in draws_of(
            entry_of(ONE), tmp_path, range(400), pins={"descent": ["Japanese"]}, edits=edits))
        assert got[mine] > 0


# --------------------------------------------------------------------------- stated and listed givers

class TestStated:
    def test_a_stated_descent_weights_the_coloring(self, tmp_path):
        src = ONE.replace('descent = pick("descent", cls="person.ethnicity", about="her descent", seed=["Korean"], '
                          'label="Descent", phase=1, line=3)\n', '').replace('emit("A", descent,', 'emit("A Japanese",')
        e = entry_of(src, "a Japanese woman", stated_context=[{"of": "", "cls": "person.ethnicity", "values": ["Japanese"]}])
        miss = sum(mismatched("person.eye_color", "eye_family", d["eyes"].value, "Japanese")
                   for _, d in draws_of(e, tmp_path, range(200)))
        assert miss < 15
        r, _ = next(draws_of(e, tmp_path / "r", range(1)))
        assert r.revision.get("context") == CONTEXT_VERSION

    def test_a_drawn_descent_wins_over_the_stated_one(self, tmp_path):
        e = entry_of(ONE, stated_context=[{"of": "", "cls": "person.ethnicity", "values": ["Japanese"]}])
        r, d = next(draws_of(e, tmp_path, range(1), pins={"descent": ["Irish"]}))
        assert any("hair_family=brown,dark_brown,red,~blonde" in k for k in r.revision["pools"])

    def test_a_users_list_value_gives_its_scope_context(self, tmp_path):
        src = ('descent = pick("descent", ["Japanese", "Irish"], source="list", label="Descent", phase=1, line=1)\n'
               'eyes = pick("eyes", cls="person.eye_color", about="her eye color", seed=["brown"], label="Eyes", phase=1, line=2)\n'
               'emit("A", descent, "woman with", eyes, "eyes")')
        e = entry_of(src, list_context={"descent": {"Japanese": {"person.ethnicity": ["Japanese"]},
                                                     "Irish": {"person.ethnicity": ["Irish"]}}})
        seen = collections.Counter()
        for _, d in draws_of(e, tmp_path, range(200)):
            seen[(d["descent"].value, bool(family("person.eye_color", "eye_family", d["eyes"].value) & {"light"}))] += 1
        assert seen[("Japanese", True)] < 10 and seen[("Irish", True)] > 25, seen
        assert seen[("Japanese", False)] + seen[("Japanese", True)] > 70   # the list itself draws evenly

    def test_given_families_needs_every_value_tagged(self):
        assert given_families("person.ethnicity", ["Japanese", "Korean"])["eye_family"] == ("brown",)
        assert given_families("person.ethnicity", []) == {}
        assert "skin_family" not in given_families("scene.time_of_day", ["midnight"])


class Ask:
    """Narrowing as a model following the instructions would answer it: `read` is the
    slots' words for each choice (narrow_read); `keep` maps a phrase to the values it keeps (default: the whole list)."""

    def __init__(self, read=None, keep=None):
        self.read, self.keep, self.calls = read or {}, keep or {}, []

    async def __call__(self, messages, project_id, max_tokens):
        values = json.loads(re.search(r"\n(\[.*?\])\n", messages[1]["content"], re.S).group(1))
        phrase = re.search(r'Which of these fit "(.*?)"', messages[1]["content"]).group(1)
        self.calls.append(("subset", phrase))
        keep = self.keep.get(phrase)
        return json.dumps([v for v in values if keep is None or v in keep])


class TestNarrowing:

    async def test_words_that_keep_the_whole_list_say_nothing(self, tmp_path):
        src = ('eyes = pick("eyes", cls="person.eye_color", about="her eye color", seed=["brown"], label="Eyes", phase=1, line=1)\n'
               'emit("A woman with", eyes, "eyes")')
        e = entry_of(src, "a woman")
        await narrow_read(e, NarrowCache(tmp_path), Ask(read={"stated_ethnicity": "woman"}))
        assert "stated_context" not in e

    async def test_a_person_with_a_descent_pick_is_not_read_again(self, tmp_path):
        e = entry_of(ONE, "a woman")
        ask = Ask()
        await narrow_read(e, NarrowCache(tmp_path), ask)
        assert not any("stated_ethnicity" in text for kind, text in ask.calls if kind == "read")

    async def test_a_users_list_values_are_read_on_the_descent_list(self, tmp_path):
        src = ('who = pick("who", ["Japanese", "in a red coat"], source="list", label="Who", phase=1, line=1)\n'
               'eyes = pick("eyes", cls="person.eye_color", about="her eye color", seed=["brown"], label="Eyes", phase=1, line=2)\n'
               'emit("A", who, "woman with", eyes, "eyes")')
        e = entry_of(src, "a {Japanese|in a red coat} woman")
        await narrow_read(e, NarrowCache(tmp_path), Ask(keep={"Japanese": ["Japanese"]}))
        assert e["list_context"] == {"who": {"Japanese": {"person.ethnicity": ["Japanese"]}}}


# --------------------------------------------------------------------------- replay

class TestReplay:
    def test_a_revision_with_context_replays_exactly(self, tmp_path):
        e = entry_of(ONE)
        for seed in range(20):
            first = draw(ONE, seed, None, [], None, None, None,
                         options=runtime_for(e, store=OptionStore(tmp_path), cfg=OFF).options)
            assert first.revision["context"] == CONTEXT_VERSION
            again = draw(ONE, seed, None, [], None, None, None,
                         options=runtime_for(e, store=OptionStore(tmp_path), cfg=OFF, revision=first.revision).options)
            assert again.prompt == first.prompt and again.revision == first.revision

    def test_a_replay_reads_the_recorded_context_pool(self, tmp_path):
        """Tags may change between versions: a replay draws from the pool as it was recorded."""
        e = entry_of(ONE)
        first = draw(ONE, 4, None, [], None, None, None,
                     options=runtime_for(e, store=OptionStore(tmp_path), cfg=OFF).options)
        rev = json.loads(json.dumps(first.revision))
        key = next(k for k in rev["pools"] if k.startswith("hair:"))
        drawn = next(d.value for d in first.draws if d.id == "hair")
        rev["pools"][key] = [[drawn, 1.0]]
        again = draw(ONE, 4, None, [], None, None, None,
                     options=runtime_for(e, store=OptionStore(tmp_path), cfg=OFF, revision=rev).options)
        assert next(d.options for d in again.draws if d.id == "hair") == [drawn]

    def test_a_revision_drawn_before_context_replays_without_it(self, tmp_path):
        e = entry_of(ONE)
        for seed in range(20):
            rt = runtime_for(e, store=OptionStore(tmp_path), cfg=OFF)
            rt.options.context = False   # what an older build drew
            old = draw(ONE, seed, None, [], None, None, None, options=rt.options)
            assert "context" not in old.revision
            again = draw(ONE, seed, None, [], None, None, None,
                         options=runtime_for(e, store=OptionStore(tmp_path), cfg=OFF, revision=old.revision).options)
            assert again.prompt == old.prompt and again.revision == old.revision

    def test_a_ctx_1_revision_still_replays_exactly(self, tmp_path):
        """ctx-1 drew before less-common families; its weighted pools are recorded, so it replays as drawn."""
        e = entry_of(ONE)
        for seed in range(10):
            first = draw(ONE, seed, None, [], None, None, None,
                         options=runtime_for(e, store=OptionStore(tmp_path), cfg=OFF).options)
            old = json.loads(json.dumps(first.revision))
            old["context"] = "ctx-1"
            again = draw(ONE, seed, None, [], None, None, None,
                         options=runtime_for(e, store=OptionStore(tmp_path), cfg=OFF, revision=old).options)
            assert again.prompt == first.prompt and again.revision["context"] == "ctx-1"

    def test_an_unknown_context_version_is_refused(self, tmp_path):
        with pytest.raises(ProgramError):
            runtime_for(entry_of(ONE), store=OptionStore(tmp_path), cfg=OFF, revision={"context": "ctx-99", "pools": {}})


    def test_a_literal_options_draw_weights_a_bound_list_too(self):
        leaf = V().get("person.hair_color")
        spec = PickSpec("hair", "Hair", "", 1, "text", "pick", [], [], leaf.id,
                        context=(("hair_family", ("black",)),))
        from prompt_programs.fill import LiteralOptions
        pool = LiteralOptions().get(spec, {})
        w = dict(zip(pool.items, pool.weights))
        assert pool.key.endswith("| context hair_family=black") and w["golden blonde"] < w["black"]


def test_options_service_reads_stated_and_listed_context():
    e = entry_of(ONE, stated_context=[{"of": "woman", "cls": "person.ethnicity", "values": ["Japanese"]},
                                      {"of": None, "cls": "scene.time_of_day", "values": ["midnight"]}],
                 list_context={"d": {"Irish": {"person.ethnicity": ["Irish"]}}})
    o = GeneratedOptions(None, ProgramContext.of(e))
    assert o.stated_context["woman"]["eye_family"] == ("brown",)
    assert o.stated_context[None]["time_of_day"] == ("night",)
    assert "red" in o.list_context["d"]["Irish"]["hair_family"]


# --------------------------------------------------------------------------- a setting the prompt states

LIGHTS = '''
nat = pick("nat", cls="lighting.natural", about="the light", seed=["window light"], label="Light", phase=1, line=1)
prac = pick("prac", cls="lighting.indoor_practical", about="the light", seed=["lamplight"], label="Lamp", phase=1, line=1)
dram = pick("dram", cls="lighting.dramatic", about="the light", seed=["rim light"], label="Look", phase=1, line=1)
emit("A woman taking a selfie, lit by", nat, ",", prac, "and", dram)
'''
NAT = '''
nat = pick("nat", cls="lighting.natural", about="the light", seed=["window light"], label="Light", phase=1, line=1)
emit("A woman, lit by", nat)
'''
AGE = '''
age = pick("age", cls="person.age_band", about="her age", seed=["32-year-old"], label="Age", phase=1, line=1)
emit("A", age, "woman")
'''
LIGHT_LISTS = {"nat": "lighting.natural", "prac": "lighting.indoor_practical", "dram": "lighting.dramatic"}


class TestTheSetting:
    """A look that places the scene somewhere (sun and sky outdoors, a window indoors, sunlight
    underwater, a streetlight) is tagged with the setting it needs; its list takes the setting
    with "unstated": "opt_in". With no setting stated or drawn it is held: shown, never drawn
    unasked. Tags decide, never the words of the values."""

    def test_every_light_is_tagged_with_the_setting_it_needs_or_any(self):
        allowed = set(V().facets["space"]["values"])
        for lid in ("lighting.natural", "lighting.indoor_practical", "lighting.dramatic", "lighting.studio"):
            for x in V().get(lid).values:
                space = x.tags.get("space")
                assert space == "any" or (isinstance(space, list) and space and set(space) <= allowed), (lid, x.text)
        assert all(x.tags["space"] == "any" for x in V().get("lighting.studio").values)
        nat = V().get("lighting.natural")
        assert nat.value("underwater sunlight").tags["space"] == ["underwater"]
        assert nat.value("window light").tags["space"] == ["indoor"]
        assert [x.text for x in nat.values if not nat.needs(x.text)] == ["soft natural light", "bright natural daylight"]
        # Places more specific than their space are drawn only when asked for.
        for text in ("ice-cave daylight", "aurora light", "forest shade", "canyon bounce light"):
            assert nat.value(text).opt_in, text

    def test_the_lists_take_the_setting_and_a_list_reads_it_from_the_prompt(self):
        for lid in ("lighting.natural", "lighting.indoor_practical", "lighting.dramatic"):
            assert V().get(lid).unstated == ("space",), lid
        setting = V().get("scene.setting")
        assert setting.gives == ("space",) and setting.stated and not setting.listed
        assert given_families("scene.setting", ["outdoors"]) == {"space": ("outdoor",)}

    def test_an_unknown_unstated_rule_is_an_error(self, tmp_path):
        from prompt_programs.vocab import load
        (tmp_path / "x").mkdir()
        (tmp_path / "x" / "_node.json").write_text(json.dumps({"id": "x", "label": "X", "description": "x"}))
        (tmp_path / "x" / "l.json").write_text(json.dumps({
            "id": "x.l", "label": "L", "description": "l", "pos": "noun", "frame": "a ___", "notes": "", "closed": True,
            "facets": [], "context": {"takes": {"space": {"mismatch": "never", "unstated": "sometimes"}}},
            "values": [{"text": "a", "tier": "typical"}]}))
        with pytest.raises(ValueError, match="unstated"):
            load((tmp_path,))

    def test_with_no_setting_stated_a_light_that_places_the_scene_is_never_drawn_unasked(self, tmp_path):
        e = entry_of(LIGHTS, "a woman taking a selfie")
        drawn = collections.Counter()
        for r, d in draws_of(e, tmp_path, range(2000)):
            for pid, lid in LIGHT_LISTS.items():
                leaf, value = V().get(lid), d[pid].value
                assert not leaf.needs(value) and not leaf.value(value).opt_in, (pid, value)
                drawn[(pid, value)] += 1
        # Held, not removed: the chooser still offers them.
        assert "ice-cave daylight" in d["nat"].options and "sodium-vapor streetlight" in d["prac"].options
        assert {v for (p, v) in drawn if p == "nat"} == {"soft natural light", "bright natural daylight"}
        assert len({v for (p, v) in drawn if p == "prac"}) >= 10 and len({v for (p, v) in drawn if p == "dram"}) >= 20

    def test_outdoors_at_dusk_draws_sunset_light_and_never_an_indoor_one(self, tmp_path):
        e = entry_of(LIGHTS, "a woman on a porch outdoors at dusk",
                     stated_context=[{"of": None, "cls": "scene.setting", "values": ["outdoors"]},
                                     {"of": None, "cls": "scene.time_of_day", "values": ["sunset", "blue hour"]}])
        nat = V().get("lighting.natural")
        got = collections.Counter(d["nat"].value for _, d in draws_of(e, tmp_path, range(400)))
        assert {"golden hour sunlight", "sunset afterglow", "blue hour light"} <= set(got), got
        for value in got:
            tags = nat.value(value).tags
            assert tags["space"] == "any" or "outdoor" in tags["space"], value
            assert not nat.value(value).opt_in, value   # no alpenglow: mountains are asked for, not stated by "outdoors"

    def test_outdoors_alone_draws_golden_hour_sun(self, tmp_path):
        e = entry_of(LIGHTS, "a woman outdoors",
                     stated_context=[{"of": None, "cls": "scene.setting", "values": ["outdoors"]}])
        got = collections.Counter(d["nat"].value for _, d in draws_of(e, tmp_path, range(300)))
        assert got["golden hour sunlight"] > 0 and got["harsh midday sun"] > 0
        assert not {"window light", "underwater sunlight"} & set(got), got

    def test_a_picked_light_is_drawn_without_a_setting(self, tmp_path):
        e = entry_of(LIGHTS)
        got = {d["nat"].value for _, d in draws_of(e, tmp_path, range(20), pins={"nat": ["ice-cave daylight"]})}
        assert got == {"ice-cave daylight"}
        got = collections.Counter(d["nat"].value for _, d in draws_of(
            e, tmp_path / "two", range(200), pins={"nat": ["harsh midday sun", "window light"]}))
        assert set(got) == {"harsh midday sun", "window light"}, got

    def test_a_drawn_place_states_the_setting(self, tmp_path):
        e = entry_of(SCENE)
        got = collections.Counter()
        for _, d in draws_of(e, tmp_path, range(100), pins={"time": ["high noon"]}):
            space = V().get("lighting.natural").value(d["light"].value).tags["space"]
            assert space == "any" or "indoor" in space, d["light"].value   # a kitchen
            got[space == "any"] += 1
        assert got[False] > 30, got   # window light and the like: the drawn room says indoors

    def test_a_revision_drawn_before_the_rule_replays_its_recorded_weights(self, tmp_path):
        """A ctx-2 revision records the natural-light pool as the last build drew it (every value at
        its tier's weight, none opt-in or held). Its replay draws from those weights, not from
        today's opt-in flags and setting tags, so each seed draws what it drew then."""
        import random
        from pathlib import Path
        recorded = json.loads((Path(__file__).parent / "fixtures" / "natural_light_pool_ctx2.json").read_text())
        e = entry_of(NAT)
        first = draw(NAT, 0, None, [], None, None, None,
                     options=runtime_for(e, store=OptionStore(tmp_path), cfg=OFF).options)
        # The last build drew no setting context, so its key has none (today's names the unstated setting).
        key = next(k for k in first.revision["pools"] if k.startswith("nat:")).split(" | context ")[0]
        rev = {**json.loads(json.dumps(first.revision)), "context": "ctx-2", "pools": {key: recorded}}
        total = sum(w for _, w in recorded)
        drawn = set()
        for seed in range(40):
            r = random.Random(seed).random() * total   # fill._Fill._weighted over the recorded pool
            want = next((o for o, w in recorded if (r := r - w) <= 0), recorded[-1][0])
            again = draw(NAT, seed, None, [], None, None, None,
                         options=runtime_for(e, store=OptionStore(tmp_path), cfg=OFF, revision=rev).options)
            got = next(d.value for d in again.draws if d.id == "nat")
            assert got == want, (seed, got, want)
            drawn.add(got)
        nat = V().get("lighting.natural")
        assert any(nat.needs(x) for x in drawn)   # values today's rule holds still replay as drawn

    def test_an_older_replay_still_holds_ages_under_18(self, tmp_path):
        e = entry_of(AGE)
        first = draw(AGE, 0, None, [], None, None, None,
                     options=runtime_for(e, store=OptionStore(tmp_path), cfg=OFF).options)
        key = next(k for k in first.revision["pools"] if k.startswith("age:"))
        ages = V().get("person.age_band")
        young = next(v.text for v in ages.values if v.minor)
        rev = {**json.loads(json.dumps(first.revision)), "context": "ctx-2",
               "pools": {key: [[young, 1.0], ["32-year-old", 0.000001]]}}
        got = {next(d.value for d in draw(AGE, seed, None, [], None, None, None,
                                          options=runtime_for(e, store=OptionStore(tmp_path), cfg=OFF,
                                                              revision=rev).options).draws if d.id == "age")
               for seed in range(20)}
        assert got == {"32-year-old"}, got

    async def test_the_setting_and_the_time_are_read_in_the_prompt(self, tmp_path):
        prompt = "a woman on a porch at dusk, lit by <light>"
        e = entry_of(LIGHTS, prompt)
        ask = Ask(keep={prompt: ["outdoors", "blue hour", "nightfall", "light drizzle"]})
        await narrow_read(e, NarrowCache(tmp_path), ask)
        said = {s["cls"]: s["values"] for s in e["stated_context"]}
        assert said == {"scene.setting": ["outdoors"], "scene.time_of_day": ["blue hour", "nightfall"]}
        # Only what a light needs stated (the setting) or can't mismatch (natural light's time): the
        # weather's climate only makes a look rarer, so it isn't read.
        assert len([p for kind, p in ask.calls if p == prompt]) == 2
        o = GeneratedOptions(None, ProgramContext.of(e))
        assert o.stated_context[None]["space"] == ("outdoor",) and o.stated_context[None]["time_of_day"] == ("dusk", "night")

    async def test_a_prompt_that_states_no_setting_states_none(self, tmp_path):
        e = entry_of(LIGHTS, "a woman taking a selfie, lit by <light>")
        await narrow_read(e, NarrowCache(tmp_path), Ask())   # every setting fits: nothing stated
        assert "stated_context" not in e


SELFIE = '''
selfie = pick("selfie", cls="camera.selfie", about="the selfie", seed=["an arm's-length selfie"], label="Selfie", phase=1, line=1)
emit("A woman taking", selfie)
'''


async def test_a_list_copied_whole_by_its_narrowing_keeps_its_opt_in_values_held(tmp_path):
    """A narrowing that names every item one by one says what ["ALL"] says: a couple or group
    selfie for one woman was not called for."""
    e = entry_of(SELFIE, "a woman taking <selfie>")
    await narrow_read(e, NarrowCache(tmp_path), Ask(read={"selfie": "selfie"}))   # names all nine
    held = {"a couple selfie", "a two-person mirror selfie", "a group selfie"}
    assert e["filters"]["selfie"] and not held & set(e["filters"]["selfie"])
    got = {d["selfie"].value for _, d in draws_of(e, tmp_path, range(300))}
    assert got and not got & held, got
    # Named on purpose, they are drawn.
    e = entry_of(SELFIE, "two friends taking <selfie>")
    await narrow_read(e, NarrowCache(tmp_path / "two"), Ask(read={"selfie": "selfie"}, keep={"selfie": ["a couple selfie"]}))
    assert e["filters"]["selfie"] == ["a couple selfie"]
