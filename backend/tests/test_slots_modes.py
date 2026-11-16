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
    varied = await ready(PROMPT, profile, modes={"central_park": "kind"})
    assert len(model.asked) == 2
    assert 'chose to see ⟨1⟩ as a kind of thing' in model.asked[1][-1]["content"]
    s = _slot(varied)
    assert not s.get("one") and s["mode"] == "kind"
    assert varied["key"] != own["key"] and s["pool"] != _slot(own)["pool"]
    assert varied["modes"] == {"1": "kind"}

    # Back to the reader's own way: its reading, entry and pool, with no call.
    again = await ready(PROMPT, profile)
    assert len(model.asked) == 2 and again["key"] == own["key"] and _slot(again)["pool"] == _slot(own)["pool"]

    # Flesh out what the reader already reads as one thing: its own reading and pool serve, no call.
    fleshed = await ready(PROMPT, profile, modes={"central_park": "one"})
    assert len(model.asked) == 2 and _slot(fleshed)["one"] is True
    assert _slot(fleshed)["pool"] == _slot(own)["pool"]

    # Varied again: the cached varied reading, no call.
    await ready(PROMPT, profile, modes={"central_park": "kind"})
    assert len(model.asked) == 2

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
