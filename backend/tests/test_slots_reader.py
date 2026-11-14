"""The slot reader with a fake model: the numbered prompt, the reply's checks, one retry, each
part read on its own and cached; slots.prepare (instant, reading and seed narrowing in the
background), POST /prompt-programs/prepare on top of it, and the words-only narrowing
(narrow.subset) the seeds are asked with."""

import copy
import json
from typing import Any, Dict, List

import pytest

from prompt_programs import program as prep
from prompt_programs import reader, slots
from prompt_programs import variant_pools as P
from prompt_programs.narrow import NarrowCache
from prompt_programs.seeding import plan
from prompt_programs.slots import parse

from test_prompt_program_variants import FakeWriter

DORM_PROMPT = "dorm room with a <young man>, lit by <light>"
DORM_READING = {"slots": [
    {"n": 1, "kind": "person", "label": "Young man", "lead": "",
     "person": {"noun": "man", "presentation": "masculine", "stated": {"age": "young"},
                "vary": ["age", "descent", "build", "hair", "hair_color"], "outfit": "person.outfit.casual"}},
    {"n": 2, "kind": "light", "label": "Light", "lead": ", lit by",
     "light": {"examples": ["warm desk-lamp light", "gray morning light through blinds", "blue screen glow"]}},
]}
DORM_LIGHT = DORM_READING["slots"][1]

PORCH_PROMPT = ("# she is his granddaughter, visiting\n"
                "an <elderly African man> reading on a porch with his <pet>, {summer|autumn} evening")
PORCH_READING = {"slots": [
    {"n": 1, "kind": "person", "label": "Elderly African man", "lead": "",
     "person": {"noun": "man", "presentation": "masculine", "stated": {"age": "elderly", "descent": "African"},
                "vary": ["age", "descent", "build", "hair", "hair_color", "facial_hair"], "outfit": "person.outfit.casual"}},
    {"n": 2, "kind": "free", "label": "Pet", "lead": " with his",
     "free": {"about": "his pet, with him on the porch", "kinds": ["ginger tabby cat", "old basset hound", "gray parrot"],
              "instead": ["stack of library books", "mug of coffee", "transistor radio"]}},
], "lists": [{"n": 1, "label": "Season"}]}

ELDERLY = ["71-year-old", "74-year-old", "79-year-old"]
AFRICAN = ["Kenyan", "Ghanaian"]


def _asked(messages) -> str:
    """The last user turn, without the line a narrowing's retry starts with (narrow.RETRY_LEAD)."""
    from prompt_programs.narrow import RETRY_LEAD
    return messages[-1]["content"].removeprefix(RETRY_LEAD)


class FakeModel:
    """Answers the reader with queued replies (a reply may be a function of the messages; the
    last one answers every later call) and narrowing with fixed subsets; records what the
    reader was asked. A reply holding every part answers each part's own call."""

    def __init__(self, *replies: Any):
        self.replies: List[Any] = list(replies)
        self.asked: List[List[Dict[str, Any]]] = []

    async def __call__(self, messages, project_id, max_tokens):
        user = _asked(messages)
        if messages[0]["content"].startswith("You read the parts of an image prompt"):
            self.asked.append(messages)
            got = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
            return got(messages) if callable(got) else got
        if user.startswith('The list "Age"'):
            return json.dumps(ELDERLY)
        if user.startswith('The list "Descent"'):
            return json.dumps(AFRICAN)
        return "[]"


def _reply(reading: Dict[str, Any], **changes: Any) -> str:
    out = copy.deepcopy(reading)
    for n, change in changes.items():
        out["slots"][int(n[1:]) - 1].update(change)
    return json.dumps(out)


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """A profile in tmp_path with fresh slot, narrowing and pool state; its pools are written
    by a FakeWriter (variant_pools.ASK), so no write reaches a model."""
    import app_dirs
    import prompt_programs.narrow as nw
    monkeypatch.setattr(app_dirs, "get_profile_dir", lambda pid="default": tmp_path / str(pid))

    async def fingerprint(project_id):
        return "fake-model"
    monkeypatch.setattr(prep, "model_fingerprint", fingerprint)
    for name in ("_reads", "_settling", "_failed"):
        monkeypatch.setattr(slots, name, {})
    monkeypatch.setattr(slots, "_again", set())
    monkeypatch.setattr(slots, "_changed", set())
    monkeypatch.setattr(nw, "_asking", {})
    monkeypatch.setattr(P, "_stores", {})
    monkeypatch.setattr(P, "_writers", {})
    monkeypatch.setattr(P, "ASK", FakeWriter())
    monkeypatch.setattr("prompt_pipeline._profile_wildcards_and_segments", lambda profile_id: ([], []))
    return "p"


async def ready(prompt: str, profile: str, **kw: Any) -> Dict[str, Any]:
    """Prepare, let the background reading, narrowing and pool writes land, and look again."""
    await slots.prepare(prompt, profile_id=profile, **kw)
    await slots.idle()
    await P.writer_for(profile).drain()
    await slots.idle()
    return await slots.prepare(prompt, profile_id=profile, start=False)


def realize_all(entry, seed, **kw):
    return prep.realize(entry, seed=seed, profile_id="p", **kw)


def bank(entry: Dict[str, Any], sid: str, role: str) -> Dict[str, Any]:
    """A slot's first seed bank with this role (descent, gender, age, core, idea)."""
    return next(b for b in entry["seeds"][sid]["banks"] if b["role"] == role)


def _use(monkeypatch, model: FakeModel) -> FakeModel:
    monkeypatch.setattr(prep, "ask_model", model)
    return model


# --------------------------------------------------------------------------- the reader itself

def test_the_prompt_is_numbered_in_place():
    shown = reader.numbered(parse(PORCH_PROMPT))
    assert shown == ("# she is his granddaughter, visiting\n"
                     "an ⟨1: elderly African man⟩ reading on a porch with his ⟨2: pet⟩, {L1: summer|autumn} evening")


def test_the_prompt_carries_the_person_guidance_and_the_catalogs():
    text = reader.system_text()
    for words in ("Lines starting with # are notes", "Leave out expression", "accessories", "need not include every",
                  "unless clothes has words", "- hair_color:", "- person.outfit.casual:", "- person.hairstyle:"):
        assert words in text
    assert "EXACT" in text and "{catalog}" not in text and "{details}" not in text
    # Each kind's own fields are shown in their object: a list's id goes inside "list": {...}.
    assert '"list": {"list": "<the list\'s id>", "about": "...", "presentation": ""}' in text
    assert "are never a person" in text
    # A worked tag prompt shows parts about the girl read as lists, their leads only the comma.
    assert '"1girl, ⟨1: hairstyle⟩, ⟨2: outfit⟩, beach"' in text and '"about": "the girl\'s hairstyle"' in text


