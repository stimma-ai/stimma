"""An edit keeps what was read: a slot read before an edit stays ready with its reading (and its
narrowing and written options) while one small call checks whether the edit changes it; only
the parts it changes are read again, quietly, and only new parts show as being read."""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import pytest

from prompt_programs import program as prep
from prompt_programs import reader, slots
from prompt_programs.fluent import start_options
from prompt_programs.judge import FluentSettings
from prompt_programs.options import OptionFiller, OptionStore

from test_prompt_program_fluent import FakeGen
from test_slots_fill import AFRICAN, ELDERLY, PORCH_PROMPT, PORCH_READING
from test_slots_reader import _client, profile  # noqa: F401  (the fixture)

BEFORE = PORCH_PROMPT
AFTER = BEFORE.replace("with his <pet>,", "with his <pet> and a <mug>,")
MAN, PET = PORCH_READING["slots"]
MUG = {"kind": "free", "label": "Mug", "lead": " and a",
       "free": {"about": "a mug on the porch", "kinds": ["enamel camp mug", "chipped diner mug", "tin cup"],
                "instead": []}}
READINGS = {"elderly African man": MAN, "pet": PET, "mug": MUG}
ON = FluentSettings(generate_options=True, fix_model="off")


class Model:
    """The reader answers each part from READINGS (a part's reading may be swapped with
    `fresh`), narrowing answers with fixed subsets, and the edit check with `check`: the set of
    part numbers the edit changes, a reply as it stands, or an exception to raise. `hold` waits
    on `go` before answering the check or one part's reading. Records every call."""

    def __init__(self, check: Any = frozenset(), fresh: Optional[Dict[str, Any]] = None,
                 hold: Optional[str] = None):
        self.check, self.fresh, self.hold = check, fresh or {}, hold
        self.reads: List[str] = []
        self.checks: List[Dict[str, Any]] = []
        self.narrows = 0
        self.go = asyncio.Event()

    async def __call__(self, messages, project_id, max_tokens):
        system, user = messages[0]["content"], messages[-1]["content"]
        if system == reader.CHECK_SYSTEM:
            self.checks.append({"messages": messages, "max_tokens": max_tokens})
            if self.hold == "check":
                await self.go.wait()
            if isinstance(self.check, Exception):
                raise self.check
            if isinstance(self.check, (set, frozenset)):
                count = len(re.findall(r"^\d+\. ⟨", user, re.M))
                return json.dumps({str(i): "changed" if i in self.check else "same" for i in range(1, count + 1)})
            return self.check
        if system.startswith("You read the parts of an image prompt"):
            asked = user.rsplit("\n", 1)[-1]
            slot = re.search(r'⟨(\d+)⟩ "([^"]+)"', asked)
            if slot:
                n, words = int(slot.group(1)), slot.group(2)
                self.reads.append(words)
                if self.hold == words:
                    await self.go.wait()
                r = self.fresh.get(words) or READINGS[words]
                return json.dumps({"slots": [{**r, "n": n}], "lists": []})
            n = int(re.search(r"\{L(\d+)\}", asked).group(1))
            self.reads.append(f"L{n}")
            return json.dumps({"slots": [], "lists": [{"n": n, "label": "Season"}]})
        self.narrows += 1
        if user.startswith('The list "Age"'):
            return json.dumps(ELDERLY)
        if user.startswith('The list "Descent"'):
            return json.dumps(AFRICAN)
        return "[]"


@pytest.fixture
def model(profile, monkeypatch):  # noqa: F811
    monkeypatch.setattr(slots, "_changed", set())
    m = Model()
    monkeypatch.setattr(prep, "ask_model", m)
    return m


async def _ready(prompt: str, **kw: Any) -> Dict[str, Any]:
    await slots.prepare(prompt, profile_id="p", **kw)
    await slots.idle()
    return await slots.prepare(prompt, profile_id="p", start=False)


def _states(entry: Dict[str, Any]) -> List[str]:
    return [s["state"] for s in entry["slots"]]


def _bare(r: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in r.items() if k not in ("n", "seen")}


