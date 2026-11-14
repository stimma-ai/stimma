"""Where a person is from (prompt_programs/places.py): the descent mix of the global prior and a
place's shares, the place a reading names or the user's default, and the pools a place keys.
Nothing here calls a model."""

from __future__ import annotations

import asyncio
import copy
import random
from collections import Counter

import pytest

from prompt_programs import places
from prompt_programs import program as prep
from prompt_programs import slots
from prompt_programs import variant_pools as P
from prompt_programs import variants as V
from prompt_programs.seeding import plan, seeds_of
from prompt_programs.vocab import TIER_WEIGHTS, vocabulary

from test_slots_variants import READING, FakeModel, profile, settled, slot, use  # noqa: F401  (profile: the store fixture)

N = 20000


def drawn(seeds, n=N, seed=7):
    return Counter(s.descent for s in V.draw_seeds(random.Random(seed), seeds, n).specs)


def tv(got, want):
    """Total variation distance between draw counts and a distribution."""
    total = sum(got.values())
    keys = set(got) | set(want)
    return 0.5 * sum(abs(got.get(k, 0) / total - want.get(k, 0.0)) for k in keys)


def region_of(text):
    return vocabulary().get(V.DESCENT).value(text).tags["region"][0]


# --------------------------------------------------------------------------- the mix

def test_the_global_prior_gives_every_region_an_equal_share_split_by_tier():
    g = places.global_prior()
    eth = vocabulary().get(V.DESCENT)
    assert len(g) == len(eth.values) == 113 and abs(sum(g.values()) - 1) < 1e-9
    by, mass = Counter(), Counter()
    for v in eth.values:
        by[region_of(v.text)] += g[v.text]
        mass[region_of(v.text)] += TIER_WEIGHTS[v.tier]
    assert all(abs(p - 0.1) < 1e-9 for p in by.values())
    # within a region each heritage's share is its tier weight over the region's
    for v in eth.values:
        assert g[v.text] == pytest.approx(0.1 * TIER_WEIGHTS[v.tier] / mass[region_of(v.text)]), v.text
    # East Asia: four typical, Mongolian and Tibetan plausible; North America: three of each
    assert g["Korean"] == pytest.approx(0.1 / 4.6) and g["Mongolian"] == pytest.approx(0.03 / 4.6)
    assert g["White American"] == pytest.approx(0.1 / 3.9) and g["Navajo"] == pytest.approx(0.03 / 3.9)
    assert g["German"] / g["Swedish"] == pytest.approx(1 / 0.3)


def test_the_descent_tiers_are_typical_or_plausible_and_every_region_has_a_typical_one():
    eth = vocabulary().get(V.DESCENT)
    assert {v.tier for v in eth.values} == {"typical", "plausible"}
    assert {region_of(v.text) for v in eth.values if v.tier == "typical"} == set(eth.local_facets["region"])


def test_with_no_place_draws_follow_the_global_prior():
    seeds = V.person_seeds()
    got = drawn(seeds)
    assert tv(got, places.global_prior()) < 0.04
    regions = Counter()
    for t, k in got.items():
        regions[region_of(t)] += k
    assert all(abs(k / N - 0.1) < 0.012 for k in regions.values()), regions
    # the tier applies once: a typical heritage beside a plausible one is drawn about 1 / 0.3 as often
    europe = sum(got[t] for t in got if region_of(t) == "Europe")
    typical = sum(got[v.text] for v in vocabulary().get(V.DESCENT).values if v.tier == "typical" and region_of(v.text) == "Europe")
    want = sum(g for t, g in places.global_prior().items() if region_of(t) == "Europe" and vocabulary().get(V.DESCENT).value(t).tier == "typical") / 0.1
    assert abs(typical / europe - want) < 0.03, (typical / europe, want)


@pytest.mark.parametrize("source,w", [("default", places.FROM_DEFAULT), ("prompt", places.FROM_PROMPT)])
def test_a_place_mixes_its_shares_with_the_global_prior(source, w):
    assert (places.FROM_PROMPT, places.FROM_DEFAULT) == (0.8, 0.5)
    place = {"code": "JP", "from": source}
    want = places.mix(place)
    assert abs(sum(want.values()) - 1) < 1e-9
    jp = dict(vocabulary().places["JP"].shares)
    rest = 1 - sum(jp.values())
    g = places.global_prior()
    assert want["Japanese"] == pytest.approx(w * (jp["Japanese"] + rest * g["Japanese"]) + (1 - w) * g["Japanese"])
    got = drawn(V.person_seeds(place=place))
    assert tv(got, want) < 0.04
    assert abs(got["Japanese"] / N - want["Japanese"]) < 0.015
    # the rest of the world is still drawn: the global part keeps every region in
    assert {region_of(t) for t in got} == set(vocabulary().get(V.DESCENT).local_facets["region"])


