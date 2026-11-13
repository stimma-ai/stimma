"""The slot reader with a fake model: the numbered prompt, the reply's checks, one retry, the
two-level cache; slots.ensure and POST /prompt-programs/prepare on top of it."""

import copy
import json
import re
from typing import Any, Dict, List

import pytest

from prompt_programs import program as prep
from prompt_programs import reader, slots
from prompt_programs.narrow import NarrowCache
from prompt_programs.slots import parse

from test_slots_build import AFRICAN, DORM_PROMPT, DORM_READING, ELDERLY, PORCH_PROMPT, PORCH_READING

DORM_LIGHT = DORM_READING["slots"][1]


class FakeModel:
    """Answers the reader with queued replies (a reply may be a function of the messages) and
    narrowing with fixed subsets; records what the reader was asked."""

    def __init__(self, *replies: Any):
        self.replies: List[Any] = list(replies)
        self.asked: List[List[Dict[str, Any]]] = []

    async def __call__(self, messages, project_id, max_tokens):
        user = messages[-1]["content"]
        if messages[0]["content"].startswith("You read the parts of an image prompt"):
            self.asked.append(messages)
            got = self.replies.pop(0)
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
    import app_dirs
    import prompt_programs.fluent as fl
    monkeypatch.setattr(app_dirs, "get_profile_dir", lambda pid="default": tmp_path / str(pid))
    monkeypatch.setattr(fl, "filler_for", lambda pid: (_ for _ in ()).throw(RuntimeError("no filler in tests")))
    monkeypatch.setattr(fl, "_profile_store", lambda pid: None)

    async def fingerprint(project_id):
        return "fake-model"
    monkeypatch.setattr(prep, "model_fingerprint", fingerprint)
    monkeypatch.setattr(slots, "_in_flight", {})
    return "p"


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
                  "already says what they wear", "- hair_color:", "- person.outfit.casual:", "- person.hairstyle:"):
        assert words in text
    assert "EXACT" in text and "{catalog}" not in text and "{details}" not in text
    # Each kind's own fields are shown in their object: a list's id goes inside "list": {...}.
    assert '"list": {"list": "<the list\'s id>", "about": "..."}' in text
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
    got = await reader.read(parse(PORCH_PROMPT), ask=model, project_id=None, model="m")
    assert len(model.asked) == 2
    retry = model.asked[1]
    assert retry[-2] == {"role": "assistant", "content": "Sure! Here is the reading: {"}
    assert "isn't valid JSON" in retry[-1]["content"]
    assert [s["kind"] for s in got["slots"]] == ["person", "free"] and got["lists"] == [{"n": 1, "label": "Season"}]


async def test_one_bad_slot_among_good_ones_is_read_as_written_and_the_others_stand(tmp_path):
    cache = NarrowCache(tmp_path)
    model = FakeModel(_reply(PORCH_READING, n2={"kind": "thing"}), _reply(PORCH_READING, n2={"kind": "thing"}))
    got = await reader.read(parse(PORCH_PROMPT), ask=model, project_id=None, model="m", cache=cache)
    assert len(model.asked) == 2 and "kind must be one of" in model.asked[1][-1]["content"]
    man, pet = got["slots"]
    assert man["kind"] == "person" and "degraded" not in man
    assert pet["degraded"] is True and pet["kind"] == "free" and pet["label"] == "pet" and "kind must be" in pet["reason"]
    src, entry = slots.build(parse(PORCH_PROMPT), got)
    assert entry["example"].endswith("reading on a porch with his pet, summer evening") or \
        entry["example"].endswith("reading on a porch with his pet, autumn evening"), entry["example"]
    assert [m.get("degraded") for m in entry["slots"]] == [None, True] and entry["slots"][1]["details"] == []
    # nothing read as written is cached: the next read asks again, only for that slot
    model = FakeModel(_reply(PORCH_READING))
    again = await reader.read(parse(PORCH_PROMPT), ask=model, project_id=None, model="m", cache=cache)
    assert len(model.asked) == 1 and 'Answer only for: ⟨2⟩ "pet".' in model.asked[0][-1]["content"]
    assert again["slots"][1]["kind"] == "free" and "degraded" not in again["slots"][1]