async def test_a_list_id_outside_its_object_is_retried_with_the_shape():
    flat = {"slots": [{"n": 1, "kind": "list", "label": "Hairstyle", "lead": "", "list": "person.hairstyle", "stated": ""}],
            "lists": []}
    nested = {"slots": [{"n": 1, "kind": "list", "label": "Hairstyle", "lead": "",
                         "list": {"list": "person.hairstyle", "stated": ""}}], "lists": []}
    model = FakeModel(json.dumps(flat), json.dumps(nested))
    got = await reader.read(parse("1girl, <hairstyle>, rooftop"), ask=model, project_id=None, model="m")
    assert len(model.asked) == 2 and '"list": {...}' in model.asked[1][-1]["content"]
    assert got["slots"][0]["list"] == {"list": "person.hairstyle", "about": "hairstyle"}


async def test_bad_json_gets_one_retry_that_says_why():
    model = FakeModel("Sure! Here is the reading: {", _reply(PORCH_READING))
    got = await reader.read_part(parse(PORCH_PROMPT), "slot", 2, ask=model, project_id=None, model="m")
    assert len(model.asked) == 2
    retry = model.asked[1]
    assert retry[-2] == {"role": "assistant", "content": "Sure! Here is the reading: {"}
    assert "isn't valid JSON" in retry[-1]["content"]
    assert got["kind"] == "free"


async def test_each_part_is_asked_on_its_own_with_the_whole_prompt():
    model = FakeModel(_reply(PORCH_READING))
    got = await reader.read(parse(PORCH_PROMPT), ask=model, project_id=None, model="m")
    assert len(model.asked) == 3
    asked = sorted(m[-1]["content"].rsplit("\n", 1)[-1] for m in model.asked)
    assert asked == ['The other parts are already read. Answer only for: {L1}.',
                     'The other parts are already read. Answer only for: ⟨1⟩ "elderly African man".',
                     'The other parts are already read. Answer only for: ⟨2⟩ "pet".']
    assert all("⟨1: elderly African man⟩" in m[-1]["content"] for m in model.asked)
    assert [s["kind"] for s in got["slots"]] == ["person", "free"] and got["lists"] == [{"n": 1, "label": "Season"}]


async def test_a_bad_slot_is_read_as_written_and_never_cached(tmp_path):
    cache = NarrowCache(tmp_path)
    model = FakeModel(_reply(PORCH_READING, n2={"kind": "thing"}))
    pet = await reader.read_part(parse(PORCH_PROMPT), "slot", 2, ask=model, project_id=None, model="m", cache=cache)
    assert len(model.asked) == 2 and "kind must be one of" in model.asked[1][-1]["content"]
    assert pet["degraded"] is True and pet["kind"] == "free" and pet["label"] == "pet" and "kind must be" in pet["reason"]
    assert reader.cached(parse(PORCH_PROMPT), "m", cache) == ({}, {})
    good = await reader.read_part(parse(PORCH_PROMPT), "slot", 2, ask=FakeModel(_reply(PORCH_READING)), project_id=None,
                                  model="m", cache=cache)
    assert "degraded" not in good and reader.cached(parse(PORCH_PROMPT), "m", cache)[0][2]["kind"] == "free"


async def test_a_reply_that_is_never_json_reads_the_part_as_written():
    got = await reader.read(parse(PORCH_PROMPT), ask=FakeModel("no"), project_id=None, model="m")
    assert [s["degraded"] for s in got["slots"]] == [True, True] and got["lists"] == [{"n": 1, "label": ""}]


async def test_a_person_with_nothing_to_draw_twice_is_read_as_written():
    empty = {"slots": [{"n": 1, "kind": "person", "label": "Hairstyle", "lead": "",
                        "person": {"noun": "hairstyle", "presentation": "", "stated": {}, "vary": [], "outfit": ""}}]}
    got = await reader.read(parse("1girl, <hairstyle>, rooftop"), ask=FakeModel(json.dumps(empty)),
                            project_id=None, model="m")
    assert got["slots"][0]["degraded"] is True


async def test_a_missing_part_or_a_list_that_doesnt_exist_is_retried():
    short = {"slots": PORCH_READING["slots"][:1], "lists": PORCH_READING["lists"]}
    model = FakeModel(json.dumps(short), _reply(PORCH_READING))
    await reader.read_part(parse(PORCH_PROMPT), "slot", 2, ask=model, project_id=None, model="m")
    assert "no answer for ⟨2⟩" in model.asked[1][-1]["content"]
    bound = {"n": 1, "kind": "list", "label": "Thing", "lead": "", "list": {"list": "no.such.list", "stated": ""}}
    model = FakeModel(json.dumps({"slots": [bound]}), json.dumps({"slots": [{**bound, "list": {"list": "animal.dog_breed",
                                                                                                "stated": ""}}]}))
    got = await reader.read(parse("a <thing> on a rug"), ask=model, project_id=None, model="m")
    assert "is not one of the lists" in model.asked[1][-1]["content"]
    assert got["slots"][0]["list"]["list"] == "animal.dog_breed"


async def test_a_person_with_nothing_to_draw_is_retried():
    """Words about part of a person read as a person with no details would emit only a noun."""
    empty = {"slots": [{"n": 1, "kind": "person", "label": "Hairstyle", "lead": "",
                        "person": {"noun": "girl", "presentation": "feminine", "stated": {}, "vary": [], "outfit": ""}}]}
    listed = {"slots": [{"n": 1, "kind": "list", "label": "Hairstyle", "lead": "",
                         "list": {"list": "person.hairstyle", "stated": ""}}]}
    model = FakeModel(json.dumps(empty), json.dumps(listed))
    got = await reader.read(parse("1girl, <girl hairstyle>, rooftop"), ask=model, project_id=None, model="m")
    assert len(model.asked) == 2 and "a person needs details to vary" in model.asked[1][-1]["content"]
    assert got["slots"][0]["kind"] == "list"


async def test_a_persons_noun_is_one_of_their_own_words():
    other = {"n": 1, "kind": "person", "label": "Expression", "lead": ",",
             "person": {"noun": "boy", "presentation": "masculine", "stated": {}, "vary": ["hair"], "outfit": ""}}
    listed = {"n": 1, "kind": "list", "label": "Expression", "lead": ",",
              "list": {"list": "person.expression", "about": "the boy's expression"}}
    model = FakeModel(json.dumps({"slots": [other]}), json.dumps({"slots": [listed]}))
    got = await reader.read(parse("1boy, <expression>, city street"), ask=model, project_id=None, model="m")
    assert len(model.asked) == 2
    assert '"boy" is not among the words "expression"' in model.asked[1][-1]["content"]
    assert got["slots"][0]["list"] == {"list": "person.expression", "about": "the boy's expression"}
    noted = {**other, "person": {**other["person"], "noun": "nurse"}}
    got = await reader.read(parse("# she is a nurse\n<tired woman>, hospital corridor"),
                            ask=FakeModel(json.dumps({"slots": [noted]})), project_id=None, model="m")
    assert got["slots"][0]["person"]["noun"] == "nurse"


async def test_a_stated_detail_is_always_drawn():
    model = FakeModel(_reply(DORM_READING, n1={"person": {**DORM_READING["slots"][0]["person"], "vary": ["hair"]}}))
    got = await reader.read(parse(DORM_PROMPT), ask=model, project_id=None, model="m")
    assert got["slots"][0]["person"]["vary"] == ["hair", "age"]


