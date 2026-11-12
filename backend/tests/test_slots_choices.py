"""The chooser's choices on a slot program: choices.expand into pins, edits and zones; /pools
with every zone and every group; /preview drawing from the zones chosen; keep_choices."""

import json

import pytest

from prompt_programs import program as prep
from prompt_programs import slots
from prompt_programs.choices import bound_zones, expand, group_values, kept, zone_titles, UnknownChoiceError
from prompt_programs.vocab import vocabulary

from test_slots_build import AFRICAN, ELDERLY, PORCH_PROMPT, PORCH_READING, _draw
from test_slots_reader import FakeModel, _client, _reply, _use, profile  # noqa: F401  (profile is a fixture)

MAN = "elderly_african_man"
KINDS = PORCH_READING["slots"][1]["free"]["kinds"]
INSTEAD = PORCH_READING["slots"][1]["free"]["instead"]


@pytest.fixture
async def porch(profile, monkeypatch):
    _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    return await slots.ensure(PORCH_PROMPT, profile_id=profile)


def test_values_are_pins_and_off_and_add_are_edits(porch):
    pins, edits, zones = expand(porch, {f"{MAN}.age": {"values": ["70-year-old"]}, "list1": {"off": True},
                                        "pet#add": ["three-legged greyhound"], "pet": {"add": ["tortoise"]}})
    assert pins == {f"{MAN}.age": ["70-year-old"]} and zones == {}
    assert edits == {"list1": {"off": True}, "pet": {"add": ["three-legged greyhound", "tortoise"]}}
    # off wins over a selection; a choice the program doesn't have is passed by
    pins, edits, _ = expand(porch, {f"{MAN}.hair": {"values": ["short curly"], "off": True}, "gone": {"values": ["x"]}})
    assert pins == {} and edits == {f"{MAN}.hair": {"off": True}}
    r = _draw(porch, 4, pins={f"{MAN}.age": ["70-year-old"]}, edits=edits)
    assert "70-year-old" in r.prompt


def test_groups_pin_every_value_in_them_including_several_memberships(porch):
    leaf = vocabulary().get("person.hair_color")
    facet = next(f for f in leaf.local_facets if any(len(v.tags.get(f) or []) > 1 for v in leaf.values))
    several = next(v for v in leaf.values if len(v.tags.get(facet) or []) > 1)
    first, second = several.tags[facet][:2]
    pins, _, _ = expand(porch, {f"{MAN}.hair_color": {"groups": {facet: [first]}}})
    assert several.text in pins[f"{MAN}.hair_color"]
    assert several.text in expand(porch, {f"{MAN}.hair_color": {"groups": {facet: [second]}}})[0][f"{MAN}.hair_color"]
    assert set(pins[f"{MAN}.hair_color"]) == {v.text for v in leaf.values if first in (v.tags.get(facet) or [])}
    # beside values: both
    both = expand(porch, {f"{MAN}.hair_color": {"values": ["auburn"], "groups": {facet: [first]}}})[0]
    assert "auburn" in both[f"{MAN}.hair_color"] and several.text in both[f"{MAN}.hair_color"]
    # descent's declared heritages are groups too
    east = group_values(vocabulary().get("person.ethnicity"), {"group": ["east_asian"]})
    assert "Korean" in east and "Kenyan" not in east
    drawn = {d.id: d.value for d in _draw(porch, 3, pins=expand(porch, {f"{MAN}.descent": {"groups": {"group": ["east_asian"]}}})[0]).draws}
    assert drawn[f"{MAN}.descent"] in east


def test_a_free_slots_zones_and_kinds_alone_is_no_choice(porch):
    assert expand(porch, {"pet": {"zones": ["kinds"]}}) == ({}, {}, {})
    _, _, zones = expand(porch, {"pet": {"zones": ["kinds", "instead", "nowhere"]}})
    assert zones == {"pet": ["kinds", "instead"]}
    drawn = {{d.id: d.value for d in _draw(porch, s, zones=expand(porch, {"pet": {"zones": ["instead"]}})[2]).draws}["pet"]
             for s in range(12)}
    assert drawn <= set(INSTEAD) and drawn


def test_a_narrowed_bound_pick_has_kinds_and_instead(porch):
    kinds, instead = bound_zones(porch, f"{MAN}.age")
    assert sorted(kinds) == sorted(ELDERLY)
    age = vocabulary().get("person.age_band")
    assert instead and not set(instead) & set(ELDERLY) and not any(age.value(o).opt_in for o in instead)   # no minors
    assert zone_titles(porch, f"{MAN}.age") == [{"id": "kinds", "title": "Elderly"}, {"id": "instead", "title": "Instead of elderly"}]
    assert zone_titles(porch, "pet") == [{"id": "kinds", "title": "Kinds of pet"}, {"id": "instead", "title": "Instead of pet"}]
    assert zone_titles(porch, f"{MAN}.build") is None   # narrowed by presentation, not by the user's words
    assert zone_titles(porch, f"{MAN}.hair") is None and bound_zones(porch, f"{MAN}.hair") is None
    assert expand(porch, {f"{MAN}.age": {"zones": ["kinds"]}}) == ({}, {}, {})
    pins = expand(porch, {f"{MAN}.age": {"zones": ["instead"]}})[0]
    assert pins == {f"{MAN}.age": instead}
    pins = expand(porch, {f"{MAN}.descent": {"zones": ["kinds", "instead"]}})[0]
    assert set(AFRICAN) <= set(pins[f"{MAN}.descent"]) and len(pins[f"{MAN}.descent"]) > len(AFRICAN)
    for s in range(6):
        drawn = {d.id: d.value for d in _draw(porch, 700 + s, pins=expand(porch, {f"{MAN}.age": {"zones": ["instead"]}})[0]).draws}
        assert drawn[f"{MAN}.age"] in instead