async def test_a_reply_that_is_never_json_reads_every_slot_as_written():
    model = FakeModel("no", "still no")
    got = await reader.read(parse(PORCH_PROMPT), ask=model, project_id=None, model="m")
    assert [s["degraded"] for s in got["slots"]] == [True, True] and got["lists"] == [{"n": 1, "label": ""}]
    _, entry = slots.build(parse(PORCH_PROMPT), got)
    assert entry["example"].split("\n")[-1] in (
        "An elderly African man reading on a porch with his pet, summer evening",
        "An elderly African man reading on a porch with his pet, autumn evening"), entry["example"]


async def test_a_person_with_nothing_to_draw_twice_is_read_as_written():
    empty = {"slots": [{"n": 1, "kind": "person", "label": "Hairstyle", "lead": "",
                        "person": {"noun": "hairstyle", "presentation": "", "stated": {}, "vary": [], "outfit": ""}}]}
    got = await reader.read(parse("1girl, <hairstyle>, rooftop"), ask=FakeModel(json.dumps(empty), json.dumps(empty)),
                            project_id=None, model="m")
    assert got["slots"][0]["degraded"] is True
    assert slots.build(parse("1girl, <hairstyle>, rooftop"), got)[1]["example"] == "1girl, hairstyle, rooftop"


async def test_a_missing_part_or_a_list_that_doesnt_exist_is_retried():
    short = {"slots": PORCH_READING["slots"][:1], "lists": PORCH_READING["lists"]}
    model = FakeModel(json.dumps(short), _reply(PORCH_READING))
    await reader.read(parse(PORCH_PROMPT), ask=model, project_id=None, model="m")
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
    """Words about someone the prompt already has ("1boy, <expression>") read as a new person
    named from elsewhere: the noun isn't the part's words, so the reading is asked again."""
    other = {"n": 1, "kind": "person", "label": "Expression", "lead": ",",
             "person": {"noun": "boy", "presentation": "masculine", "stated": {}, "vary": ["hair"], "outfit": ""}}
    listed = {"n": 1, "kind": "list", "label": "Expression", "lead": ",",
              "list": {"list": "person.expression", "about": "the boy's expression"}}
    model = FakeModel(json.dumps({"slots": [other]}), json.dumps({"slots": [listed]}))
    got = await reader.read(parse("1boy, <expression>, city street"), ask=model, project_id=None, model="m")
    assert len(model.asked) == 2
    assert '"boy" is not among the words "expression"' in model.asked[1][-1]["content"]
    assert got["slots"][0]["list"] == {"list": "person.expression", "about": "the boy's expression"}
    # a noun from a note is the user's words too
    noted = {**other, "person": {**other["person"], "noun": "nurse"}}
    got = await reader.read(parse("# she is a nurse\n<tired woman>, hospital corridor"),
                            ask=FakeModel(json.dumps({"slots": [noted]})), project_id=None, model="m")
    assert got["slots"][0]["person"]["noun"] == "nurse"


def test_a_list_slot_is_narrowed_by_its_words_said_of_what_it_is_about():
    reading = {"slots": [{"n": 1, "kind": "list", "label": "Pet", "lead": " with his",
                          "list": {"list": "animal.species", "about": "his pet, on the porch"}}]}
    src, entry = slots.build(parse("a man on a porch with his <pet>"), reading)
    assert "cls='animal.species', about='his pet, on the porch'" in src
    assert entry["slot_words"] == {"pet": "pet"}


async def test_a_stated_detail_is_always_drawn():
    model = FakeModel(_reply(DORM_READING, n1={"person": {**DORM_READING["slots"][0]["person"], "vary": ["hair"]}}))
    got = await reader.read(parse(DORM_PROMPT), ask=model, project_id=None, model="m")
    assert got["slots"][0]["person"]["vary"] == ["hair", "age"]


async def test_a_lead_that_isnt_in_the_text_is_cleared():
    model = FakeModel(_reply(DORM_READING, n2={"lead": ", lighted with"}))
    got = await reader.read(parse(DORM_PROMPT), ask=model, project_id=None, model="m")
    assert got["slots"][1]["lead"] == ""
    model = FakeModel(_reply(DORM_READING))
    got = await reader.read(parse(DORM_PROMPT), ask=model, project_id=None, model="m")
    assert got["slots"][1]["lead"] == ", lit by"


