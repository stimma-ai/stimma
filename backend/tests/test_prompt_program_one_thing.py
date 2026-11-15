"""A part that names one specific thing (a place, a brand, a character, people the words settle)
against one that names a kind of thing: the reader's answer, the seeds it gets, the writer's
brief and the check that keeps its words as typed."""

import json
import random

from prompt_programs import reader
from prompt_programs import variants as V
from prompt_programs.seeding import is_one, plan, seeds_of
from prompt_programs.slots import parse
from prompt_programs.vocab import vocabulary

from test_prompt_program_variants import slot_of
from test_slots_reader import FakeModel, PORCH_PROMPT, PORCH_READING, _use, bank, profile, ready  # noqa: F401

SHOP_PROMPT = "An <abandoned McDonald’s> in 1984 <Shinjuku>, Kodachrome photo"
SHOP = {"n": 1, "kind": "free", "label": "Abandoned McDonald’s", "lead": "An", "names": "one", "category": "McDonald’s",
        "free": {"about": "the restaurant", "lists": ["place.building"]}}
CHARACTER_PROMPT = "short <Holmes from the stories> handing out flyers on a busy street"
CHARACTER = {"n": 1, "kind": "person", "label": "Holmes", "lead": "", "names": "one", "category": "",
             "person": {"noun": "Holmes", "presentation": "masculine", "stated": {}, "vary": [], "clothes_part": 0,
                        "clothes": "", "dress": "", "outfit": "written", "place": "", "people": "one", "being": "human"}}


async def _read(prompt, n, reading, **changes):
    model = FakeModel(json.dumps({"slots": [{**reading, **changes}]}))
    got = await reader.read_part(parse(prompt), "slot", n, ask=model, project_id=None, model="m")
    return got, model


# --------------------------------------------------------------------------- the reading

def test_the_reader_asks_every_part_whether_it_names_one_thing_or_a_kind():
    text = reader.system_text()
    assert '- names: "one" when' in text and '"kind" when they name a kind of thing' in text
    assert 'A person named by name' in text   # the person kind's own words on it, from its data
    assert '"names": "one"' in text and "Sherlock Holmes" in text   # a worked example of each
    assert '"names": "kind"' in text
    assert "{one}" not in text and "[EXACT" not in text.split("hidden from you.")[1]


async def test_one_thing_keeps_every_word_and_a_kind_keeps_its_category():
    got, model = await _read(SHOP_PROMPT, 1, SHOP)
    assert len(model.asked) == 1 and got["names"] == "one" and got["category"] == ""
    assert is_one(got)
    for slip in ("kind", "One thing", None, 1, ["one"]):
        got, _ = await _read(SHOP_PROMPT, 1, SHOP, names=slip)
        assert "names" not in got and got["category"] == "McDonald’s" and not is_one(got)   # today's reading
    got, _ = await _read(SHOP_PROMPT, 1, {k: v for k, v in SHOP.items() if k != "names"})
    assert "names" not in got


async def test_one_person_needs_no_detail_to_vary_and_a_kind_of_person_still_does():
    got, model = await _read(CHARACTER_PROMPT, 1, CHARACTER)
    assert len(model.asked) == 1 and not got.get("degraded") and got["names"] == "one"
    got, model = await _read(CHARACTER_PROMPT, 1, CHARACTER, names="kind")
    assert len(model.asked) == 2   # nothing to vary: asked again, as before


# --------------------------------------------------------------------------- the seeds

def test_one_thing_seeds_no_member_of_its_kind():
    assert plan(SHOP, "abandoned McDonald’s") == {"kind": "free", "banks": [], "one": True}
    listed = {"n": 1, "kind": "list", "label": "Tower", "lead": "", "names": "one",
              "list": {"list": "camera.angle", "about": "the tower"}}
    assert plan(listed, "Eiffel tower")["banks"] == []
    kind = {k: v for k, v in SHOP.items() if k != "names"}
    assert [b["list"] for b in plan(kind, "abandoned McDonald’s")["banks"]] == ["place.building"]


def test_one_person_keeps_only_their_age_list_for_the_minors_rules():
    p = plan(CHARACTER, "Holmes from the stories")
    assert p["one"] and [b["role"] for b in p["banks"]] == ["age"]
    kind = plan({**CHARACTER, "names": "kind", "person": {**CHARACTER["person"], "vary": ["age", "descent", "hair"]}},
                "Holmes from the stories")
    assert {"descent", "gender", "age", "idea"} <= {b["role"] for b in kind["banks"]}


def test_one_persons_seeds_have_no_descent_gender_age_ideas_or_family_note():
    k = vocabulary().kind("person")
    ages = ["30-year-old", "40-year-old", "50-year-old"] + [v.text for v in vocabulary().get(V.AGE).values
                                                          if not v.opt_in][:3]
    seeds = V.kind_seeds(k, heritage=("person.ethnicity", None), who=("person.gender", None), ages=ages, age_role=True,
                         ideas=[("person.build", None), ("person.hair_color", None)],
                         answers={"people": "family"}, one=True)
    assert seeds.one and seeds.descent is None and seeds.gender is None and seeds.age is None and not seeds.ideas
    assert not seeds.notes and not seeds.typical and not seeds.heritage_list
    assert set(k.aspects.one_drop) <= set(seeds.dropped) and {"build", "how their age shows"} <= set(seeds.dropped)
    d = V.draw_seeds(random.Random(1), seeds, 12, "Holmes")
    assert all(not s.descent and not s.gender and not s.age and not s.ideas for s in d.specs)
    assert all(not ({"build", "face", "how their age shows"} & set(s.develop)) for s in d.specs)
    # a teenager named exactly keeps the minors line
    teen = V.kind_seeds(k, ages=["15-year-old", "16-year-old"], age_role=True, minor=("15-year-old", "16-year-old"), one=True)
    assert teen.age is None and teen.minor and V.minors_lines(teen) and "under 18" in V.minors_lines(teen)[0]