async def test_a_lead_that_isnt_in_the_text_is_cleared():
    got = await reader.read(parse(DORM_PROMPT), ask=FakeModel(_reply(DORM_READING, n2={"lead": ", lighted with"})),
                            project_id=None, model="m")
    assert got["slots"][1]["lead"] == ""
    got = await reader.read(parse(DORM_PROMPT), ask=FakeModel(_reply(DORM_READING)), project_id=None, model="m")
    assert got["slots"][1]["lead"] == ", lit by"


async def test_words_that_arent_the_users_are_dropped_and_unknown_details_too():
    person = copy.deepcopy(PORCH_READING["slots"][0])
    person["person"]["stated"] = {"age": "elderly", "descent": "Kenyan", "hair": "granddaughter", "mood": "calm"}
    person["person"]["vary"] = ["age", "build", "expression", "hair"]
    model = FakeModel(json.dumps({"slots": [person, PORCH_READING["slots"][1]], "lists": PORCH_READING["lists"]}))
    got = await reader.read(parse(PORCH_PROMPT), ask=model, project_id=None, model="m")
    p = got["slots"][0]["person"]
    assert p["stated"] == {"age": "elderly", "hair": "granddaughter"}
    assert p["vary"] == ["age", "build", "hair"]


async def test_unknown_numbers_are_dropped():
    reading = copy.deepcopy(PORCH_READING)
    reading["slots"].append({**reading["slots"][1], "n": 7})
    reading["lists"].append({"n": 4, "label": "Nothing"})
    got = await reader.read(parse(PORCH_PROMPT), ask=FakeModel(json.dumps(reading)), project_id=None, model="m")
    assert [s["n"] for s in got["slots"]] == [1, 2] and [x["n"] for x in got["lists"]] == [1]


async def test_each_part_is_cached_by_its_own_words_and_line(tmp_path):
    cache = NarrowCache(tmp_path)
    model = FakeModel(_reply(DORM_READING))
    first = await reader.read(parse(DORM_PROMPT), ask=model, project_id=None, model="m", cache=cache)
    again = await reader.read(parse(DORM_PROMPT), ask=model, project_id=None, model="m", cache=cache)
    assert first == again and len(model.asked) == 2
    other = FakeModel(_reply(DORM_READING))
    await reader.read(parse(DORM_PROMPT), ask=other, project_id=None, model="other", cache=cache)
    assert len(other.asked) == 2   # another reader model reads again


async def test_an_edit_on_another_line_asks_only_for_the_slot_whose_line_changed(tmp_path):
    cache = NarrowCache(tmp_path)
    before = "a <young man> on a bench\nnear a <dog> in the park"
    reading = {"slots": [DORM_READING["slots"][0],
                         {"n": 2, "kind": "free", "label": "Dog", "lead": "",
                          "free": {"about": "a dog in the park", "kinds": ["beagle", "whippet", "corgi"],
                                   "instead": ["pigeon", "kite", "bicycle"]}}]}
    await reader.read(parse(before), ask=FakeModel(json.dumps(reading)), project_id=None, model="m", cache=cache)
    model = FakeModel(json.dumps(reading))
    got = await reader.read(parse("a <young man> on a bench\nnear a <dog> by the lake"), ask=model, project_id=None,
                            model="m", cache=cache)
    assert len(model.asked) == 1 and 'Answer only for: ⟨2⟩ "dog".' in model.asked[0][-1]["content"]
    assert [s["kind"] for s in got["slots"]] == ["person", "free"]
    model = FakeModel(json.dumps(reading))
    await reader.read(parse("# at dawn\n" + before), ask=model, project_id=None, model="m", cache=cache)
    assert len(model.asked) == 2   # a new note is context for every slot: all are read again


# --------------------------------------------------------------------------- the category word and a free part's lists

SILLY_PROMPT = "a <young woman> making a <silly expression>, phone selfie"
SILLY_AS_LIST = {"n": 2, "kind": "list", "label": "Silly expression", "lead": " making a",
                 "list": {"list": "person.expression", "about": "the young woman's expression"}}


async def _category(prompt: str, n: int, reading: Dict[str, Any], category: Any) -> str:
    model = FakeModel(json.dumps({"slots": [{**reading, "category": category}]}))
    got = await reader.read_part(parse(prompt), "slot", n, ask=model, project_id=None, model="m")
    assert len(model.asked) == 1 and not got.get("degraded")   # never a reason to retry
    return got["category"]


async def test_a_category_that_is_a_run_of_the_parts_own_words_is_kept():
    assert await _category(SILLY_PROMPT, 2, SILLY_AS_LIST, "expression") == "expression"
    assert await _category(SILLY_PROMPT, 2, SILLY_AS_LIST, " Silly expression ") == "Silly expression"
    camera = {"n": 1, "kind": "list", "label": "Selfie camera angle", "lead": "",
              "list": {"list": "camera.angle", "about": "the camera angle"}}
    assert await _category("<selfie camera angle>, a rooftop", 1, camera, "camera angle") == "camera angle"


@pytest.mark.parametrize("category", ["face", "silly face", "expression silly", "", None, 7, ["expression"]])
async def test_a_category_that_isnt_a_run_of_the_parts_words_is_none(category):
    assert await _category(SILLY_PROMPT, 2, SILLY_AS_LIST, category) == ""


async def test_a_person_never_has_a_category():
    man = PORCH_READING["slots"][0]
    assert await _category(PORCH_PROMPT, 1, man, "man") == ""
    assert await _category(PORCH_PROMPT, 1, man, "elderly African man") == ""


async def test_a_free_parts_lists_are_real_lists_at_most_three():
    pet = copy.deepcopy(PORCH_READING["slots"][1])
    pet["free"]["lists"] = ["no.such.list", "animal.species", "animal.species", "animal.dog_breed",
                            "animal.cat_breed", "animal.life_stage"]
    got = await reader.read_part(parse(PORCH_PROMPT), "slot", 2, ask=FakeModel(json.dumps({"slots": [pet]})),
                                 project_id=None, model="m")
    assert got["free"]["lists"] == ["animal.species", "animal.dog_breed", "animal.cat_breed"]
    # none named, or none that exist: no lists, and the reading stands
    for lists in (None, [], ["no.such.list"]):
        pet["free"]["lists"] = lists
        got = await reader.read_part(parse(PORCH_PROMPT), "slot", 2, ask=FakeModel(json.dumps({"slots": [pet]})),
                                     project_id=None, model="m")
        assert got["free"]["lists"] == [] and not got.get("degraded")
    pet["free"]["lists"] = "animal.species"   # not a list of ids: retried with the reason
    model = FakeModel(json.dumps({"slots": [pet]}), _reply(PORCH_READING))
    await reader.read_part(parse(PORCH_PROMPT), "slot", 2, ask=model, project_id=None, model="m")
    assert len(model.asked) == 2 and "lists must be a list of strings" in model.asked[1][-1]["content"]


def test_a_free_parts_lists_seed_it_with_ideas():
    pet = {**PORCH_READING["slots"][1], "category": "pet",
           "free": {**PORCH_READING["slots"][1]["free"], "lists": ["animal.species", "animal.dog_breed"]}}
    assert [(b["role"], b["list"]) for b in plan(pet, "pet")["banks"]] == [("idea", "animal.species"),
                                                                           ("idea", "animal.dog_breed")]
    e = slots.compose(parse(PORCH_PROMPT), {2: pet})
    assert e["slots"][1]["category"] == "pet" and e["choices"][1] == {"id": "pet", "kind": "variants", "label": "Pet",
                                                                      "slot": "pet"}