async def test_words_that_arent_the_users_are_dropped_and_unknown_details_too():
    person = copy.deepcopy(PORCH_READING["slots"][0])
    person["person"]["stated"] = {"age": "elderly", "descent": "Kenyan", "hair": "granddaughter", "mood": "calm"}
    person["person"]["vary"] = ["age", "build", "expression", "hair"]
    model = FakeModel(json.dumps({"slots": [person, PORCH_READING["slots"][1]], "lists": PORCH_READING["lists"]}))
    got = await reader.read(parse(PORCH_PROMPT), ask=model, project_id=None, model="m")
    p = got["slots"][0]["person"]
    # "granddaughter" is copied from a comment line, so it is the user's words (what it means is the model's call)
    assert p["stated"] == {"age": "elderly", "hair": "granddaughter"}
    assert p["vary"] == ["age", "build", "hair"]


async def test_unknown_numbers_are_dropped():
    reading = copy.deepcopy(PORCH_READING)
    reading["slots"].append({**reading["slots"][1], "n": 7})
    reading["lists"].append({"n": 4, "label": "Nothing"})
    got = await reader.read(parse(PORCH_PROMPT), ask=FakeModel(json.dumps(reading)), project_id=None, model="m")
    assert [s["n"] for s in got["slots"]] == [1, 2] and [x["n"] for x in got["lists"]] == [1]


async def test_a_written_outfit_brings_its_examples_as_seeds():
    person = copy.deepcopy(DORM_READING["slots"][0])
    person["person"].update(outfit="written", outfit_examples=["a hoodie and track pants", "a band T-shirt and jeans",
                                                               "a flannel shirt and chinos"])
    model = FakeModel(json.dumps({"slots": [person, DORM_LIGHT]}))
    got = await reader.read(parse(DORM_PROMPT), ask=model, project_id=None, model="m")
    src, _ = slots.build(parse(DORM_PROMPT), got)
    assert "pick('young_man.outfit', about=\"Young man's outfit\", seed=['a hoodie and track pants'," in src
    person["person"]["outfit_examples"] = []
    model = FakeModel(json.dumps({"slots": [person, DORM_LIGHT]}), _reply(DORM_READING))
    await reader.read(parse(DORM_PROMPT), ask=model, project_id=None, model="m")
    assert "needs three outfit_examples" in model.asked[1][-1]["content"]


async def test_the_reading_is_cached_whole_and_per_slot(tmp_path):
    cache = NarrowCache(tmp_path)
    model = FakeModel(_reply(DORM_READING))
    first = await reader.read(parse(DORM_PROMPT), ask=model, project_id=None, model="m", cache=cache)
    again = await reader.read(parse(DORM_PROMPT), ask=model, project_id=None, model="m", cache=cache)
    assert first == again and len(model.asked) == 1
    # another reader model reads again
    await reader.read(parse(DORM_PROMPT), ask=FakeModel(_reply(DORM_READING)), project_id=None, model="other", cache=cache)


async def test_an_edit_on_another_line_asks_only_for_the_slot_whose_line_changed(tmp_path):
    cache = NarrowCache(tmp_path)
    before = "a <young man> on a bench\nnear a <dog> in the park"
    reading = {"slots": [DORM_READING["slots"][0],
                         {"n": 2, "kind": "free", "label": "Dog", "lead": "",
                          "free": {"about": "a dog in the park", "kinds": ["beagle", "whippet", "corgi"],
                                   "instead": ["pigeon", "kite", "bicycle"]}}]}
    await reader.read(parse(before), ask=FakeModel(json.dumps(reading)), project_id=None, model="m", cache=cache)

    def only_the_dog(messages):
        assert 'Answer only for: ⟨2⟩ "dog".' in messages[-1]["content"]
        assert "⟨1: young man⟩" in messages[-1]["content"]   # still shown the whole prompt
        return json.dumps({"slots": [{**reading["slots"][1], "label": "Dog"}]})
    model = FakeModel(only_the_dog)
    got = await reader.read(parse("a <young man> on a bench\nnear a <dog> by the lake"), ask=model, project_id=None,
                            model="m", cache=cache)
    assert len(model.asked) == 1 and [s["kind"] for s in got["slots"]] == ["person", "free"]
    assert got["slots"][0] == {**reader.check_slot(DORM_READING["slots"][0], parse(before).slots()[0], "a ", []), "n": 1}
    # a new note is context for every slot: all are read again
    model = FakeModel(json.dumps(reading))
    await reader.read(parse("# at dawn\n" + before), ask=model, project_id=None, model="m", cache=cache)
    assert "Answer only" not in model.asked[0][-1]["content"]