def test_a_stated_descent_restricts_the_mix_and_renormalizes_within_it():
    place = {"code": "JP", "from": "prompt"}
    subset = ["Korean", "Japanese", "Chinese"]   # "East Asian" narrowed by the words
    m = places.mix(place)
    want = {t: m[t] / sum(m[t] for t in subset) for t in subset}
    got = drawn(V.person_seeds(descent=subset, place=place))
    assert set(got) <= set(subset) and tv(got, want) < 0.02
    assert got["Japanese"] / N > 0.85
    # no local mass inside the subset: the global prior within it (shares by tier)
    other = ["Nigerian", "Ghanaian"]
    got = drawn(V.person_seeds(descent=other, place=place))
    assert set(got) == set(other) and abs(got["Nigerian"] / N - 0.5) < 0.015
    horn = ["Ethiopian", "Eritrean"]   # typical and plausible
    got = drawn(V.person_seeds(descent=horn, place=place))
    assert set(got) == set(horn) and abs(got["Ethiopian"] / N - 1 / 1.3) < 0.015


@pytest.mark.parametrize("code,majority,share", [("US", "White American", 0.57), ("CA", "White Canadian", 0.66),
                                                 ("AU", "White Australian", 0.73), ("NZ", "White New Zealander", 0.6)])
def test_a_settler_majority_country_draws_its_own_majority_heritage(code, majority, share):
    place = {"code": code, "from": "prompt"}
    m = places.mix(place)
    assert max(m, key=m.get) == majority
    assert m[majority] == pytest.approx(0.8 * (share + (1 - sum(dict(vocabulary().places[code].shares).values())) * places.global_prior()[majority])
                                        + 0.2 * places.global_prior()[majority])
    european = {v.text for v in vocabulary().get(V.DESCENT).values if region_of(v.text) == "Europe"}
    assert not european & set(dict(vocabulary().places[code].shares)) - {"Ashkenazi Jewish"}
    got = drawn(V.person_seeds(place=place))
    assert abs(got[majority] / N - m[majority]) < 0.015


def test_a_plausible_heritage_keeps_its_whole_local_share():
    """Māori is plausible, yet in New Zealand it is drawn at its mix share: the place mix replaces
    the bank's tier weight rather than multiplying it."""
    place = {"code": "NZ", "from": "prompt"}
    assert vocabulary().get(V.DESCENT).value("Māori").tier == "plausible"
    m = places.mix(place)
    got = drawn(V.person_seeds(place=place))
    assert m["Māori"] > 0.12 and abs(got["Māori"] / N - m["Māori"]) < 0.01


def test_israel_draws_its_jewish_and_arab_heritages():
    m = places.mix({"code": "IL", "from": "prompt"})
    top = sorted(m, key=m.get, reverse=True)[:4]
    assert top == ["Mizrahi Jewish", "Ashkenazi Jewish", "Palestinian", "Russian"]
    assert m["Ethiopian Jewish"] > 0.01 and m["Polish"] < 0.005 and m["Moroccan"] < 0.005


def test_a_picked_descent_restricts_the_mix_too():
    place = {"code": "NG", "from": "default"}
    seeds = V.person_seeds(place=place).pinned(V.Pins(regions=("Sub-Saharan Africa",)))
    got = drawn(seeds)
    assert {region_of(t) for t in got} == {"Sub-Saharan Africa"}
    m = places.mix(place)
    sub = [v.text for v in vocabulary().get(V.DESCENT).values if region_of(v.text) == "Sub-Saharan Africa"]
    assert tv(got, {t: m[t] / sum(m[t] for t in sub) for t in sub}) < 0.03
    # a pick outside what the words allow keeps the place's mix as well
    seeds = V.person_seeds(descent=["Korean"], place=place).pinned(V.Pins(descent=("Nigerian", "Ghanaian")))
    got = drawn(seeds)
    assert set(got) == {"Nigerian", "Ghanaian"} and got["Nigerian"] > 3 * got["Ghanaian"]


# --------------------------------------------------------------------------- the place

def test_a_readings_place_counts_only_when_it_is_in_the_table_exactly():
    assert places.place_for("Nigeria") == {"code": "NG", "from": "prompt"}
    assert places.place_for("japan", "FR") == {"code": "JP", "from": "prompt"}
    assert places.place_for("Narnia", "FR") == {"code": "FR", "from": "default"}   # no near matches
    assert places.place_for("Nigera") is None and places.place_for("") is None and places.place_for(None) is None
    assert places.mark({"code": "JP", "from": "prompt"}) == "JP@prompt" and places.mark(None) == ""


@pytest.mark.parametrize("value,code", [("", None), ("anywhere", None), ("Anywhere", None), ("jp", "JP"), ("ZZ", None)])
def test_the_default_place_is_a_table_code_or_none(monkeypatch, value, code):
    from prompt_programs import judge
    monkeypatch.delenv("STIMMA_FLUENT_PEOPLE_FROM", raising=False)
    monkeypatch.setattr(judge, "settings", lambda: judge.FluentSettings(people_from=value))
    assert places.default_place() == code