# --------------------------------------------------------------------------- prepare, at once

class Hang(FakeModel):
    """A model that never answers until let go: whatever waits on it would hang."""

    def __init__(self, *replies: Any):
        import asyncio
        super().__init__(*replies)
        self.go = asyncio.Event()
        self.calls = 0

    async def __call__(self, messages, project_id, max_tokens):
        self.calls += 1
        await self.go.wait()
        return await super().__call__(messages, project_id, max_tokens)


async def test_prepare_answers_from_the_parse_before_any_model_call(profile, monkeypatch):
    import asyncio
    model = _use(monkeypatch, Hang(_reply(PORCH_READING)))
    entry = await asyncio.wait_for(slots.prepare(PORCH_PROMPT, profile_id=profile), 2.0)
    assert [(s["id"], s["state"], s["label"]) for s in entry["slots"]] == [
        ("elderly_african_man", "reading", "elderly African man"), ("pet", "reading", "pet")]
    assert entry["lists"][0]["state"] == "reading" and entry["reading"] and entry["working"]
    assert entry["key"] and model.asked == []   # nothing answered, nothing waited for
    await asyncio.sleep(0)
    assert model.calls == 3   # one call per part, all at once
    model.go.set()
    await slots.idle()
    done = await slots.prepare(PORCH_PROMPT, profile_id=profile, start=False)
    assert [s["state"] for s in done["slots"]] == ["ready", "ready"] and not done["reading"] and not done["working"]


async def test_each_slot_lands_on_its_own(profile, monkeypatch):
    import asyncio

    class PetLate(FakeModel):
        def __init__(self, *r):
            super().__init__(*r)
            self.go = asyncio.Event()

        async def __call__(self, messages, project_id, max_tokens):
            if '"pet".' in messages[-1]["content"]:
                await self.go.wait()
            return await super().__call__(messages, project_id, max_tokens)
    model = _use(monkeypatch, PetLate(_reply(PORCH_READING)))
    await slots.prepare(PORCH_PROMPT, profile_id=profile)
    for _ in range(50):
        await asyncio.sleep(0.01)
        now = await slots.prepare(PORCH_PROMPT, profile_id=profile, start=False)
        if now["slots"][0]["state"] == "ready":
            break
    assert [s["state"] for s in now["slots"]] == ["ready", "reading"] and now["working"]
    assert now["slots"][0]["pool"] and "pool" not in now["slots"][1]
    assert [c["kind"] for c in now["choices"]] == ["variants", "variants", "pick"]
    model.go.set()
    await slots.idle()


async def test_prepare_reads_narrows_seeds_and_stores(profile, monkeypatch):
    model = _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    entry = await ready(PORCH_PROMPT, profile)
    man = "elderly_african_man"
    assert bank(entry, man, "age")["narrowed"] == ELDERLY and sorted(bank(entry, man, "descent")["narrowed"]) == sorted(AFRICAN)
    assert bank(entry, man, "descent")["phrase"] == "African" and entry["seeds"][man]["stated_descent"]
    # the outfit list seeds ideas, kept to how the man presents
    outfit = next(b for b in entry["seeds"][man]["banks"] if b["list"] == "person.outfit.casual")
    assert outfit["role"] == "idea" and outfit["where"] == {"presentation": "masculine"}
    assert entry["seeds_pending"] == [] and not entry["reading"]
    assert entry["readings"]["slots"][1]["free"] == {"about": "his pet, with him on the porch", "lists": []}
    assert all(P.store_for(profile).has(s["pool"]) for s in entry["slots"])
    stored = prep.store_for(profile).get(entry["key"])
    assert stored["seeds"] == entry["seeds"] and [s["pool"] for s in stored["slots"]] == [s["pool"] for s in entry["slots"]]
    again = await slots.prepare(PORCH_PROMPT, profile_id=profile)
    await slots.idle()
    assert again["key"] == entry["key"] and len(model.asked) == 3
    assert (await slots.prepare("a plain prompt", profile_id=profile)) == {"key": None, "slots": [], "choices": []}


async def test_a_stated_age_under_18_gives_the_person_a_pool_of_their_own(profile, monkeypatch):
    from prompt_programs.variant_pools import pool_key
    from prompt_programs.vocab import vocabulary
    young = [v.text for v in vocabulary().get("person.age_band").values if v.minor][:3]
    reading = {"slots": [{"n": 1, "kind": "person", "label": "Boy", "lead": "",
                          "person": {"noun": "boy", "presentation": "masculine", "stated": {"age": "10-year-old"},
                                     "vary": ["hair", "hair_color"], "outfit": ""}}]}

    class Young(FakeModel):
        async def __call__(self, messages, project_id, max_tokens):
            if _asked(messages).startswith('The list "Age"'):
                assert '"10-year-old' in messages[-1]["content"]
                return json.dumps(young)
            if messages[0]["content"].startswith("You read an image prompt and say whether"):
                assert '"10-year-old boy"' in messages[-1]["content"]
                return '{"under_18": "yes"}'   # the model's explicit yes: only then do ages under 18 count
            return await super().__call__(messages, project_id, max_tokens)
    _use(monkeypatch, Young(json.dumps(reading)))
    first = await slots.prepare("a <10-year-old boy> flying a kite", profile_id=profile)
    assert first["slots"][0]["state"] == "reading"
    entry = await ready("a <10-year-old boy> flying a kite", profile)
    assert entry["readings"]["slots"][0]["person"]["vary"] == ["hair", "hair_color", "age"]
    sid = "slot_10_year_old_boy"
    assert bank(entry, sid, "age")["narrowed"] == young and entry["seeds"][sid]["minor"] == young
    s = entry["slots"][0]
    assert s["pool"] != pool_key("fake-model", s["words"], s["seen"]["marked"], s["seen"]["notes"])
    assert "This person is under 18" in P.ASK.calls[0]["user"]


async def test_a_slot_whose_seeds_arent_narrowed_yet_waits_and_stands_as_its_words(profile, monkeypatch):
    """Until its narrowing lands, a slot's pool isn't written (an unnarrowed age would fight
    "10-year-old"), and every image has it as typed."""
    import asyncio
    import prompt_programs.narrow as nw
    reading = {"slots": [{"n": 1, "kind": "person", "label": "Boy", "lead": "",
                          "person": {"noun": "boy", "presentation": "masculine", "stated": {"age": "10-year-old"},
                                     "vary": ["age", "hair"], "outfit": ""}}]}

    class NarrowHangs(FakeModel):
        async def __call__(self, messages, project_id, max_tokens):
            if _asked(messages).startswith('The list'):
                await asyncio.Event().wait()
            return await super().__call__(messages, project_id, max_tokens)
    _use(monkeypatch, NarrowHangs(json.dumps(reading)))
    prompt = "a <10-year-old boy> flying a kite"
    await slots.prepare(prompt, profile_id=profile)
    for _ in range(100):
        await asyncio.sleep(0.01)
        entry = await slots.prepare(prompt, profile_id=profile, start=False)
        if entry["slots"][0]["state"] == "ready":
            break
    assert entry["reading"] and entry["seeds_pending"] == ["slot_10_year_old_boy"]
    assert entry["slots"][0]["pool"] and not P.ASK.calls
    assert realize_all(entry, 3).prompt == "A 10-year-old boy flying a kite"
    for t in [*slots._settling.values(), *nw._asking.values()]:
        t.cancel()


