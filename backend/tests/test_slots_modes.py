"""Vary or Flesh out, chosen by the user over the reader's reading (`names`): each mode a reading,
an entry and a pool of its own; the reader told the choice and held to it; [exact text] never sent."""

import json

from prompt_programs import reader, slots
from prompt_programs.choices import modes

from prompt_programs import variant_pools as P
from test_slots_reader import FakeModel, _use, profile  # noqa: F401  (profile: the fixture)

PROMPT = "a dog asleep in <Central Park> at [EXACT DAWN MARK]"


def park(names: str) -> str:
    return json.dumps({"slots": [{"n": 1, "kind": "free", "label": "Central Park", "lead": "", "names": names,
                                  "category": "", "free": {"about": "the park", "lists": []}}]})


async def ready(prompt, profile, **kw):
    """Prepare with these modes, let the background work land, and look again with them."""
    await slots.prepare(prompt, profile_id=profile, **kw)
    await slots.idle()
    await P.writer_for(profile).drain()
    await slots.idle()
    return await slots.prepare(prompt, profile_id=profile, start=False, **kw)


def _slot(entry):
    return entry["slots"][0]


def test_modes_come_from_the_choices():
    assert modes({"central_park": {"mode": "one"}, "dog": {"mode": "kind", "values": ["x"]},
                  "cat": {"mode": "other"}, "list1": {"values": ["a"]}, "x#add": ["y"]}) == {
        "central_park": "one", "dog": "kind"}
    assert modes(None) == {}


async def test_a_chosen_mode_is_its_own_reading_entry_and_pool(profile, monkeypatch):
    model = _use(monkeypatch, FakeModel(park("one")))
    own = await ready(PROMPT, profile)
    assert _slot(own)["one"] is True and "mode" not in _slot(own) and len(model.asked) == 1
    assert "chose to see" not in model.asked[0][-1]["content"]

    # Vary it: read again, told so; the model's "one" doesn't stand over the user's choice.
    # (a reading of one specific thing with no kind_of is asked again once, then varies as before)
    varied = await ready(PROMPT, profile, modes={"central_park": "kind"})
    assert len(model.asked) == 3
    assert 'names one specific thing, and the user chose to vary it' in model.asked[1][-1]["content"]
    assert '"kind_of"' in model.asked[2][-1]["content"]
    s = _slot(varied)
    assert not s.get("one") and s["mode"] == "kind"
    assert varied["key"] != own["key"] and s["pool"] != _slot(own)["pool"]
    assert varied["modes"] == {"1": "kind"}

    # Back to the reader's own way: its reading, entry and pool, with no call.
    again = await ready(PROMPT, profile)
    assert len(model.asked) == 3 and again["key"] == own["key"] and _slot(again)["pool"] == _slot(own)["pool"]

    # Flesh out what the reader already reads as one thing: its own reading and pool serve, no call.
    fleshed = await ready(PROMPT, profile, modes={"central_park": "one"})
    assert len(model.asked) == 3 and _slot(fleshed)["one"] is True
    assert _slot(fleshed)["pool"] == _slot(own)["pool"]

    # Varied again: the cached varied reading, no call.
    await ready(PROMPT, profile, modes={"central_park": "kind"})
    assert len(model.asked) == 3

    for messages in model.asked:   # exact text never reaches the model
        assert all("DAWN MARK" not in str(m.get("content")) for m in messages)


async def test_flesh_out_holds_whatever_the_reader_answers(profile, monkeypatch):
    model = _use(monkeypatch, FakeModel(park("kind")))
    own = await ready(PROMPT, profile)
    assert not _slot(own).get("one")
    fleshed = await ready(PROMPT, profile, modes={"central_park": "one"})
    assert 'chose to see ⟨1⟩ as one specific thing' in model.asked[-1][-1]["content"]
    s = _slot(fleshed)
    assert s["one"] is True and s["mode"] == "one" and s["pool"] != _slot(own)["pool"]
    assert reader.mode_of(fleshed["readings"]["slots"][0]) == "one"


async def test_a_mode_for_a_slot_the_prompt_lacks_changes_nothing(profile, monkeypatch):
    _use(monkeypatch, FakeModel(park("one")))
    own = await ready(PROMPT, profile)
    other = await slots.prepare(PROMPT, profile_id=profile, start=False, modes={"gone": "kind", "central_park": "bogus"})
    assert other["key"] == own["key"]


def park_of(kind_of: str, category: str = "", names: str = "kind") -> str:
    return json.dumps({"slots": [{"n": 1, "kind": "free", "label": "Central Park", "lead": "", "names": names,
                                  "kind_of": kind_of, "category": category,
                                  "free": {"about": "the park", "lists": []}}]})


async def test_varying_a_named_thing_writes_other_members_of_its_kind(profile, monkeypatch):
    from prompt_programs.fluent import slot_job
    from prompt_programs.variants import messages
    model = _use(monkeypatch, FakeModel(park_of("big city park", category="Park", names="one")))
    varied = await ready(PROMPT, profile, modes={"central_park": "kind"})
    assert '"kind_of"' in model.asked[0][-1]["content"]
    s = _slot(varied)
    # the kind it is one of, and none of its words kept (a category the model gave anyway goes)
    assert s["kind_of"] == "big city park" and s["category"] == "" and not s.get("one")
    assert varied["seeds"][s["id"]].get("kind_of") is True
    job = slot_job(varied, s)
    assert job is not None and job.slot.keep() == [] and job.slot.kind_of == "big city park"
    text = messages(job.slot, *_one_spec())[-1]["content"]
    assert "another big city park" in text and 'is not "Central Park"' in text


def _one_spec():
    from prompt_programs.variants import Drawn, Seeds, Spec
    return Drawn(specs=[Spec()], short=[]), Seeds()


def test_kind_of_counts_only_when_the_user_chose_vary():
    from prompt_programs.slots import parse
    parsed = parse("a picnic in <Central Park>")
    seg = next(s for s in parsed.segments if s.kind == "slot")
    r = {"n": 1, "kind": "free", "names": "kind", "kind_of": "big city park", "category": "",
         "free": {"about": "the park", "lists": []}}
    assert "kind_of" not in reader.check_slot(dict(r), seg, "a picnic in ", [], parsed.prompt)
    assert reader.check_slot(dict(r), seg, "a picnic in ", [], parsed.prompt, mode="kind")["kind_of"] == "big city park"
    assert "kind_of" not in reader.check_slot(dict(r), seg, "a picnic in ", [], parsed.prompt, mode="one")
    long = {**r, "kind_of": "a very large and famous park that sits in the middle of a city"}
    assert "kind_of" not in reader.check_slot(long, seg, "a picnic in ", [], parsed.prompt, mode="kind")


def test_one_thing_varied_needs_its_kind_then_degrades_to_every_word_kept():
    from prompt_programs.slots import parse
    parsed = parse("a picnic in <Central Park>")
    seg = next(s for s in parsed.segments if s.kind == "slot")
    r = {"n": 1, "kind": "free", "names": "one", "category": "", "free": {"about": "the park", "lists": []}}
    try:
        reader.check_slot(dict(r), seg, "a picnic in ", [], parsed.prompt, mode="kind")
        raise AssertionError("asked again")
    except reader._Bad as e:
        assert "kind_of" in str(e)
    last = reader.check_slot(dict(r), seg, "a picnic in ", [], parsed.prompt, strict=False, mode="kind")
    assert "kind_of" not in last and reader.mode_of(last) == "kind"
