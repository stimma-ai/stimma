"""A vocabulary pack extends Fluent with data alone: the fictional test pack in
fixtures/vocab_packs/vael adds an elf sort of being with a clan list (looks per clan), a realms
table that weights the clans, elven dress, and a new kind of slot (a creature) with its own
questions, draw rules and writing rules. With the pack as a root, an elf draws a clan, a realm
weights it, a human beside it still draws a human heritage, and a creature is read and drawn by
its rules; a bad pack file is skipped with a logged reason. Faked model throughout."""

from __future__ import annotations

import asyncio
import json
import random
import shutil
from collections import Counter
from pathlib import Path

import pytest

from prompt_programs import reader, seeding, vocab
from prompt_programs import variants as V
from prompt_programs.slots import parse

PACK = Path(__file__).parent / "fixtures" / "vocab_packs" / "vael"


@pytest.fixture
def with_roots(monkeypatch):
    """Load the vocabulary with these extra roots for the test, the built-in one alone after."""
    def use(*roots: Path) -> vocab.Vocabulary:
        import os
        monkeypatch.setenv(vocab.ROOTS_ENV, os.pathsep.join(str(r) for r in roots))
        vocab.vocabulary.cache_clear()
        return vocab.vocabulary()
    yield use
    monkeypatch.delenv(vocab.ROOTS_ENV, raising=False)
    vocab.vocabulary.cache_clear()


@pytest.fixture
def pack(with_roots):
    return with_roots(PACK)


def _seg(prompt: str, n: int = 1):
    return [s for s in parse(prompt).segments if s.kind == "slot"][n - 1]


def _person(**kw):
    return {"n": 1, "kind": "person", "label": "Elf", "lead": "an", "category": "",
            "person": {"noun": "elf", "presentation": "", "stated": {}, "vary": ["age", "descent", "build", "hair"],
                       "outfit": "person.outfit.fantasy", **kw}}


async def _subset(leaf, phrase, *a, **k):
    return [v.text for v in leaf.values]   # narrowing keeps every value: the draw rules are what is tested


def _record(monkeypatch, reading, words, prompt, home=None):
    """A slot's narrowed seeds record, as prepare makes it (narrow_seeds with a fake narrowing)."""
    from prompt_programs import narrow, places
    monkeypatch.setattr(narrow, "subset", _subset)
    monkeypatch.setattr(places, "default_place", lambda: home)
    entry = {"prompt": prompt, "segments": [], "slots": [{"id": "s1", "n": 1, "words": words, "state": "ready", "line": 1}],
             "readings": {"slots": [reading]}, "lists": []}
    asyncio.run(seeding.narrow_seeds(entry, None, object()))
    return entry["seeds"]["s1"]


# --------------------------------------------------------------------------- loading

def test_the_pack_loads_with_no_problems_and_adds_what_it_declares(pack):
    assert pack.problems == ()
    assert [k.id for k in pack.ordered_kinds()] == ["person", "animal", "camera", "light", "creature"]
    assert [o.answer for o in pack.kind("person").question("being").options] == ["human", "elf", "other"]   # "other" stays last
    assert pack.heritage_lists() == ("person.ethnicity", "vael.clan")
    assert pack.table_for("vael.clan").id == "realms" and pack.table_for("person.ethnicity").id == "countries"
    assert pack.get("vael.clan").look("Ashveil").startswith("ash-pale skin")
    assert pack.context_named("Saltfang")[1].code == "saltfang" and pack.context_named("Japan")[1].code == "JP"


def test_without_the_pack_nothing_of_it_is_there(with_roots):
    v = with_roots()
    assert "creature" not in v.kinds and "realms" not in v.tables and v.get("vael.clan") is None
    assert [o.answer for o in v.kind("person").question("being").options] == ["human", "other"]
    text = reader.system_text()
    assert "Vael" not in text and '- "creature":' not in text and '"elf" (' not in text


def test_the_reader_is_told_of_the_elf_the_realms_and_the_creature(pack):
    text = reader.system_text()
    assert '"elf" (an elf of the Vael\'s world' in text and 'or "other" (any other sort of being' in text
    assert '- "creature": a beast of the Vael\'s world' in text and "For a creature:" in text
    assert '"a glade in Thornmere": "Thornmere"' in text and "Never a city" in text   # countries first, then realms
    assert '"creature": {...}' in text and text.index('"light": {...}') < text.index('"creature": {...}')
    system = V.system_text()
    assert "A creature of the Vael's world" in system and "- hide: the creature's hide" in system


# --------------------------------------------------------------------------- an elf

def test_an_elf_is_read_as_one_and_a_realm_counts_as_a_place(pack):
    seg = _seg("an <elf> in Thornmere")
    got = reader.check_slot(_person(being="elf", place="Thornmere"), seg, "an ", [])
    assert got["person"]["being"] == "elf" and got["person"]["place"] == "Thornmere"
    with pytest.raises(reader._Bad):
        reader.check_slot(_person(being="elf", place="the north"), seg, "an ", [])   # not a name of any table: asked again