def _client(monkeypatch, profile):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import prompt_programs as route
    monkeypatch.setattr(route, "get_current_profile", lambda: profile)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app, raise_server_exceptions=False)


async def test_the_prepare_route_answers_with_slots_and_choices(profile, monkeypatch):
    _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    typed = "  " + PORCH_PROMPT   # spans are in the prompt as typed
    await ready(typed, profile)
    client = _client(monkeypatch, profile)
    out = client.post("/api/prompt-programs/prepare", json={"tool_id": "t", "prompt": typed, "cache_only": True}).json()
    assert set(out) == {"key", "slots", "choices", "reading", "working"} and not out["reading"]
    man, pet = out["slots"]
    assert man["id"] == "elderly_african_man" and man["kind"] == "person" and man["words"] == "elderly African man"
    assert typed[man["span"][0]:man["span"][1]] == "<elderly African man>" and man["line"] == 2
    assert man["stated"] == {"age": "elderly", "descent": "African"} and man["state"] == "ready"
    assert pet == {"id": "pet", "n": 2, "kind": "free", "label": "Pet", "words": "pet", "state": "ready",
                   "span": [typed.index("<pet>"), typed.index("<pet>") + 5], "line": 2}
    assert out["choices"] == [
        {"id": "elderly_african_man", "kind": "variants", "label": "Elderly African man", "slot": "elderly_african_man"},
        {"id": "pet", "kind": "variants", "label": "Pet", "slot": "pet"},
        {"id": "list1", "kind": "pick", "label": "Season", "options": ["summer", "autumn"], "source": "list", "line": 2}]
    assert "program" not in out and "seeds" not in out and "pool" not in str(out)
    nothing = client.post("/api/prompt-programs/prepare", json={"tool_id": "t", "prompt": "a cat on a mat"}).json()
    assert nothing == {"key": None, "slots": [], "choices": []}


async def test_a_lookup_shows_the_slots_and_starts_nothing(profile, monkeypatch):
    model = _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    out = _client(monkeypatch, profile).post("/api/prompt-programs/prepare",
                                             json={"tool_id": "t", "prompt": PORCH_PROMPT, "cache_only": True}).json()
    assert [s["state"] for s in out["slots"]] == ["reading", "reading"] and out["reading"] and not out["working"]
    await slots.idle()
    assert model.asked == []


async def test_a_reading_that_cant_be_used_stands_as_written_and_is_read_again(profile, monkeypatch):
    _use(monkeypatch, FakeModel("no"))
    entry = await ready(DORM_PROMPT, profile)
    assert [s.get("degraded") for s in entry["slots"]] == [True, True] and not entry["reading"]
    assert realize_all(entry, 0).prompt == "Dorm room with a young man, lit by light"
    _use(monkeypatch, FakeModel(_reply(DORM_READING)))
    again = await ready(DORM_PROMPT, profile)   # a prepare that starts work reads it again
    assert not any(s.get("degraded") for s in again["slots"])


async def test_a_reader_that_raises_never_fails_the_prepare(profile, monkeypatch):
    async def down(messages, project_id, max_tokens):
        raise RuntimeError("the endpoint went away")
    monkeypatch.setattr(prep, "ask_model", down)
    entry = await ready(DORM_PROMPT, profile)
    assert all(s["degraded"] for s in entry["slots"]) and realize_all(entry, 0).prompt.startswith("Dorm room with a young man")


class SlowDescent(FakeModel):
    """Narrowing the descent list answers late; `fails` makes it fail instead."""

    def __init__(self, *replies: Any, delay: float = 0.0, fails: bool = False):
        super().__init__(*replies)
        self.delay, self.fails, self.descent_asks = delay, fails, 0

    async def __call__(self, messages, project_id, max_tokens):
        import asyncio
        if _asked(messages).startswith('The list "Descent"'):
            self.descent_asks += 1
            await asyncio.sleep(self.delay)
            if self.fails:
                raise RuntimeError("the endpoint went away")
        return await super().__call__(messages, project_id, max_tokens)


async def test_a_narrowing_that_fails_drops_its_seeds_never_the_slot_and_is_asked_again(profile, monkeypatch):
    model = _use(monkeypatch, SlowDescent(_reply(PORCH_READING), fails=True))
    entry = await ready(PORCH_PROMPT, profile)
    assert model.descent_asks == 2   # one more try, then the pool is written without descent seeds
    man = next(s for s in entry["slots"] if s["id"] == "elderly_african_man")
    variants = P.store_for(profile).variants(man["pool"])
    assert variants and not any("descent" in v["seeds"] for v in variants)
    assert all("elderly african man" in realize_all(entry, seed).prompt.lower() for seed in range(4))
    # never cached: the next prepare that starts work asks again
    assert entry["reading"] and entry["seeds_pending"] == ["elderly_african_man"]
    model = _use(monkeypatch, SlowDescent())
    again = await ready(PORCH_PROMPT, profile)
    assert model.descent_asks == 1 and not again["reading"]
    assert sorted(bank(again, "elderly_african_man", "descent")["narrowed"]) == sorted(AFRICAN)


async def test_the_same_narrowing_asked_twice_at_once_is_asked_once(profile, monkeypatch):
    import asyncio
    model = _use(monkeypatch, SlowDescent(_reply(PORCH_READING), delay=0.2))
    await asyncio.gather(*(slots.prepare(PORCH_PROMPT, profile_id=profile) for _ in range(3)))
    await slots.idle()
    assert model.descent_asks == 1


def test_an_oversized_prompt_is_refused_before_the_reader(profile, monkeypatch):
    model = _use(monkeypatch, FakeModel())
    long = "A woman waiting for a <train>, " * 400
    r = _client(monkeypatch, profile).post("/api/prompt-programs/prepare", json={"tool_id": "t", "prompt": long})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "prompt_too_long" and not model.asked


async def test_a_narrowing_that_keeps_every_item_says_all_and_the_opt_in_items_stay_out():
    from prompt_programs.narrow import reply_tokens, subset
    from prompt_programs.vocab import vocabulary
    ages = vocabulary().get("person.age_band")
    asked = []

    async def all_of_them(messages, project_id, max_tokens):
        asked.append(max_tokens)
        return '["ALL"]'
    got = await subset(ages, "person", None, all_of_them)
    assert got and all(not v.opt_in for v in ages.values if v.text in set(got))
    assert len(got) == len([v for v in ages.eligible() if not v.opt_in])
    # a long list gets room to be copied back whole
    outfits = [v.text for v in vocabulary().get("person.outfit.casual").eligible()]
    assert reply_tokens(outfits) > 16 * len(outfits)