# --------------------------------------------------------------------------- ensure and /prepare

async def test_ensure_reads_builds_narrows_and_stores(profile, monkeypatch):
    model = _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    entry = await slots.ensure(PORCH_PROMPT, profile_id=profile)
    assert sorted(entry["filters"]["elderly_african_man.age"]) == sorted(ELDERLY)
    assert sorted(entry["filters"]["elderly_african_man.descent"]) == sorted(AFRICAN)
    assert entry["reading"]["slots"][1]["free"]["kinds"][0] == "ginger tabby cat"
    assert prep.store_for(profile).get(entry["key"])["program"] == entry["program"]
    again = await slots.ensure(PORCH_PROMPT, profile_id=profile)
    assert again["key"] == entry["key"] and len(model.asked) == 1
    assert await slots.ensure("a <cat>", profile_id=profile, cache_only=True) is None
    assert (await slots.ensure("a plain prompt", profile_id=profile)) == {"key": None, "slots": [], "choices": []}


async def test_a_stated_age_still_reaches_the_minors_policy(profile, monkeypatch):
    from prompt_programs.options import program_minors
    from prompt_programs.vocab import vocabulary
    young = [v.text for v in vocabulary().get("person.age_band").values if v.minor][:3]
    reading = {"slots": [{"n": 1, "kind": "person", "label": "Boy", "lead": "",
                          "person": {"noun": "boy", "presentation": "masculine", "stated": {"age": "10-year-old"},
                                     "vary": ["hair", "hair_color"], "outfit": ""}}]}

    class Young(FakeModel):
        async def __call__(self, messages, project_id, max_tokens):
            if messages[-1]["content"].startswith('The list "Age"'):
                assert '"10-year-old"' in messages[-1]["content"]
                return json.dumps(young)
            return await super().__call__(messages, project_id, max_tokens)
    _use(monkeypatch, Young(json.dumps(reading)))
    entry = await slots.ensure("a <10-year-old boy> flying a kite", profile_id=profile)
    # the stated age is drawn, within the words, so the prompt keeps it and the pools know it
    assert entry["reading"]["slots"][0]["person"]["vary"] == ["hair", "hair_color", "age"]
    assert entry["filters"]["slot_10_year_old_boy.age"] == young
    assert dict(program_minors(entry)) == {"slot_10_year_old_boy": tuple(young)}


def _client(monkeypatch, profile):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import prompt_programs as route
    monkeypatch.setattr(route, "get_current_profile", lambda: profile)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app, raise_server_exceptions=False)


def test_the_prepare_route_answers_with_slots_and_choices(profile, monkeypatch):
    _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    client = _client(monkeypatch, profile)
    typed = "  " + PORCH_PROMPT   # spans are in the prompt as typed
    assert client.post("/api/prompt-programs/prepare", json={"tool_id": "t", "prompt": typed, "cache_only": True}).json() == {"key": None}
    out = client.post("/api/prompt-programs/prepare", json={"tool_id": "t", "prompt": typed}).json()
    assert set(out) == {"key", "slots", "choices", "example", "seconds"}
    man, pet = out["slots"]
    assert man["id"] == "elderly_african_man" and man["kind"] == "person" and man["words"] == "elderly African man"
    assert typed[man["span"][0]:man["span"][1]] == "<elderly African man>" and man["line"] == 2
    assert man["stated"] == {"age": "elderly", "descent": "African"}
    assert "elderly_african_man.outfit" in man["details"] and "elderly_african_man.outfit.colors" in man["details"]
    assert pet == {"id": "pet", "n": 2, "kind": "free", "label": "Pet", "words": "pet",
                   "span": [typed.index("<pet>"), typed.index("<pet>") + 5], "line": 2, "details": ["pet"]}
    by_id = {c["id"]: c for c in out["choices"]}
    assert by_id["pet"]["slot"] == "pet" and "source" not in by_id["pet"]
    assert by_id["elderly_african_man.age"]["slot"] == "elderly_african_man"
    assert sorted(by_id["elderly_african_man.age"]["options"]) == sorted(ELDERLY)
    assert by_id["list1"] == {"id": "list1", "kind": "pick", "label": "Season", "options": ["summer", "autumn"],
                              "source": "list", "line": 2}
    assert by_id["elderly_african_man.outfit.colors"]["follows"] == "elderly_african_man.outfit"
    assert "program" not in out and "wildcard" not in str(out) and "said" not in str(out)
    nothing = client.post("/api/prompt-programs/prepare", json={"tool_id": "t", "prompt": "a cat on a mat"}).json()
    assert nothing == {"key": None, "slots": [], "choices": []}