def test_a_person_reading_carries_its_place_into_the_plan_and_seeds():
    r = {"kind": "person", "person": {"noun": "vendor", "stated": {}, "outfit": "person.outfit.casual", "place": "Nigeria"}}
    p = plan(r, "vendor")
    assert p["said_place"] == "Nigeria"
    seeds = seeds_of({"kind": "person", "banks": [{"role": "descent", "list": V.DESCENT, "narrowed": None}],
                      "place": {"code": "NG", "from": "prompt"}})
    got = drawn(seeds, 4000)
    assert got["Nigerian"] / 4000 > 0.7


# --------------------------------------------------------------------------- end to end: pools by place

def reading_with(place: str):
    r = copy.deepcopy(READING)
    r["slots"][0]["person"]["place"] = place
    return r


async def test_a_prompt_place_is_read_seeded_and_keys_the_pool(monkeypatch, profile):
    model, writer = use(monkeypatch, FakeModel(reading_with("Japan")))
    prompt = "# a Tokyo apartment\n<dominant young woman> at home in <clothing slightly open in the front>, lit by <lighting>"
    entry = await settled(prompt, profile)
    rec = entry["seeds"]["dominant_young_woman"]
    assert rec["place"] == {"code": "JP", "from": "prompt"}
    assert "place" not in entry["seeds"]["lighting"]
    person = slot(entry, "dominant_young_woman")
    seeds = [v["seeds"] for v in P.store_for(profile).variants(person["pool"])]
    assert sum(s.get("descent") == "Japanese" for s in seeds) > len(seeds) / 2


async def test_a_new_default_place_writes_a_new_pool_with_the_old_one_standing_in(monkeypatch, profile):
    prompt = "<dominant young woman> standing in her living room in <clothing slightly open in the front>, lit by <lighting>"
    monkeypatch.setenv("STIMMA_FLUENT_PEOPLE_FROM", "anywhere")
    use(monkeypatch)
    before = await settled(prompt, profile)
    old = slot(before, "dominant_young_woman")
    assert "place" not in before["seeds"]["dominant_young_woman"] and P.store_for(profile).has(old["pool"])
    other_pools = {s["id"]: s["pool"] for s in before["slots"] if s["id"] != "dominant_young_woman"}

    async def hang(*a, **k):   # the new pool isn't written yet
        await asyncio.sleep(3600)
    monkeypatch.setattr(P, "ASK", hang)
    monkeypatch.setenv("STIMMA_FLUENT_PEOPLE_FROM", "BR")
    await slots.prepare(prompt, profile_id=profile, shown=before["key"])
    await slots.idle()
    after = await slots.prepare(prompt, profile_id=profile, start=False, shown=before["key"])
    s = slot(after, "dominant_young_woman")
    assert after["seeds"]["dominant_young_woman"]["place"] == {"code": "BR", "from": "default"}
    assert s["pool"] != old["pool"] and s.get("stand_in") == old["pool"]
    assert {x["id"]: x["pool"] for x in after["slots"] if x["id"] != "dominant_young_woman"} == other_pools
    r = prep.realize(after, seed=2, profile_id=profile)
    assert next(d for d in r.draws if d.id == "dominant_young_woman").source == "variant"   # the stand-in draws
    for t in list(P.writer_for(profile)._inflight.values()):
        if t is not None:
            t.cancel()


def test_pool_key_includes_the_place_only_when_there_is_one():
    k = P.pool_key("m", "woman", "a ⟨woman⟩", [])
    assert k == P.pool_key("m", "woman", "a ⟨woman⟩", [], place="")
    assert k != P.pool_key("m", "woman", "a ⟨woman⟩", [], place="JP@prompt")
    assert P.pool_key("m", "woman", "a ⟨woman⟩", [], place="JP@prompt") != P.pool_key("m", "woman", "a ⟨woman⟩", [], place="JP@default")


# --------------------------------------------------------------------------- the setting's route

async def test_the_people_from_route_reads_and_sets_the_app_wide_place(monkeypatch):
    from fastapi import HTTPException
    import config
    import config_writer
    import routes.prompt_programs as rp
    from prompt_programs import judge
    written = {}
    cfg = config.FluentConfig()
    monkeypatch.setattr(config, "get_settings", lambda: type("S", (), {"fluent": cfg})())
    monkeypatch.setattr(config_writer, "patch_global_section", lambda section, value: written.update({section: value}))
    monkeypatch.delenv("STIMMA_FLUENT_PEOPLE_FROM", raising=False)
    got = await rp.get_people_from()
    assert got["value"] is None and {"code": "JP", "name": "Japan"} in got["places"]
    assert [p["name"] for p in got["places"]] == sorted(p["name"] for p in got["places"])
    got = await rp.put_people_from(rp.PeopleFromRequest(value="jp"))
    assert got["value"] == "JP" and written["fluent"]["people_from"] == "JP" and judge.settings().people_from == "JP"
    assert places.default_place() == "JP"
    got = await rp.put_people_from(rp.PeopleFromRequest(value="Anywhere"))
    assert got["value"] == "anywhere" and places.default_place() is None
    with pytest.raises(HTTPException):
        await rp.put_people_from(rp.PeopleFromRequest(value="Narnia"))