def test_the_message_names_each_part_and_the_example_shows_its_prompt():
    """A person written outside the brackets ("an old farmer with his <pet>") is not a part: the
    message names the parts there are, and the example reply is shown beside its own prompt."""
    text = reader.user_message(parse("an old farmer with his <pet> on a porch"), [("slot", 1)])
    assert text.endswith('Answer for each of its parts: ⟨1⟩ "pet".')
    system = reader.system_text()
    assert 'For the prompt "an ⟨1: elderly African man⟩ reading on a porch with his ⟨2: pet⟩' in system
    assert "never a part, even when they name a\nperson" in system


async def test_a_list_with_declared_groups_is_narrowed_by_group():
    """The descent list's heritage groups are shown, and a group's name in the reply stands for
    every item in it; single items still count by themselves."""
    from prompt_programs.narrow import messages_for, subset
    from prompt_programs.vocab import vocabulary
    leaf = vocabulary().get("person.ethnicity")
    values = [v.text for v in leaf.eligible()]
    system, user = (m["content"] for m in messages_for(leaf, "African", values, "the man's descent"))
    assert "- north_african: Moroccan, Algerian" in user and '{"groups": [...],' in system
    north = [v.text for v in leaf.values if v.group == "north_african"]
    horn = [v.text for v in leaf.values if v.group == "horn_of_africa"]

    async def answer(messages, project_id, max_tokens):
        return json.dumps(["north_african", horn[0], "no such people"])
    assert sorted(await subset(leaf, "African", None, answer)) == sorted(north + horn[:1])


async def test_a_group_named_beside_its_own_items_keeps_only_those_items():
    """{"groups": [g], "items": [an item of g]} names g for that item: just the item is kept."""
    from prompt_programs.narrow import subset
    from prompt_programs.vocab import vocabulary
    leaf = vocabulary().get("person.ethnicity")
    west = [v.text for v in leaf.values if v.group == "west_central_east_african"]
    north = [v.text for v in leaf.values if v.group == "north_african"]

    async def answer(messages, project_id, max_tokens):
        return '```json\n{"groups": ["west_central_east_african", "north_african"], "items": ["Nigerian"]}\n```'
    assert sorted(await subset(leaf, "Nigerian or North African", None, answer)) == sorted(["Nigerian", *north])
    assert "Nigerian" in west

    async def nothing(messages, project_id, max_tokens):
        return '{"groups": [], "items": []}'
    asked = []

    async def counted(messages, project_id, max_tokens):
        asked.append(1)
        return await nothing(messages, project_id, max_tokens)
    assert await subset(leaf, "Martian", None, counted) == [] and len(asked) == 1   # an empty answer stands


async def test_a_long_list_is_asked_in_chunks_each_cached_on_its_own(tmp_path):
    """A list over WORDS_CHUNK values is asked in even chunks side by side, each its own question
    and cache entry: a chunk whose call fails is asked again later, alone. The age list is read
    whole (the minors rules need every band in view)."""
    from prompt_programs.narrow import WORDS_CHUNK, NarrowCache, subset
    from prompt_programs.vocab import AGE_LIST, vocabulary
    leaf = vocabulary().get("clothing.top")
    values = [v.text for v in leaf.eligible()]
    assert len(values) > WORDS_CHUNK
    asked: List[List[str]] = []
    fail_second = [True]

    async def first_of_each(messages, project_id, max_tokens):
        shown = json.loads(_asked(messages).split("\n")[1])
        asked.append(shown)
        if fail_second[0] and shown[0] != values[0]:
            raise RuntimeError("the endpoint went away")
        return json.dumps([shown[0]])
    cache = NarrowCache(tmp_path)
    assert await subset(leaf, "cropped", cache, first_of_each) is None   # a chunk unanswered: no answer yet
    chunks = [a for a in dict.fromkeys(map(tuple, asked))]
    assert len(chunks) == 2 and [v for c in chunks for v in c] == values and all(len(c) <= WORDS_CHUNK for c in chunks)
    assert len(asked) == 3   # the first chunk once, the failing one twice (one more try)
    asked.clear()
    fail_second[0] = False
    got = await subset(leaf, "cropped", cache, first_of_each)
    assert asked == [list(chunks[1])] and got == [chunks[0][0], chunks[1][0]]
    asked.clear()
    assert await subset(leaf, "cropped", cache, first_of_each) == got and asked == []
    ages = vocabulary().get(AGE_LIST)
    assert len(ages.eligible()) > WORDS_CHUNK
    assert await subset(ages, "elderly", None, first_of_each) == [ages.eligible()[0].text] and len(asked) == 1


async def test_an_animal_reading_is_checked_for_its_shape():
    animal = {"n": 1, "kind": "animal", "label": "Pet", "lead": "",
              "animal": {"noun": "pet", "vary": ["species", "life_stage"], "breed": "", "stated": {}}}
    got = await reader.read(parse("a girl walking her <pet>"), ask=FakeModel(json.dumps({"slots": [animal]})),
                            project_id=None, model="m")
    assert got["slots"][0]["animal"] == {"noun": "pet", "vary": ["species", "life_stage"], "breed": "", "stated": {}}
    both = {**animal, "animal": {"noun": "pet", "vary": ["species", "breed"], "breed": "animal.dog_breed", "stated": {}}}
    # A breed beside species, or a breed list that isn't there ("a cat breed"), is dropped; the rest stands.
    got = await reader.read(parse("a girl walking her <pet>"), ask=FakeModel(json.dumps({"slots": [both]})),
                            project_id=None, model="m")
    assert got["slots"][0]["animal"]["vary"] == ["species"]
    # The kind of animal the words call for is one of the species list's kinds, else left out.
    pet = {**animal, "animal": {**animal["animal"], "type": "pet"}}
    got = await reader.read(parse("a girl walking her <pet>"), ask=FakeModel(json.dumps({"slots": [pet]})),
                            project_id=None, model="m")
    assert got["slots"][0]["animal"]["type"] == "pet"
    odd = {**animal, "animal": {**animal["animal"], "type": "spaceship"}}
    got = await reader.read(parse("a girl walking her <pet>"), ask=FakeModel(json.dumps({"slots": [odd]})),
                            project_id=None, model="m")
    assert "type" not in got["slots"][0]["animal"] and not got["slots"][0].get("degraded")
    ferret = {**animal, "animal": {"noun": "ferret", "vary": ["breed", "life_stage"], "breed": "animal.ferret_breed",
                                   "stated": {"life_stage": "baby"}}}
    got = await reader.read(parse("a baby <ferret> on a windowsill"), ask=FakeModel(json.dumps({"slots": [ferret]})),
                            project_id=None, model="m")
    assert not got["slots"][0].get("degraded") and got["slots"][0]["animal"]["vary"] == ["life_stage"]
    kitten = {**animal, "animal": {"noun": "kitten", "vary": ["breed", "life_stage"], "breed": "animal.cat_breed",
                                   "stated": {"life_stage": "kitten"}}}
    got = await reader.read(parse("a <kitten> on a windowsill"), ask=FakeModel(json.dumps({"slots": [kitten]})),
                            project_id=None, model="m")
    assert got["slots"][0]["animal"] == {"noun": "kitten", "vary": ["breed", "life_stage"], "breed": "animal.cat_breed",
                                         "stated": {"life_stage": "kitten"}}
    old = {**animal, "animal": {"noun": "dog", "vary": ["breed"], "breed": "animal.dog_breed", "stated": {"life_stage": "old"}}}
    got = await reader.read(parse("an <old dog> asleep"), ask=FakeModel(json.dumps({"slots": [old]})), project_id=None, model="m")
    assert got["slots"][0]["animal"]["vary"] == ["breed", "life_stage"]