def test_one_things_record_gives_plain_seeds():
    assert seeds_of({"kind": "free", "banks": [], "one": True}) == V.Seeds(one=True)
    assert seeds_of({"kind": "free", "banks": [], "one": True, "young": "teenager"}).young == "teenager"


# --------------------------------------------------------------------------- the writer

def test_the_writer_is_told_it_is_that_same_thing_with_its_words_as_typed():
    sl = slot_of(SHOP_PROMPT, kind="free", category="")
    one = V.Slot(words=sl.words, prompt=sl.prompt, span=sl.span, kind="free", one=True)
    assert one.keep() == ["abandoned McDonald’s"] and sl.keep() == ["abandoned mcdonald's"]
    d = V.draw_seeds(random.Random(2), V.Seeds(one=True), 10, one.words)
    msg = V.messages(one, d, V.Seeds(one=True))[1]["content"]
    assert 'contains exactly "abandoned McDonald’s", with the same spelling and capitals' in msg
    assert "never a substitute for it, another one of its kind" in msg and "Category word" not in msg
    assert "No category word" not in msg and "Seeds, one line per variant" not in msg
    kind = V.messages(sl, d, V.Seeds())[1]["content"]
    assert "names one specific thing" not in kind and 'No category word: every variant contains exactly these words: "abandoned mcdonald\'s"' in kind


def test_one_person_is_told_to_stay_who_they_are_and_gets_no_family_note():
    k = vocabulary().kind("person")
    sl = slot_of("<Twin teenager girls> fighting over a <boy>", kind="person")
    one = V.Slot(words=sl.words, prompt=sl.prompt, span=sl.span, kind="person", one=True)
    seeds = V.kind_seeds(k, answers={"people": "family"}, one=True)
    family = V.kind_seeds(k, answers={"people": "family"})
    d = V.draw_seeds(random.Random(3), seeds, 10, one.words)
    msg = V.messages(one, d, seeds)[1]["content"]
    assert k.writer_one in msg and "Never change who they are, add anyone to them" in msg
    assert not any(n in msg for n in family.notes)
    assert '"Twin teenager girls"' in msg


def test_a_lowercased_name_is_dropped_and_a_capital_at_the_start_is_fine():
    spec = V.Spec()
    keep = ["abandoned McDonald’s"]
    assert V.check("abandoned McDonald's with peeling seats", "abandoned McDonald’s", keep, spec, exact=True) == ""
    assert V.check("Abandoned McDonald’s at dusk", "abandoned McDonald’s", keep, spec, exact=True) == ""
    assert V.check("abandoned mcdonald's at dusk", "abandoned McDonald’s", keep, spec, exact=True) == "capitals not kept"
    assert V.check("abandoned burger joint at dusk", "abandoned McDonald’s", keep, spec, exact=True) == "words not kept"
    # a kind of thing keeps today's check: case aside
    assert V.check("abandoned mcdonald's at dusk", "abandoned McDonald’s", ["abandoned mcdonald's"], spec) == ""


def test_kept_runs_as_typed():
    assert V.kept_chunks("the Eiffel Tower", exact=True) == ["Eiffel Tower"]
    assert V.kept_chunks("Tatsumaki from OnePunchMan", exact=True) == ["Tatsumaki from OnePunchMan"]
    assert V.kept_chunks("1girl", exact=True) == ["1girl"]
    assert V.kept_chunks("Central Park") == ["central park"]   # a kind's runs: lowercased words, as before


# --------------------------------------------------------------------------- end to end

async def test_a_prepared_slot_naming_one_thing_is_written_as_it(profile, monkeypatch):  # noqa: F811
    from prompt_programs import variant_pools as P
    porch = json.loads(json.dumps(PORCH_READING))
    porch["slots"][1] = {"n": 2, "kind": "free", "label": "Rex", "lead": " with his", "names": "one",
                         "category": "", "free": {"about": "his dog Rex", "lists": ["animal.species"]}}
    _use(monkeypatch, FakeModel(json.dumps(porch)))
    entry = await ready(PORCH_PROMPT, profile)
    pet = next(s for s in entry["slots"] if s["n"] == 2)
    assert pet.get("one") and entry["seeds"][pet["id"]]["one"] and entry["seeds"][pet["id"]]["banks"] == []
    man = next(s for s in entry["slots"] if s["n"] == 1)
    assert not man.get("one") and bank(entry, man["id"], "descent")
    asked = [c for c in P.ASK.calls if c["words"] == "pet"]
    assert asked and all("names one specific thing" in c["first"] for c in asked)


def test_a_persons_gender_keeps_to_the_presentation_the_reader_gives():
    nymph = {"n": 1, "kind": "person", "label": "Nymph", "lead": "",
             "person": {"noun": "Nymph", "presentation": "feminine", "stated": {}, "vary": ["hair"], "outfit": "written",
                        "people": "one", "being": "other"}}
    who = next(b for b in plan(nymph, "Nymph")["banks"] if b["role"] == "gender")
    assert who["where"] == {"presentation": "feminine"}
    open_ = {**nymph, "person": {**nymph["person"], "presentation": ""}}
    assert "where" not in next(b for b in plan(open_, "chef")["banks"] if b["role"] == "gender")
