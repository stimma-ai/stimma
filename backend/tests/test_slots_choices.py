"""The chooser's choices on a prepared prompt: choices.expand into list pins, list edits and
one variant_pools.Choice per slot; keep_choices; and the routes that take them: /prepare (one
choice per slot), /pools, /preview and /options (More like these)."""

import pytest

from prompt_programs import program as prep
from prompt_programs import variant_pools as P
from prompt_programs.choices import UnknownChoiceError, expand, kept

from test_slots_fill import PORCH_PROMPT, PORCH_READING
from test_slots_reader import FakeModel, _client, _reply, _use, profile, ready  # noqa: F401  (profile is a fixture)

MAN = "elderly_african_man"


@pytest.fixture
async def porch(profile, monkeypatch):
    _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    return await ready(PORCH_PROMPT, profile)


def pool_of(entry, profile, sid):
    s = next(s for s in entry["slots"] if s["id"] == sid)
    return [v["text"] for v in P.store_for(profile).variants(s["pool"])]


def test_a_slots_choice_is_a_choice_and_a_lists_are_pins_and_edits(porch):
    pins, edits, chosen = expand(porch, {MAN: {"values": ["a tall man"]}, "list1": {"off": True},
                                         "pet#add": ["three-legged greyhound"], "pet": {"add": ["tortoise"]}})
    assert pins == {} and edits == {"list1": {"off": True}}
    assert chosen[MAN].values == ("a tall man",) and chosen["pet"].add == ("three-legged greyhound", "tortoise")
    pins, edits, _ = expand(porch, {"list1": {"values": ["autumn"]}, "list1#add": ["winter"]})
    assert pins == {"list1": ["autumn"]} and edits == {"list1": {"add": ["winter"]}}
    # off wins over a selection; a choice the prompt doesn't have (an old detail id) is passed by
    pins, edits, chosen = expand(porch, {"list1": {"values": ["autumn"], "off": True}, f"{MAN}.age": {"values": ["70"]},
                                         "gone": {"values": ["x"]}, "pet": {"off": True}})
    assert pins == {} and edits == {"list1": {"off": True}} and set(chosen) == {"pet"} and chosen["pet"].off


def test_seeds_off_and_as_written_read_back_as_sent(porch):
    sent = {MAN: {"seeds": {"descent": {"values": ["Kenyan"], "groups": {"region": ["Sub-Saharan Africa"]}},
                            "gender": {"values": ["man"]}}},
            "pet": {"as_written": True}}
    _, _, chosen = expand(porch, sent)
    assert chosen[MAN].pins.descent == ("Kenyan",) and chosen[MAN].pins.regions == ("Sub-Saharan Africa",)
    assert chosen[MAN].to_dict() == sent[MAN] and chosen["pet"].to_dict() == {"as_written": True}


def test_any_and_empty_are_no_choice(porch):
    assert expand(porch, {MAN: {"any": True}, "pet": {}, "list1": {"any": True}}) == ({}, {}, {})


def test_keep_choices_map_to_values(porch):
    assert kept(porch, {"pet": "gray parrot", "Season": ["autumn"], "Elderly African man": "a stooped man"}) == {
        "pet": {"values": ["gray parrot"]}, "list1": {"values": ["autumn"]}, MAN: {"values": ["a stooped man"]}}
    with pytest.raises(UnknownChoiceError, match="isn't a choice"):
        kept(porch, {"hat": "a fedora"})


def test_a_kept_value_holds_whether_or_not_its_pool_has_it(porch, profile):
    one = pool_of(porch, profile, "pet")[3]
    for value in (one, "gray parrot in a cage"):
        _, _, chosen = expand(porch, kept(porch, {"Pet": value}))
        for seed in range(3):
            r = prep.realize(porch, seed=seed, profile_id=profile, chosen=chosen)
            assert {d.id: d.value for d in r.draws}["pet"] == value and value in r.prompt


# --------------------------------------------------------------------------- the routes

async def _prepared(profile, monkeypatch):
    _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    entry = await ready(PORCH_PROMPT, profile)
    client = _client(monkeypatch, profile)
    out = client.post("/api/prompt-programs/prepare", json={"tool_id": "t", "prompt": PORCH_PROMPT}).json()
    return client, out, entry


async def test_prepare_has_one_choice_per_slot(profile, monkeypatch):
    _, out, _ = await _prepared(profile, monkeypatch)
    assert [(c["id"], c["kind"]) for c in out["choices"]] == [(MAN, "variants"), ("pet", "variants"), ("list1", "pick")]
    assert [s["state"] for s in out["slots"]] == ["ready", "ready"]


async def test_pools_lists_each_slots_variants_and_echoes_its_choice(profile, monkeypatch):
    client, out, _ = await _prepared(profile, monkeypatch)
    body = {"tool_id": "t", "prompt": PORCH_PROMPT, "key": out["key"]}
    got = client.post("/api/prompt-programs/pools", json=body).json()
    pet = got["choices"]["pet"]
    assert pet["kind"] == "variants" and pet["state"] == "ready" and pet["more"] is False and pet["chosen"] is None
    assert pet["options"] == [v["text"] for v in pet["variants"]] and len(pet["options"]) == 30
    assert "person" in got["choices"][MAN] and "person" not in pet and got["more"] == []
    one = pet["options"][2]
    got = client.post("/api/prompt-programs/pools",
                      json={**body, "choices": {"pet": {"values": [one]}, "pet#add": ["box of kittens"]}}).json()
    pet = got["choices"]["pet"]
    assert pet["chosen"] == {"values": [one]} and pet["variants"][-1]["own"] and pet["options"][-1] == "box of kittens"


async def test_preview_draws_with_the_choices(profile, monkeypatch):
    import prompt_programs.fix as fix

    async def no_judge(entry, project_id=None):
        return None
    monkeypatch.setattr(fix, "await_judge", no_judge)
    client, _, entry = await _prepared(profile, monkeypatch)
    man = pool_of(entry, profile, MAN)[0]
    body = {"tool_id": "t", "prompt": PORCH_PROMPT,
            "choices": {"pet": {"off": True}, "list1": {"off": True}, MAN: {"values": [man]}}}
    for seed in range(4):
        r = client.post("/api/prompt-programs/preview", json={**body, "seed": seed}).json()
        drawn = {d["id"]: d["value"] for d in r["draws"]}
        assert drawn == {MAN: man} and "with his" not in r["prompt"]
        assert r["prompt"].endswith("reading on a porch, evening") and "summer" not in r["prompt"]


async def test_options_writes_more_like_these(profile, monkeypatch):
    client, out, entry = await _prepared(profile, monkeypatch)
    before = pool_of(entry, profile, "pet")
    body = {"tool_id": "t", "prompt": PORCH_PROMPT, "key": out["key"], "choice_id": "pet"}
    r = client.post("/api/prompt-programs/options", json=body)
    assert r.status_code == 200
    new = r.json()["options"]
    assert len(new) == 20 and not set(new) & set(before)
    assert pool_of(entry, profile, "pet") == before + new
    gone = client.post("/api/prompt-programs/options", json={**body, "choice_id": "hat"})
    assert gone.status_code == 422