async def test_a_light_reading_may_name_a_lighting_list():
    light = {"n": 1, "kind": "light", "label": "Light", "lead": "",
             "light": {"list": "lighting.studio", "examples": ["softbox", "flash", "ring light"]}}
    got = await reader.read(parse("a portrait in <light>"), ask=FakeModel(json.dumps({"slots": [light]})),
                            project_id=None, model="m")
    assert got["slots"][0]["light"]["list"] == "lighting.studio"
    wrong = {**light, "light": {"list": "person.hairstyle", "examples": []}}
    model = FakeModel(json.dumps({"slots": [wrong]}), json.dumps({"slots": [light]}))
    await reader.read(parse("a portrait in <light>"), ask=model, project_id=None, model="m")
    assert "not one of the lighting lists" in model.asked[1][-1]["content"]


async def test_a_person_with_no_outfit_is_asked_once_why_then_stands():
    bare = {"n": 1, "kind": "person", "label": "Young man", "lead": "",
            "person": {"noun": "man", "presentation": "masculine", "stated": {"age": "young"}, "vary": ["age"], "outfit": ""}}
    model = FakeModel(json.dumps({"slots": [bare]}))
    got = await reader.read(parse("a <young man> in a dorm room"), ask=model, project_id=None, model="m")
    assert len(model.asked) == 2 and '"clothes"' in model.asked[1][-1]["content"]
    assert not got["slots"][0].get("degraded") and got["slots"][0]["person"]["outfit"] == ""
    dressed = {**bare, "person": {**bare["person"], "clothes": "in a red raincoat"}}
    model = FakeModel(json.dumps({"slots": [dressed]}))
    await reader.read(parse("a <young man> in a red raincoat"), ask=model, project_id=None, model="m")
    assert len(model.asked) == 1


async def test_a_person_keeps_the_words_that_say_what_they_wear_and_draws_no_outfit(tmp_path):
    # "in a red raincoat": the reading keeps the prompt's words, so the seeds plan no outfit and
    # the person's seeds say their clothes are the prompt's (their answers: no clothes to develop).
    from prompt_programs.seeding import plan, seeds_of
    dressed = {"n": 1, "kind": "person", "label": "Young man", "lead": "",
               "person": {"noun": "man", "presentation": "masculine", "stated": {"age": "young"}, "vary": ["age"],
                          "clothes": "in a red raincoat", "outfit": ""}}
    got = await reader.read(parse("a <young man> in a red raincoat"), ask=FakeModel(json.dumps({"slots": [dressed]})),
                            project_id=None, model="m")
    person = got["slots"][0]["person"]
    assert person["clothes"] == "in a red raincoat"
    p = plan(got["slots"][0], "young man")
    assert p["answers"]["clothes"] and not any(b["list"].startswith("person.outfit") for b in p["banks"])
    seeds = seeds_of({"kind": "person", "banks": [{**b, "narrowed": None} for b in p["banks"]], "answers": p["answers"]})
    assert "what they wear" in seeds.dropped and not seeds.typical
    # Words that aren't the prompt's are dropped, and then the outfit list stands.
    made_up = {**dressed, "person": {**dressed["person"], "clothes": "in a tuxedo", "outfit": "person.outfit.casual"}}
    got = await reader.read(parse("a <young man> in a red raincoat"), ask=FakeModel(json.dumps({"slots": [made_up]})),
                            project_id=None, model="m")
    assert "clothes" not in got["slots"][0]["person"] and not plan(got["slots"][0], "young man")["answers"].get("clothes")
    # The edit check is shown the clothes as part of what was read.
    assert '"clothes": "in a red raincoat"' in reader._read_as({"kind": "person", "person": person})


def test_the_reader_no_longer_asks_for_kinds_instead_or_light_examples():
    text = reader.system_text()
    assert '"kinds"' not in text and '"instead"' not in text and '"examples"' not in text
    assert "kinds (three" not in text and "instead:" not in text and "examples, three" not in text
    # a free part and a light with no list are good readings without them
    seg = parse("a <bench> lit by <light>").slots()
    free = reader.check_slot({"n": 1, "kind": "free", "label": "Bench", "lead": "", "free": {"about": "a bench"}},
                             seg[0], "a ", [])
    assert free["free"] == {"about": "a bench", "lists": []}
    light = reader.check_slot({"n": 2, "kind": "light", "label": "Light", "lead": "", "light": {"list": ""}},
                              seg[1], " lit by ", [])
    assert light["light"] == {"list": ""}


async def test_a_camera_that_varies_one_detail_is_that_details_list():
    # "<selfie camera angle>": a camera with only its angle varying would open on one row to
    # click through. It is read as the angle list itself, its words narrowing it.
    one = {"n": 1, "kind": "camera", "label": "Selfie camera angle", "lead": ", shot from",
           "camera": {"vary": ["angle"]}, "category": "camera angle"}
    prompt = "a woman on a rooftop, shot from <selfie camera angle>"
    got = await reader.read(parse(prompt), ask=FakeModel(json.dumps({"slots": [one]})), project_id=None, model="m")
    slot = got["slots"][0]
    assert not slot.get("degraded")
    assert slot["kind"] == "list" and slot["list"]["list"] == "camera.angle" and slot["category"] == "camera angle"
    assert slot["label"] == "Selfie camera angle" and slot["lead"] == ", shot from"
    # one value of the angle list per variant, narrowed by the slot's words
    banks = plan(slot, "selfie camera angle")["banks"]
    assert [(b["role"], b["list"], b["phrase"]) for b in banks] == [("core", "camera.angle", "selfie camera angle")]
    e = slots.compose(parse(prompt), {1: slot})
    assert e["choices"] == [{"id": "selfie_camera_angle", "kind": "variants", "label": "Selfie camera angle",
                             "slot": "selfie_camera_angle"}]
    # Two details stay a camera, seeded with ideas from each; a person always stays a person,
    # however few details it names.
    two = {**one, "camera": {"vary": ["angle", "lens"]}}
    got = await reader.read(parse(prompt), ask=FakeModel(json.dumps({"slots": [two]})), project_id=None, model="m")
    assert got["slots"][0]["kind"] == "camera"
    assert [(b["role"], b["list"]) for b in plan(got["slots"][0], "selfie camera angle")["banks"]] == [
        ("idea", "camera.angle"), ("idea", "camera.lens")]
    man = {"n": 1, "kind": "person", "label": "Young man", "lead": "",
           "person": {"noun": "man", "presentation": "masculine", "stated": {"age": "young"}, "vary": ["age"],
                      "outfit": "person.outfit.casual"}}
    got = await reader.read(parse("a <young man> in a dorm room"), ask=FakeModel(json.dumps({"slots": [man]})),
                            project_id=None, model="m")
    assert got["slots"][0]["kind"] == "person"