def test_a_reading_that_cant_be_used_still_prepares_and_says_degraded(profile, monkeypatch):
    model = _use(monkeypatch, FakeModel("no", "still no", _reply(DORM_READING)))
    client = _client(monkeypatch, profile)
    r = client.post("/api/prompt-programs/prepare", json={"tool_id": "t", "prompt": DORM_PROMPT})
    assert r.status_code == 200
    out = r.json()
    assert [s["degraded"] for s in out["slots"]] == [True, True] and out["example"] == "Dorm room with a young man, lit by light"
    # served to a lookup, read again by the next prepare
    assert client.post("/api/prompt-programs/prepare", json={"tool_id": "t", "prompt": DORM_PROMPT,
                                                             "cache_only": True}).json()["key"] == out["key"]
    again = client.post("/api/prompt-programs/prepare", json={"tool_id": "t", "prompt": DORM_PROMPT}).json()
    assert len(model.asked) == 3 and not any(s.get("degraded") for s in again["slots"])


class SlowDescent(FakeModel):
    """Narrowing the descent list answers late; `fails` makes it fail instead."""

    def __init__(self, *replies: Any, delay: float = 0.0, fails: bool = False):
        super().__init__(*replies)
        self.delay, self.fails, self.descent_asks = delay, fails, 0

    async def __call__(self, messages, project_id, max_tokens):
        import asyncio
        if messages[-1]["content"].startswith('The list "Descent"'):
            self.descent_asks += 1
            await asyncio.sleep(self.delay)
            if self.fails:
                raise RuntimeError("the endpoint went away")
        return await super().__call__(messages, project_id, max_tokens)


async def test_a_slow_narrowing_is_waited_for_and_the_example_is_drawn_after_it(profile, monkeypatch):
    """Past the old time limit the run still waits: the first draw of an <elderly African man> is
    elderly and of African descent, and so is the example."""
    import prompt_programs.narrow as nw
    monkeypatch.setattr(nw, "NARROW_SECONDS", 5.0)
    _use(monkeypatch, SlowDescent(_reply(PORCH_READING), delay=1.0))
    entry = await slots.ensure(PORCH_PROMPT, profile_id=profile)
    assert "narrow_pending" not in entry
    assert sorted(entry["filters"]["elderly_african_man.descent"]) == sorted(AFRICAN)
    assert any(d in entry["example"] for d in AFRICAN), entry["example"]
    assert any(a in entry["example"] for a in ELDERLY), entry["example"]
    for seed in range(8):
        drawn = {d.id: d.value for d in prep.realize(entry, seed=seed).draws}
        assert drawn["elderly_african_man.descent"] in AFRICAN and drawn["elderly_african_man.age"] in ELDERLY


def _stands_as_typed(entry):
    """Every draw keeps "African" as typed, and the man's age still within "elderly"."""
    for seed in range(6):
        r = prep.realize(entry, seed=seed)
        drawn = {d.id: d.value for d in r.draws}
        assert " African man" in r.prompt, r.prompt
        assert drawn["elderly_african_man.age"] in ELDERLY
        assert not any(d in r.prompt for d in AFRICAN)


async def test_a_narrowing_that_fails_keeps_the_stated_words_as_typed_and_the_run_goes_on(profile, monkeypatch):
    model = _use(monkeypatch, SlowDescent(_reply(PORCH_READING), fails=True))
    entry = await slots.ensure(PORCH_PROMPT, profile_id=profile)
    assert model.descent_asks >= 2   # one more try, then the words stand as typed
    assert entry["degraded"] is True and "narrow_pending" not in entry
    assert entry["slots"][0]["degraded"] is True and "elderly_african_man.age" in entry["slots"][0]["details"]
    _stands_as_typed(entry)
    # a lookup gets it; the next prepare narrows again
    assert (await slots.ensure(PORCH_PROMPT, profile_id=profile, cache_only=True))["key"] == entry["key"]
    model = _use(monkeypatch, SlowDescent())
    again = await slots.ensure(PORCH_PROMPT, profile_id=profile)
    assert model.descent_asks >= 1 and not again.get("degraded")
    assert sorted(again["filters"]["elderly_african_man.descent"]) == sorted(AFRICAN)