async def test_a_slot_added_on_the_line_keeps_the_others_read_with_one_small_check(model):
    first = await _ready(BEFORE)
    assert model.reads == ["elderly African man", "pet", "L1"] and model.narrows
    narrows = model.narrows
    # The editor looks the edited prompt up, saying which prompt it shows: no model call, the
    # parts it had are ready with their readings, and only the new slot is being read.
    look = await slots.prepare(AFTER, profile_id="p", start=False, shown=first["key"])
    assert _states(look) == ["ready", "ready", "reading"] and look["lists"][0]["state"] == "ready"
    assert look["slots"][0]["kind"] == "person" and look["slots"][0]["details"] == first["slots"][0]["details"]
    assert look["reading"] and model.reads == ["elderly African man", "pet", "L1"] and not model.checks
    entry = await _ready(AFTER, shown=first["key"])
    # One check for every part read before; the new slot read on its own; nothing narrowed again.
    assert len(model.checks) == 1 and model.reads[3:] == ["mug"] and model.narrows == narrows
    asked = model.checks[0]["messages"][-1]["content"]
    assert "⟨elderly African man⟩" in asked and "⟨pet⟩" in asked and "⟨{summer|autumn}⟩" in asked
    assert "before:\nan ⟨elderly African man⟩ reading on a porch with his <pet>, {summer|autumn} evening" in asked
    assert asked.startswith("note: she is his granddaughter, visiting\n\n1. ⟨elderly African man⟩, read as: {")
    # far cheaper than a reading: a short question and room for a word per part
    assert len(reader.CHECK_SYSTEM) + len(asked) < len(reader.system_text()) / 5
    assert model.checks[0]["max_tokens"] <= 48
    assert _states(entry) == ["ready", "ready", "ready"] and not entry["reading"] and not entry["working"]
    assert [_bare(r) for r in entry["readings"]["slots"][:2]] == [_bare(r) for r in first["readings"]["slots"]]
    assert entry["filters"]["elderly_african_man.age"] == first["filters"]["elderly_african_man.age"]
    # Kept: the next prepare asks nothing at all.
    await _ready(AFTER, shown=first["key"])
    assert len(model.checks) == 1 and len(model.reads) == 4
    assert "mug" in prep.realize(entry, seed=2).prompt


async def test_the_earlier_readings_serve_while_the_check_runs(model, monkeypatch):
    model.hold = "check"
    first = await _ready(BEFORE)
    await slots.prepare(AFTER, profile_id="p", shown=first["key"])
    for _ in range(50):
        await asyncio.sleep(0.01)
        if model.checks and model.reads[3:] == ["mug"]:
            break
    # The route passes the shown key along; a lookup without it finds the earlier readings too.
    out = _client(monkeypatch, "p").post("/api/prompt-programs/prepare", json={
        "tool_id": "t", "prompt": AFTER, "cache_only": True, "key": first["key"]}).json()
    assert [s["state"] for s in out["slots"]][:2] == ["ready", "ready"] and out["working"]
    now = await slots.prepare(AFTER, profile_id="p", start=False)
    assert _states(now)[:2] == ["ready", "ready"] and now["working"]
    drawn = prep.realize(now, seed=4)   # a generation meanwhile draws from the earlier readings
    assert "elderly_african_man.age" in {d.id for d in drawn.draws}
    model.go.set()
    await slots.idle()
    assert len(model.checks) == 1 and model.reads[3:] == ["mug"]


async def test_a_part_the_edit_changes_is_read_again_quietly(model):
    first = await _ready(BEFORE)
    model.check, model.hold = {2}, "pet"
    model.fresh = {"pet": {**PET, "label": "Porch pet"}}
    await slots.prepare(AFTER, profile_id="p", shown=first["key"])
    for _ in range(50):
        await asyncio.sleep(0.01)
        if model.reads.count("pet") == 2:
            break
    # The pet is being read again; meanwhile it stands as it was read, never "reading".
    now = await slots.prepare(AFTER, profile_id="p", start=False)
    assert now["slots"][1]["state"] == "ready" and now["slots"][1]["label"] == "Pet" and now["working"]
    model.go.set()
    await slots.idle()
    done = await slots.prepare(AFTER, profile_id="p", start=False)
    assert done["slots"][1]["label"] == "Porch pet" and not done["reading"]
    assert sorted(model.reads[3:]) == ["mug", "pet"] and len(model.checks) == 1


@pytest.mark.parametrize("check", ["not json", '{"0": "same", "1": "same", "2": "same"}', '{"1": "maybe"}',
                                   RuntimeError("down")])