# --------------------------------------------------------------------------- a clothing part beside a person

WETSUIT_PROMPT = "a <woman> in a <wetsuit> on a research boat"
DIVER = {"n": 1, "kind": "person", "label": "Woman", "lead": "a",
         "person": {"noun": "woman", "presentation": "feminine", "stated": {},
                    "vary": ["age", "descent", "build", "hair"], "clothes": "", "clothes_part": 2,
                    "outfit": "person.outfit.summer", "outfit_examples": []}}
WETSUIT = {"n": 2, "kind": "free", "label": "Wetsuit", "lead": " in a",
           "free": {"about": "the woman's wetsuit", "kinds": ["shorty wetsuit", "full-length wetsuit", "drysuit"],
                    "instead": []}}


async def test_a_person_beside_a_part_that_is_their_clothes_draws_no_outfit():
    # "<woman> in a <wetsuit>": the wetsuit part varies her clothes, so her variants are seeded
    # with no outfit of her own, even when the reading also names an outfit list (the reading
    # says so; no words matched).
    model = FakeModel(json.dumps({"slots": [DIVER, WETSUIT]}))
    got = await reader.read(parse(WETSUIT_PROMPT), ask=model, project_id=None, model="m")
    assert len(model.asked) == 2   # one call a part, no retry
    person = got["slots"][0]["person"]
    assert person["outfit"] == "" and person["clothes_part"] == {"n": 2, "words": "wetsuit"}

    def outfits(reading):
        return [b for b in plan(reading, "woman")["banks"] if b["list"].startswith(("person.outfit", "clothing."))]
    assert not outfits(got["slots"][0])
    # whatever outfit a stored reading still carries
    stale = copy.deepcopy(got["slots"][0])
    stale["person"]["outfit"] = "person.outfit.summer"
    assert not outfits(stale)
    dressed = copy.deepcopy(stale)
    del dressed["person"]["clothes_part"]
    assert [b["list"] for b in outfits(dressed)] == ["person.outfit.summer"]


async def test_a_clothes_part_that_names_no_other_part_is_ignored():
    for wrong in (7, 1, "two"):
        bare = copy.deepcopy(DIVER)
        bare["person"].update(clothes_part=wrong, outfit="")
        dressed = copy.deepcopy(DIVER)
        dressed["person"].update(clothes_part=0, outfit="person.outfit.summer")
        model = FakeModel(json.dumps({"slots": [bare, WETSUIT]}), json.dumps({"slots": [dressed, WETSUIT]}))
        got = await reader.read_part(parse(WETSUIT_PROMPT), "slot", 1, ask=model, project_id=None, model="m")
        assert len(model.asked) == 2 and '"clothes_part"' in model.asked[1][-1]["content"]
        assert got["person"]["outfit"] == "person.outfit.summer" and "clothes_part" not in got["person"]


async def test_a_person_whose_clothes_part_is_gone_is_read_again(tmp_path):
    # Their clothes part on another line: an edit there leaves the person's own key as it was,
    # but a person whose wetsuit is gone would wear nothing drawn, so they are read again.
    cache = NarrowCache(tmp_path)
    before = "a <woman> on a research boat,\nin a <wetsuit>"
    model = FakeModel(json.dumps({"slots": [DIVER, WETSUIT]}))
    await reader.read(parse(before), ask=model, project_id=None, model="m", cache=cache)
    model = FakeModel(json.dumps({"slots": [DIVER, WETSUIT]}))
    await reader.read(parse(before), ask=model, project_id=None, model="m", cache=cache)
    assert len(model.asked) == 0
    dressed = copy.deepcopy(DIVER)
    dressed["person"].update(clothes_part=0)
    hat = {**WETSUIT, "label": "Hat", "free": {**WETSUIT["free"], "about": "her hat"}}
    model = FakeModel(json.dumps({"slots": [dressed, hat]}))
    got = await reader.read(parse("a <woman> on a research boat,\nin a <sun hat>"), ask=model, project_id=None,
                            model="m", cache=cache)
    assert len(model.asked) == 2 and got["slots"][0]["person"]["outfit"] == "person.outfit.summer"


def test_the_reader_is_shown_a_clothes_part_and_an_expression_beside_a_person():
    text = reader.system_text()
    assert "clothes_part" in text and '"clothes_part": 2' in text
    assert "the dancer's expression" in text


# --------------------------------------------------------------------------- words about someone read as a person

SILLY_AS_PERSON = {"n": 2, "kind": "person", "label": "Silly expression", "lead": " making a",
                   "person": {"noun": "expression", "presentation": "feminine", "stated": {}, "vary": [],
                              "face": True, "outfit": ""}}


async def test_an_expression_read_as_a_person_is_retried_with_the_reason():
    model = FakeModel(json.dumps({"slots": [SILLY_AS_PERSON]}), json.dumps({"slots": [SILLY_AS_LIST]}))
    got = await reader.read_part(parse(SILLY_PROMPT), "slot", 2, ask=model, project_id=None, model="m")
    assert len(model.asked) == 2
    why = model.asked[1][-1]["content"]
    assert "a person needs details to vary" in why and "expression" in why and "clothes_part" not in why
    assert got["kind"] == "list" and got["list"]["list"] == "person.expression"


async def test_an_expression_read_as_a_person_twice_degrades_to_a_free_slot():
    # On the retry too (an outfit doesn't make it a person): it stands as its words, never a second person.
    worse = copy.deepcopy(SILLY_AS_PERSON)
    worse["person"].update(outfit="person.outfit.casual")
    model = FakeModel(json.dumps({"slots": [SILLY_AS_PERSON]}), json.dumps({"slots": [worse]}))
    got = await reader.read_part(parse(SILLY_PROMPT), "slot", 2, ask=model, project_id=None, model="m")
    assert len(model.asked) == 2
    assert got["kind"] == "free" and got.get("degraded") is True
    e = slots.compose(parse(SILLY_PROMPT), {2: got})
    assert e["slots"][1]["degraded"] and e["choices"][1]["kind"] == "variants"


async def test_one_parts_reading_given_bare_is_taken_as_it_stands():
    model = FakeModel(json.dumps(WETSUIT))
    got = await reader.read_part(parse(WETSUIT_PROMPT), "slot", 2, ask=model, project_id=None, model="m")
    assert len(model.asked) == 1 and got["kind"] == "free" and not got.get("degraded")


async def test_a_made_up_outfit_list_twice_is_written_not_a_failed_reading():
    girl = {"n": 1, "kind": "person", "label": "Little girl", "lead": "a",
            "person": {"noun": "girl", "presentation": "feminine", "stated": {"age": "little"},
                       "vary": ["age", "descent", "hair"], "outfit": "person.outfit.party"}}
    model = FakeModel(json.dumps({"slots": [girl]}), json.dumps({"slots": [girl]}))
    got = await reader.read(parse("a <little girl> at a birthday party"), ask=model, project_id=None, model="m")
    assert "is not one of the lists" in model.asked[1][-1]["content"]
    slot = got["slots"][0]
    assert "degraded" not in slot and slot["kind"] == "person" and slot["person"]["outfit"] == "written"