async def test_a_narrowing_past_the_time_limit_keeps_the_stated_words_as_typed(profile, monkeypatch):
    import prompt_programs.narrow as nw
    monkeypatch.setattr(nw, "NARROW_SECONDS", 0.5)
    _use(monkeypatch, SlowDescent(_reply(PORCH_READING), delay=3.0))
    entry = await slots.ensure(PORCH_PROMPT, profile_id=profile)
    assert entry["degraded"] is True
    _stands_as_typed(entry)


def test_a_failed_narrowing_still_prepares(profile, monkeypatch):
    _use(monkeypatch, SlowDescent(_reply(PORCH_READING), fails=True))
    r = _client(monkeypatch, profile).post("/api/prompt-programs/prepare", json={"tool_id": "t", "prompt": PORCH_PROMPT})
    assert r.status_code == 200 and r.json()["slots"][0]["degraded"] is True
    assert " African man" in r.json()["example"]


async def test_a_stored_entry_with_unfinished_narrowing_is_narrowed_before_it_draws(profile, monkeypatch):
    """An entry an older build stored with narrowing pending is narrowed before it is used."""
    _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    entry = await slots.ensure(PORCH_PROMPT, profile_id=profile)
    store = prep.store_for(profile)
    stale = copy.deepcopy(entry)
    descent = next(c for c in stale["choices"] if c["id"] == "elderly_african_man.descent")
    stale["narrow_pending"] = {descent["id"]: {"cls": descent.get("cls") or "person.descent", "options": []}}
    stale["filters"].pop(descent["id"], None)
    store.put(entry["key"], stale)
    model = _use(monkeypatch, SlowDescent())
    again = await slots.ensure(PORCH_PROMPT, profile_id=profile)
    assert model.descent_asks == 0   # its answer is cached on disk from the first prepare
    assert "narrow_pending" not in again and sorted(again["filters"][descent["id"]]) == sorted(AFRICAN)
    assert "narrow_pending" not in store.get(entry["key"])


def test_the_outfit_follows_presentation_and_is_set_off_by_a_comma():
    src, entry = slots.build(parse(PORCH_PROMPT), PORCH_READING)
    assert "cls='person.outfit.casual', where={'presentation': 'masculine'}" in src
    assert "wearing=slot1_outfit, close=','" in src
    assert re.search(r", wearing [^,]+, reading on a porch", entry["example"])


def test_a_person_with_no_outfit_still_closes_with_the_comma():
    """The comma before "reading" belongs to the person's description, not to the outfit: with no
    outfit it follows their hair or beard, and with nothing of them drawn it goes."""
    from test_slots_build import _draw
    reading = copy.deepcopy(PORCH_READING)
    reading["slots"][0]["person"]["outfit"] = ""
    _, entry = slots.build(parse(PORCH_PROMPT), reading)
    body = entry["example"].split("\n")[-1]
    assert re.search(r"man with [^,]+, [^,]+, reading on a porch", body), body
    details = [c["id"] for c in entry["choices"] if c["id"].startswith("elderly_african_man.")]
    bare = _draw(entry, 1, edits={d: {"off": True} for d in details}).prompt.split("\n")[-1]
    assert bare.startswith("An elderly African man reading on a porch"), bare   # as written: no comma
    hair = _draw(entry, 1, edits={d: {"off": True} for d in details if d.endswith("facial_hair")}).prompt
    assert re.search(r"hair, reading on a porch", hair), hair


def test_lookups_and_cache_hits_start_no_background_work(profile, monkeypatch):
    started = []
    monkeypatch.setattr(prep, "on_prepared", lambda entry, **kw: started.append(entry["key"]))
    model = _use(monkeypatch, FakeModel(_reply(PORCH_READING)))
    client = _client(monkeypatch, profile)
    body = {"tool_id": "t", "prompt": PORCH_PROMPT}
    assert client.post("/api/prompt-programs/prepare", json={**body, "cache_only": True}).json() == {"key": None}
    first = client.post("/api/prompt-programs/prepare", json=body).json()
    client.post("/api/prompt-programs/prepare", json={**body, "cache_only": True})
    client.post("/api/prompt-programs/prepare", json=body)
    assert started == [first["key"]] and len(model.asked) == 1   # once, for the fresh prepare


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

