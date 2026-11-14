"""An edit keeps what was read: a slot read before an edit stays ready with its reading (and its
seeds and its pool of variants) while one small call checks whether the edit changes it; only
the parts it changes are read again, quietly, and only new parts show as being read."""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import pytest

from prompt_programs import program as prep
from prompt_programs import reader, slots
from prompt_programs import variant_pools as P
from prompt_programs.choices import expand

from test_slots_reader import AFRICAN, ELDERLY, PORCH_PROMPT, PORCH_READING, _client, ready
from test_slots_reader import profile  # noqa: F401  (the fixture)

BEFORE = PORCH_PROMPT
AFTER = BEFORE.replace("with his <pet>,", "with his <pet> and a <mug>,")
MAN, PET = PORCH_READING["slots"]
MUG = {"kind": "free", "label": "Mug", "lead": " and a",
       "free": {"about": "a mug on the porch", "kinds": ["enamel camp mug", "chipped diner mug", "tin cup"],
                "instead": []}}
READINGS = {"elderly African man": MAN, "pet": PET, "mug": MUG}


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
        from prompt_programs.ages import READING_SYSTEM
        if system == READING_SYSTEM:   # how old the people read: asked again for each wording of the prompt
            return '{"age": "adult"}'
        self.narrows += 1
        if user.startswith('The list "Age"'):
            return json.dumps(ELDERLY)
        if user.startswith('The list "Descent"'):
            return json.dumps(AFRICAN)
        return "[]"


@pytest.fixture
def model(profile, monkeypatch):  # noqa: F811
    m = Model()
    monkeypatch.setattr(prep, "ask_model", m)
    return m


async def _ready(prompt: str, **kw: Any) -> Dict[str, Any]:
    return await ready(prompt, "p", **kw)


def _pools(entry: Dict[str, Any]) -> Dict[str, str]:
    return {s["id"]: s["pool"] for s in entry["slots"]}


def _written() -> List[str]:
    """The slots' words of every pool write so far, in order: a session's turns (the same slot in
    the same prompt) counted once."""
    seen: Dict[tuple, str] = {}
    for c in P.ASK.calls:
        seen.setdefault((c["words"], c["first"].split("Marked part:")[0]), c["words"])
    return list(seen.values())


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
    assert look["slots"][0]["kind"] == "person" and look["slots"][0]["pool"] == first["slots"][0]["pool"]
    assert look["reading"] and model.reads == ["elderly African man", "pet", "L1"] and not model.checks
    entry = await _ready(AFTER, shown=first["key"])
    # One check for every part read before; the new slot read on its own; nothing narrowed again.
    assert len(model.checks) == 1 and model.reads[3:] == ["mug"] and model.narrows == narrows
    asked = model.checks[0]["messages"][-1]["content"]
    assert "⟨elderly African man⟩" in asked and "⟨pet⟩" in asked and "⟨{summer|autumn}⟩" in asked
    # the other parts as their bare words: adding one isn't an edit to weigh
    assert "before:\nan ⟨elderly African man⟩ reading on a porch with his pet, {summer|autumn} evening" in asked
    assert "now:\nan ⟨elderly African man⟩ reading on a porch with his pet and a mug, {summer|autumn} evening" in asked
    assert asked.startswith("note: she is his granddaughter, visiting\n\n1. ⟨elderly African man⟩, read as: {")
    # far cheaper than a reading: a short question and room for a word per part
    assert len(reader.CHECK_SYSTEM) + len(asked) < len(reader.system_text()) / 5
    assert model.checks[0]["max_tokens"] <= 48
    assert _states(entry) == ["ready", "ready", "ready"] and not entry["reading"] and not entry["working"]
    assert [_bare(r) for r in entry["readings"]["slots"][:2]] == [_bare(r) for r in first["readings"]["slots"]]
    assert entry["seeds"]["elderly_african_man"] == first["seeds"]["elderly_african_man"]
    # Kept: the next prepare asks nothing at all.
    await _ready(AFTER, shown=first["key"])
    assert len(model.checks) == 1 and len(model.reads) == 4
    assert "mug" in prep.realize(entry, seed=2, profile_id="p").prompt


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
    drawn = prep.realize(now, seed=4, profile_id="p")   # a generation meanwhile draws from the earlier pools
    assert {d.id: d.source for d in drawn.draws}["elderly_african_man"] == "variant"
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