def test_any_is_no_choice(porch):
    assert expand(porch, {f"{MAN}.descent": {"any": True}, "pet": {"any": True, "zones": ["instead"]}}) == ({}, {}, {})


def test_keep_choices_map_to_values(porch):
    assert kept(porch, {"pet": "grey parrot", "Season": ["autumn"]}) == {"pet": {"values": ["grey parrot"]},
                                                                         "list1": {"values": ["autumn"]}}
    with pytest.raises(UnknownChoiceError, match="isn't a choice"):
        kept(porch, {"hat": "a fedora"})
    from routes.generation import pins_for_kept_choices
    assert pins_for_kept_choices(porch, {"pet": "grey parrot"}) == {"pet": ["grey parrot"]}


# --------------------------------------------------------------------------- the routes

def _prepared(profile, monkeypatch):
    _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    client = _client(monkeypatch, profile)
    out = client.post("/api/prompt-programs/prepare", json={"tool_id": "t", "prompt": PORCH_PROMPT}).json()
    return client, out


def test_prepare_names_the_zones(profile, monkeypatch):
    _, out = _prepared(profile, monkeypatch)
    by_id = {c["id"]: c for c in out["choices"]}
    assert by_id["pet"]["zones"] == [{"id": "kinds", "title": "Kinds of pet"}, {"id": "instead", "title": "Instead of pet"}]
    assert [z["id"] for z in by_id[f"{MAN}.descent"]["zones"]] == ["kinds", "instead"]
    assert "zones" not in by_id[f"{MAN}.hair"] and "zones" not in by_id["list1"]


def test_pools_sends_both_zones_of_a_free_slot_and_every_group(profile, monkeypatch):
    client, out = _prepared(profile, monkeypatch)
    body = {"tool_id": "t", "prompt": PORCH_PROMPT, "key": out["key"]}
    got = client.post("/api/prompt-programs/pools", json=body).json()
    pet = got["choices"]["pet"]
    assert set(pet["zones"]) == {"kinds", "instead"}
    # the slot's own words are among its kinds (pinned, they are the slot as written)
    assert set(pet["zones"]["kinds"]) == {*KINDS, "pet"} and set(pet["zones"]["instead"]) == set(INSTEAD)
    assert set(pet["options"]) == {*KINDS, "pet"} and pet["more"] is False   # nothing chosen: the kinds
    both = client.post("/api/prompt-programs/pools", json={**body, "choices": {"pet": {"zones": ["kinds", "instead"]}}}).json()
    assert set(both["choices"]["pet"]["options"]) == {*KINDS, "pet", *INSTEAD}
    descent = got["choices"][f"{MAN}.descent"]
    assert set(descent["zones"]["kinds"]) == set(AFRICAN) and "Korean" in descent["zones"]["instead"]
    assert "Korean" in descent["groups"]["group"]["east_asian"]
    outfit = got["choices"][f"{MAN}.outfit"]
    assert "presentation" in outfit["groups"] and outfit["short"]
    leaf = vocabulary().get("person.outfit.casual")
    assert all(leaf.short(o) == s and s != o for o, s in outfit["short"].items())


def test_preview_draws_from_the_zones_chosen(profile, monkeypatch):
    import prompt_programs.fix as fix
    monkeypatch.setattr(fix, "await_judge", _no_judge)
    client, out = _prepared(profile, monkeypatch)
    body = {"tool_id": "t", "prompt": PORCH_PROMPT, "choices": {"pet": {"zones": ["instead"]}, "list1": {"off": True}}}
    for seed in range(4):
        r = client.post("/api/prompt-programs/preview", json={**body, "seed": seed}).json()
        drawn = {d["id"]: d["value"] for d in r["draws"]}
        assert drawn["pet"] in INSTEAD and "list1" not in drawn
        assert "evening" in r["prompt"] and "summer" not in r["prompt"] and "autumn" not in r["prompt"]


async def _no_judge(entry, project_id=None):
    return None


def test_options_writes_for_one_zone(profile, monkeypatch):
    client, out = _prepared(profile, monkeypatch)
    seen = []

    async def write(job, count):
        seen.append(job)
        return ["sleepy tortoise", "box of kittens"]
    import prompt_programs.options as opts
    monkeypatch.setattr(opts, "write_options", write)
    body = {"tool_id": "t", "prompt": PORCH_PROMPT, "key": out["key"], "choice_id": "pet", "zone": "instead"}
    r = client.post("/api/prompt-programs/options", json=body)
    assert r.status_code == 200 and r.json()["options"] == ["sleepy tortoise", "box of kittens"]
    assert seen[0].spec.zone == "instead" and seen[0].spec.seeds == INSTEAD
    assert client.post("/api/prompt-programs/options", json={**body, "zone": "elsewhere"}).status_code == 422