async def test_a_check_that_fails_or_cant_be_read_reads_them_again_quietly(model, check):
    first = await _ready(BEFORE)
    model.check = check
    look = await slots.prepare(AFTER, profile_id="p", shown=first["key"])
    assert _states(look) == ["ready", "ready", "reading"]
    await slots.idle()
    done = await slots.prepare(AFTER, profile_id="p", start=False)
    assert _states(done) == ["ready", "ready", "ready"] and not done["reading"]
    assert sorted(model.reads[3:]) == ["L1", "elderly African man", "mug", "pet"]
    assert not any(s.get("degraded") for s in done["slots"])


async def test_a_new_note_is_checked_once_for_every_part(model):
    first = await _ready(BEFORE)
    edited = "# at dawn\n" + BEFORE
    await _ready(edited, shown=first["key"])
    assert len(model.checks) == 1 and len(model.reads) == 3
    asked = model.checks[0]["messages"][-1]["content"]
    assert ("before:\nnote: she is his granddaughter, visiting\nan ⟨elderly African man⟩" in asked
            and "now:\nnote: at dawn\nnote: she is his granddaughter, visiting\nan ⟨elderly African man⟩" in asked)


async def test_a_prompt_never_prepared_before_is_read_as_usual(model):
    look = await slots.prepare(AFTER, profile_id="p", start=False)
    assert _states(look) == ["reading", "reading", "reading"]
    await _ready(AFTER)
    assert not model.checks and sorted(model.reads) == ["L1", "elderly African man", "mug", "pet"]


async def test_a_kept_slot_keeps_its_written_options(model, tmp_path):
    first = await _ready(BEFORE)
    store = OptionStore(tmp_path / "options")
    gen = FakeGen()
    filler = OptionFiller(store, gen)
    assert start_options(first, store=store, filler=filler, cfg=ON)
    await filler.drain()
    written = len(gen.calls)
    entry = await _ready(AFTER, shown=first["key"])
    start_options(entry, store=store, filler=filler, cfg=ON)
    await filler.drain()
    # Only the new slot's options are written; the man's and the pet's pools are the ones they had.
    assert written and gen.calls[written:] and all(j.spec.id.startswith("mug") for j in gen.calls[written:])
    # A part the edit changes gets options written for the prompt as it is now.
    model.check = {2}
    again = await _ready(AFTER.replace("evening", "evening light"), shown=entry["key"])
    count = len(gen.calls)
    start_options(again, store=store, filler=filler, cfg=ON)
    await filler.drain()
    assert any(j.spec.id == "pet" for j in gen.calls[count:])
    assert not any(j.spec.id.startswith("elderly_african_man") for j in gen.calls[count:])


def test_the_check_reply_names_each_part():
    assert reader.parse_changed('{"1": "same", "2": "changed"}', 2) == {2}
    assert reader.parse_changed('```json\n{"1": "Same", "2": "same"}\n```', 2) == set()
    assert reader.parse_changed('{"1": "same"}', 2) == {2}   # a part left out is read again
    assert reader.parse_changed('{"0": "same"}', 1) is None   # counted from 0: can't be trusted
    assert reader.parse_changed('{"1": true}', 1) is None
    assert reader.parse_changed('["same"]', 1) is None


async def test_an_edit_on_another_line_writes_no_options_and_asks_nothing(model, tmp_path):
    before = BEFORE + "\nlate summer light"
    first = await _ready(before)
    store = OptionStore(tmp_path / "options")
    gen = FakeGen()
    filler = OptionFiller(store, gen)
    assert start_options(first, store=store, filler=filler, cfg=ON)
    await filler.drain()
    written, reads, narrows = len(gen.calls), len(model.reads), model.narrows
    entry = await _ready(before.replace("late summer light", "soft late summer light, slight haze"), shown=first["key"])
    assert entry["template"] != first["template"]
    assert start_options(entry, store=store, filler=filler, cfg=ON) == []   # every pool is already written
    await filler.drain()
    assert len(gen.calls) == written
    assert (len(model.reads), model.narrows, model.checks) == (reads, narrows, [])