async def test_a_kept_slot_keeps_its_pool(model):
    first = await _ready(BEFORE)
    assert sorted(_written()) == ["elderly African man", "pet"]
    entry = await _ready(AFTER, shown=first["key"])
    # Only the new slot's pool is written; the man's and the pet's are the ones they had.
    assert _written()[2:] == ["mug"]
    assert {k: v for k, v in _pools(entry).items() if k != "mug"} == _pools(first)
    # A part the edit changes is read again, and gets a pool for the line as it is now.
    model.check = {2}
    again = await _ready(AFTER.replace("evening", "evening light"), shown=entry["key"])
    assert _written()[3:] == ["pet"]
    assert again["slots"][1]["pool"] != entry["slots"][1]["pool"]
    assert [again["slots"][i]["pool"] for i in (0, 2)] == [entry["slots"][i]["pool"] for i in (0, 2)]


async def test_a_reread_slot_draws_from_its_old_pool_until_its_new_one_is_written(model, monkeypatch):
    first = await _ready(BEFORE)
    model.check = {2}
    edited = BEFORE.replace("evening", "evening light")
    held = asyncio.Event()
    writer = P.ASK

    async def slow(messages, project_id, max_tokens, temperature=0.8):
        await held.wait()
        return await writer(messages, project_id, max_tokens, temperature)
    monkeypatch.setattr(P, "ASK", slow)
    await slots.prepare(edited, profile_id="p", shown=first["key"])
    await slots.idle()
    now = await slots.prepare(edited, profile_id="p", start=False, shown=first["key"])
    pet = now["slots"][1]
    assert pet["pool"] != first["slots"][1]["pool"] and pet["stand_in"] == first["slots"][1]["pool"]
    old = {v["text"] for v in P.store_for("p").variants(first["slots"][1]["pool"])}
    assert {d.id: d.value for d in prep.realize(now, seed=1, profile_id="p").draws}["pet"] in old
    held.set()
    await P.writer_for("p").drain()


def test_the_check_reply_names_each_part():
    assert reader.parse_changed('{"1": "same", "2": "changed"}', 2) == {2}
    assert reader.parse_changed('```json\n{"1": "Same", "2": "same"}\n```', 2) == set()
    assert reader.parse_changed('{"1": "same"}', 2) == {2}   # a part left out is read again
    assert reader.parse_changed('{"0": "same"}', 1) is None   # counted from 0: can't be trusted
    assert reader.parse_changed('{"1": true}', 1) is None
    assert reader.parse_changed('["same"]', 1) is None


async def test_an_edit_on_another_line_the_check_calls_the_same_writes_no_pools(model):
    before = BEFORE + "\nlate summer light"
    first = await _ready(before)
    written, reads, narrows = len(_written()), len(model.reads), model.narrows
    after = before.replace("late summer light", "soft late summer light, slight haze")
    look = await slots.prepare(after, profile_id="p", start=False, shown=first["key"])
    assert look["reading"] and _pools(look) == _pools(first)   # kept, to be checked
    entry = await _ready(after, shown=first["key"])
    assert entry["template"] != first["template"] and not entry["reading"]
    assert _pools(entry) == _pools(first) and len(_written()) == written   # every pool is already written
    assert (len(model.reads), model.narrows, len(model.checks)) == (reads, narrows, 1)
    asked = model.checks[0]["messages"][-1]["content"]
    assert "elsewhere in the prompt:\nlate summer light" in asked
    assert "elsewhere in the prompt:\nsoft late summer light, slight haze" in asked
    # Kept, and checked against the prompt as it is now: the next prepare asks nothing.
    await _ready(after, shown=first["key"])
    assert len(model.checks) == 1 and len(model.reads) == reads


async def test_a_scene_edited_on_another_line_writes_the_pool_again_its_old_one_standing_in(model):
    # "living room" to "beach" on line 1: a <light> on line 2 was written for a living room. The
    # check says it changed: it is read again, its pool keyed anew, the old pool standing in.
    before = "a woman in her living room\nlit by <light>"
    model.check = {1}
    light = {"kind": "light", "label": "Light", "lead": "lit by", "light": {"list": ""}}
    READINGS["light"] = light
    try:
        first = await _ready(before)
        old = _pools(first)["light"]
        assert P.store_for("p").has(old)
        model.hold = "light"
        after = before.replace("living room", "beach house on the beach")
        await slots.prepare(after, profile_id="p", shown=first["key"])
        for _ in range(100):
            await asyncio.sleep(0.01)
            if model.reads.count("light") == 2:
                break
        meanwhile = await slots.prepare(after, profile_id="p", start=False, shown=first["key"])
        assert meanwhile["slots"][0]["state"] == "ready" and meanwhile["reading"]
        model.go.set()
        entry = await _ready(after, shown=first["key"])
        assert len(model.checks) == 1 and model.reads.count("light") == 2
        new = _pools(entry)["light"]
        assert new != old and P.store_for("p").has(new) and P.store_for("p").has(old)
        assert entry["readings"]["slots"][0]["seen"]["scene"] == reader.scene_mark("a woman in her beach house on the beach")
        # the next prepare asks nothing, and back to the living room the first pool is its own again
        await _ready(after, shown=entry["key"])
        assert len(model.checks) == 1
        back = await _ready(before, shown=entry["key"])
        assert len(model.checks) == 2 and _pools(back)["light"] != new   # the edit back is checked too
    finally:
        READINGS.pop("light", None)