def test_an_elf_in_a_forest_draws_a_clan_per_variant(pack, monkeypatch):
    reading = _person(being="elf")
    p = seeding.plan(reading, "elf")
    assert ("descent", "vael.clan") in [(b["role"], b["list"]) for b in p["banks"]]
    assert "vael.dress" in [b["list"] for b in p["banks"] if b["role"] == "idea"]
    same = seeding.plan(_person(being="elf", outfit="vael.dress"), "elf")   # the reader chose it too: one bank
    assert [b["list"] for b in same["banks"]].count("vael.dress") == 1
    rec = _record(monkeypatch, reading, "elf", "an <elf> in a forest", home="US")
    assert "place" not in rec   # the user's default country weights human descent, not clans
    seeds = seeding.seeds_of(rec)
    drawn = V.draw_seeds(random.Random(1), seeds, 40, "elf")
    clans = Counter(s.descent for s in drawn.specs)
    assert set(clans) <= {v.text for v in pack.get("vael.clan").values} and len(clans) >= 4
    line = drawn.specs[0].line()
    assert f'"{drawn.specs[0].descent}" (' in line   # the clan's look is on the seed line
    slot = V.Slot("elf", "an <elf> in a forest", (3, 8), "person")
    user = V.messages(slot, drawn, seeds)[1]["content"]
    assert "The quoted heritage is their clan" in user


def test_a_realm_weights_the_clans(pack, monkeypatch):
    reading = _person(being="elf", place="Thornmere")
    rec = _record(monkeypatch, reading, "elf", "an <elf> in Thornmere", home="US")
    assert rec["place"] == {"code": "thornmere", "from": "prompt", "table": "realms"}
    from prompt_programs.places import mark
    assert mark(rec["place"]) == "realms:thornmere@prompt"
    seeds = seeding.seeds_of(rec)
    got = Counter(s.descent for s in V.draw_seeds(random.Random(2), seeds, 200, "elf").specs)
    assert got["Corriveth"] / 200 > 0.55 and got["Corriveth"] > 3 * got["Ashveil"]
    forest = seeding.seeds_of(_record(monkeypatch, _person(being="elf"), "elf", "an <elf> in a forest"))
    plain = Counter(s.descent for s in V.draw_seeds(random.Random(2), forest, 200, "elf").specs)
    assert plain["Corriveth"] < got["Corriveth"] / 2


def test_a_human_beside_the_elf_still_draws_a_human_heritage(pack, monkeypatch):
    human = {"n": 1, "kind": "person", "label": "Farmer", "lead": "a", "category": "",
             "person": {"noun": "farmer", "presentation": "", "stated": {}, "vary": ["age", "descent", "build"],
                        "outfit": "person.outfit.casual", "place": "Thornmere"}}
    rec = _record(monkeypatch, human, "farmer", "an elf and a <farmer> in Thornmere", home="US")
    assert next(b["list"] for b in rec["banks"] if b["role"] == "descent") == "person.ethnicity"
    assert rec["place"] == {"code": "US", "from": "default"}   # a realm is no country: the default place stands
    drawn = V.draw_seeds(random.Random(3), seeding.seeds_of(rec), 40, "farmer")
    assert {s.descent for s in drawn.specs} <= {v.text for v in pack.get("person.ethnicity").values}


def test_an_undeclared_being_still_draws_none(pack):
    p = seeding.plan(_person(noun="robot", being="other"), "robot")
    assert "descent" not in [b["role"] for b in p["banks"]]


async def test_the_reader_reply_for_an_elf_goes_through_as_read(pack):
    class Fake:
        def __init__(self, reply):
            self.reply = reply

        async def __call__(self, messages, project_id, max_tokens):
            return self.reply
    reply = {"slots": [{**_person(being="elf", place="Vellumdeep"), "label": "Elf"}]}
    got = await reader.read(parse("an <elf> in Vellumdeep"), ask=Fake(json.dumps(reply)), project_id=None, model="m")
    s = got["slots"][0]
    assert s["kind"] == "person" and s["person"]["being"] == "elf" and s["person"]["place"] == "Vellumdeep"
    assert not s.get("degraded")


# --------------------------------------------------------------------------- the new kind

def _creature(**kw):
    return {"n": 1, "kind": "creature", "label": "Mount", "lead": "a", "category": "mount",
            "creature": {"noun": "mount", **kw}}


def test_a_creature_is_read_by_its_questions(pack):
    seg = _seg("a knight on a <mount> at dawn")
    got = reader.check_slot(_creature(size="great"), seg, "a knight on a ", [])
    assert got["kind"] == "creature" and got["creature"] == {"noun": "mount", "size": "great"}
    odd = reader.check_slot(_creature(size="huge"), seg, "a knight on a ", [])
    assert odd["creature"]["size"] == "any"   # an answer the kind doesn't allow is its default
    with pytest.raises(reader._Bad, match="creature's noun"):
        reader.check_slot({**_creature(size="great"), "creature": {"noun": "horse", "size": "great"}}, seg, "a knight on a ", [])