async def test_a_lead_the_edit_takes_away_is_read_again_and_one_it_keeps_is_kept(model):
    model.fresh = {"mug": {**MUG, "lead": " with a"}}
    first = await _ready("a table with a <mug>")
    assert first["readings"]["slots"][0]["lead"] == " with a"
    # "with a" no longer stands before it: read again (no check can say what the lead is now),
    # its old lead dropped meanwhile, so leaving it out never leaves "beside a" hanging.
    model.hold = "mug"
    await slots.prepare("a table beside a <mug>", profile_id="p", shown=first["key"])
    for _ in range(50):
        await asyncio.sleep(0.01)
        if model.reads.count("mug") == 2:
            break
    now = await slots.prepare("a table beside a <mug>", profile_id="p", start=False)
    assert now["slots"][0]["state"] == "ready" and now["readings"]["slots"][0]["lead"] == ""
    model.go.set()
    await slots.idle()
    assert model.reads == ["mug", "mug"] and not model.checks
    # More words further from it: "with a" still stands right before it, and the edit is checked.
    model.hold = None
    kept = await _ready("a wooden table with a <mug>", shown=first["key"])
    assert len(model.checks) == 1 and model.reads == ["mug", "mug"]
    assert kept["readings"]["slots"][0]["lead"] == " with a"


def test_parts_are_matched_by_where_they_stand_and_a_match_the_text_cant_settle_is_dropped():
    from prompt_programs.slots import match_marks, parse
    # the first of two mugs removed: the one left was the second
    assert match_marks(parse("a <mug> on the shelf and a <mug> on the desk"), parse("a <mug> on the desk")) == {1: 0}
    # two identical mugs, one removed: which one can't be told, so neither is matched
    assert match_marks(parse("a <mug> and a <mug>"), parse("a <mug>")) == {}
    # a slot added among them moves nothing
    assert match_marks(parse("a <man> with his <pet>, {a|b}"), parse("a <man> with his <pet> and a <mug>, {a|b}")) == \
        {0: 0, 1: 1, 2: 3}


async def test_the_editor_is_told_which_part_each_was(model, monkeypatch):
    model.fresh = {"mug": MUG}
    first = await _ready("a <mug> on the shelf and a <mug> on the desk, {red|blue}")
    assert [s["id"] for s in first["slots"]] == ["mug", "mug_2"]
    edited = "a <mug> on the desk, {green|gray} and {red|blue}"
    look = await slots.prepare(edited, profile_id="p", start=False, shown=first["key"])
    assert look["was"] == {"from": first["key"], "ids": {"mug": "mug_2", "list2": "list1"}}
    assert look["slots"][0]["state"] == "ready"   # carried from the second mug
    out = _client(monkeypatch, "p").post("/api/prompt-programs/prepare", json={
        "tool_id": "t", "prompt": edited, "cache_only": True, "key": first["key"]}).json()
    assert out["from"] == first["key"] and out["slots"][0]["was"] == "mug_2"
    lists = {c["id"]: c.get("was") for c in out["choices"] if c.get("source") == "list"}
    assert lists == {"list1": None, "list2": "list1"}
    # identical mugs, one removed: the one left is new to the editor, and read as new
    twin = await _ready("a <mug> and a <mug>")
    left = await slots.prepare("a <mug>", profile_id="p", start=False, shown=twin["key"])
    assert left["was"] == {"from": twin["key"], "ids": {}} and left["slots"][0]["state"] == "reading"


async def test_a_kept_lead_is_kept_as_it_stands_now_so_leaving_the_slot_out_takes_it_whole(model):
    model.fresh = {"mug": {**MUG, "lead": " with a"}}
    first = await _ready("a table with a <mug>")
    entry = await _ready("a table\nwith a <mug>", shown=first["key"])
    assert len(model.checks) == 1 and model.reads == ["mug"]   # kept: the edit was checked, not read again
    assert entry["readings"]["slots"][0]["lead"] == "with a"
    left = prep.realize(entry, seed=1, edits={"mug": {"off": True}}).prompt
    assert "with a" not in left.lower() and left.strip().lower().startswith("a table")


def test_a_lead_is_fitted_to_the_text_before_its_slot():
    assert reader.fit_lead(" with a", "a table\nwith a ".split("\n")[-1]) == "with a"
    assert reader.fit_lead(" with a", "a wooden table with a ") == " with a"
    assert reader.fit_lead(" with a", "a table beside a ") is None
    assert reader.fit_lead("", "anything ") == ""