async def test_a_one_line_prompt_edited_on_its_line_costs_no_more_calls(model):
    first = await _ready("a <mug> on a table")
    reads = len(model.reads)
    await _ready("a <mug> on a wooden table", shown=first["key"])
    assert len(model.checks) == 1 and len(model.reads) == reads
    asked = model.checks[0]["messages"][-1]["content"]
    assert "elsewhere in the prompt" not in asked


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
    _, _, chosen = expand(entry, {"mug": {"off": True}})
    left = prep.realize(entry, seed=1, profile_id="p", chosen=chosen).prompt
    assert "with a" not in left.lower() and left.strip().lower().startswith("a table")


def test_a_lead_is_fitted_to_the_text_before_its_slot():
    assert reader.fit_lead(" with a", "a table\nwith a ".split("\n")[-1]) == "with a"
    assert reader.fit_lead(" with a", "a wooden table with a ") == " with a"
    assert reader.fit_lead(" with a", "a table beside a ") is None
    assert reader.fit_lead("", "anything ") == ""


# --------------------------------------------------------------------------- what a person wears, through an edit

BOAT = "a <woman> on a research boat,\nin a <wetsuit>"
DIVER = {"kind": "person", "label": "Woman", "lead": "a",
         "person": {"noun": "woman", "presentation": "feminine", "stated": {}, "vary": ["age", "descent", "build", "hair"],
                    "clothes": "", "clothes_part": 2, "outfit": "", "outfit_examples": []}}
DRESSED = {**DIVER, "person": {**DIVER["person"], "clothes_part": 0, "outfit": "person.outfit.summer"}}
WORN = {"wetsuit": {"kind": "free", "label": "Wetsuit", "lead": " in a",
                    "free": {"about": "the woman's wetsuit", "kinds": ["shorty wetsuit", "drysuit", "full wetsuit"],
                             "instead": []}},
        "fish": {"kind": "free", "label": "Fish", "lead": " holding a",
                 "free": {"about": "a fish she holds", "kinds": ["mackerel", "snapper", "small tuna"], "instead": []}}}


def _person(entry: Dict[str, Any]) -> Dict[str, Any]:
    return next(r for r in entry["readings"]["slots"] if r["kind"] == "person")["person"]


async def test_a_carried_person_whose_clothes_slot_is_gone_is_read_again(model):
    model.fresh.update(WORN, woman=DIVER)
    first = await _ready(BOAT)
    assert _person(first)["clothes_part"] == {"n": 2, "words": "wetsuit"}
    model.reads.clear()
    model.fresh["woman"] = DRESSED
    # The woman's own line is as it was, but what she wore is gone: she is read again, not carried.
    entry = await _ready(BOAT.replace("in a <wetsuit>", "in a sun hat"), shown=first["key"])
    assert model.reads == ["woman"]
    assert "clothes_part" not in _person(entry) and _person(entry)["outfit"] == "person.outfit.summer"
    assert "person.outfit.summer" in {b["list"] for b in entry["seeds"]["woman"]["banks"]}
    assert entry["reading"] is False


async def test_a_carried_person_follows_their_clothes_slot_to_its_new_number(model):
    model.fresh.update(WORN, woman=DIVER)
    first = await _ready(BOAT)
    model.reads.clear()
    entry = await _ready(BOAT.replace("in a <wetsuit>", "holding a <fish> in a <wetsuit>"), shown=first["key"])
    assert model.reads == ["fish"]   # the woman is carried; the wetsuit's edit is checked, not read
    assert _person(entry)["clothes_part"] == {"n": 3, "words": "wetsuit"}
    assert not any(b["list"].startswith("person.outfit") for b in entry["seeds"]["woman"]["banks"])
    assert entry["reading"] is False