def test_a_creature_draws_by_its_rules(pack, monkeypatch):
    great = seeding.plan(_creature(size="great"), "mount")
    assert [(b["role"], b["list"]) for b in great["banks"]] == [
        ("core", "vael.beast.great"), ("each", "vael.hide"), ("idea", "vael.temper")]
    anysize = seeding.plan(_creature(size="any"), "mount")
    assert [b["list"] for b in anysize["banks"] if b["role"] == "idea"] == ["vael.beast.small", "vael.beast.great", "vael.temper"]
    rec = _record(monkeypatch, _creature(size="great"), "mount", "a knight on a <mount> at dawn")
    seeds = seeding.seeds_of(rec)
    assert seeds.core.list_id == "vael.beast.great" and seeds.each[0][0] == "hide"
    slot = V.Slot("mount", "a knight on a <mount> at dawn", (14, 21), "creature", "mount")
    assert slot.n == 12   # the kind's first write
    drawn = V.draw_seeds(random.Random(4), seeds, slot.n, "mount")
    s = drawn.specs[0]
    assert s.core and 'hide: "' in s.line() and s.seeds()["hide"]
    user = V.messages(slot, drawn, seeds)[1]["content"]
    assert "This part is a creature of the Vael's world" in user
    hide = dict((label, value) for label, value, _ in s.each)["hide"]
    assert V.check(f"{s.core} with {hide}", "mount", slot.keep(), s) == ""
    assert V.check(f"{s.core} with a plain coat", "mount", slot.keep(), s) == "hide missing"


def test_improve_is_told_of_the_creature(pack):
    from routes.prompt_enhancement import _protected_text_guidance
    assert "a creature of the Vael's world keeps it" in _protected_text_guidance("a ⟦x⟧", marked=True)


# --------------------------------------------------------------------------- a bad pack

def _copy(tmp_path: Path) -> Path:
    root = tmp_path / "pack"
    shutil.copytree(PACK, root)
    return root


def _edit(path: Path, **change):
    d = json.loads(path.read_text())
    d.update(change)
    path.write_text(json.dumps(d))


@pytest.mark.parametrize("breaks,why", [
    (lambda r: (r / "kinds" / "creature.json").write_text("{not json"), "not valid JSON"),
    (lambda r: _edit(r / "kinds" / "creature.json", draws=[{"role": "summon", "list": "vael.hide"}]), "role must be one of"),
    (lambda r: _edit(r / "kinds" / "creature.json", draws=[{"role": "core", "list": "vael.nothing"}]), "isn't loaded"),
    (lambda r: _edit(r / "contexts" / "realms.json", weights="vael.nothing"), "isn't a list"),
    (lambda r: _edit(r / "contexts" / "realms.json", entries={"x": {"name": "Japan", "shares": {}}}), "stands for both"),
    (lambda r: _edit(r / "contexts" / "realms.json", entries={"x": {"name": "X", "shares": {"Korean": 0.5}}}), "not a vael.clan value"),
    (lambda r: _edit(r / "kinds" / "person.json", extend=False), "defined twice"),
])
def test_a_bad_pack_file_is_skipped_with_its_reason(tmp_path, with_roots, breaks, why):
    root = _copy(tmp_path)
    breaks(root)
    v = with_roots(root)   # never raises
    assert any(why in p for p in v.problems), v.problems
    assert v.kind("person") is not None and v.get("person.ethnicity") is not None   # the built-in vocabulary stands
    reader.system_text()   # and the reader's prompt still composes


def test_what_would_replace_something_is_skipped_and_the_rest_applies(tmp_path, with_roots):
    root = _copy(tmp_path)
    ext = json.loads((root / "kinds" / "person.json").read_text())
    ext["reader"]["questions"][0]["options"].append({"answer": "human", "text": "a person"})   # already allowed
    ext["first_write"] = 99   # the kind's own
    (root / "kinds" / "person.json").write_text(json.dumps(ext))
    (root / "person").mkdir()
    (root / "person" / "gender.json").write_text(json.dumps({"extend": True, "label": "Sex", "values": [
        {"text": "woman", "tier": "typical"}]}))
    v = with_roots(root)
    assert any("already allows 'human'" in p for p in v.problems)
    assert any("first_write is the kind's own" in p for p in v.problems)
    assert any("has 'woman' already" in p for p in v.problems) and any("label of person.gender" in p for p in v.problems)
    assert v.kind("person").first_write == 40 and v.get("person.gender").label == "Gender"
    assert [o.answer for o in v.kind("person").question("being").options] == ["human", "elf", "other"]


def test_a_pack_may_add_values_to_a_built_in_list(tmp_path, with_roots):
    root = _copy(tmp_path)
    (root / "lighting").mkdir()
    (root / "lighting" / "scene.json").write_text(json.dumps({"extend": True, "values": [
        {"text": "the cold blue glow of rune-stones", "tier": "plausible"}]}))
    v = with_roots(root)
    assert v.problems == () and v.get("lighting.scene").value("the cold blue glow of rune-stones") is not None
