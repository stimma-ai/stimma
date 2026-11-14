"""Who may be under 18 (stimma-plans MINORS_POLICY.md): ages under 18 enter a person's seeds only
after the model's explicit yes that the prompt's own words make them a child or a teenager
(narrow.under_18). A narrowing that merely leaves young ages in, a no, a failed call or an
unreadable reply all mean an adult. The model here is faked; the narrowing and the yes/no run as
in the product."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from prompt_programs import narrow, seeding
from prompt_programs import variants as V
from prompt_programs.narrow import NarrowCache, parse_under_18, under_18
from prompt_programs.vocab import AGE_LIST, vocabulary


def _ages() -> List[str]:
    return [v.text for v in vocabulary().get(AGE_LIST).values]


def _young() -> set:
    return {v.text for v in vocabulary().get(AGE_LIST).values if v.minor}


class FakeModel:
    """Answers the age narrowing by keeping every age, young ones included (what a model did for
    "farmer"), and the yes/no from `yes` by the words asked about (anything else: `other`)."""

    def __init__(self, yes: Dict[str, Any], other: str = '{"under_18": "no"}', keep: Optional[List[str]] = None):
        self.yes, self.other, self.keep = yes, other, keep
        self.asked: List[str] = []

    async def __call__(self, messages, project_id, tokens):
        system, user = messages[0]["content"], messages[1]["content"]
        if system == narrow.UNDER_18_SYSTEM:
            words = user.split('"')[1]
            self.asked.append(words)
            got = self.yes.get(words, self.other)
            if isinstance(got, Exception):
                raise got
            return got
        return json.dumps(self.keep if self.keep is not None else _ages())


def _record(model, words: str, prompt: str, lists=None, reading: Optional[Dict[str, Any]] = None,
            cache: Optional[NarrowCache] = None) -> Dict[str, Any]:
    reading = reading or {"n": 1, "kind": "person", "label": words, "lead": "a", "category": "",
                          "person": {"noun": words.split()[-1], "presentation": "", "stated": {},
                                     "vary": ["age", "descent", "build", "hair"], "outfit": "person.outfit.casual"}}
    entry = {"prompt": prompt, "segments": [], "slots": [{"id": "s1", "n": 1, "words": words, "state": "ready", "line": 1}],
             "readings": {"slots": [reading]}, "lists": lists or []}
    asyncio.run(seeding.narrow_seeds(entry, cache, model))
    return entry["seeds"]["s1"]


def _age_bank(record):
    return next(b for b in record["banks"] if b["role"] == "age")


def test_a_narrowing_that_leaves_young_ages_in_never_makes_an_unqualified_word_a_minor():
    model = FakeModel({})
    record = _record(model, "farmer", "a <farmer> in rural Vietnam, <camera>")
    assert "minor" not in record
    kept = _age_bank(record)["narrowed"]
    assert kept and not (set(kept) & _young())   # the young ages leave their ages too
    seeds = seeding.seeds_of(record)
    assert seeds.minor == ()
    assert not {t for t, _ in seeds.age.values} & _young()
    assert V.age_stages(*seeding.age_basis(record)) and not set().union(*V.age_stages(*seeding.age_basis(record)).values()) & _young()
    assert model.asked == ["farmer"]


def test_an_explicit_yes_lets_the_young_ages_the_narrowing_kept_count():
    young = sorted(_young(), key=_ages().index)[:6]
    model = FakeModel({"little girl": '{"under_18": "yes"}'}, keep=young)
    record = _record(model, "little girl", "a <little girl> at a birthday party")
    assert record["minor"] == young
    assert set(seeding.seeds_of(record).minor) == set(young)


def test_a_failed_or_unreadable_yes_or_no_is_an_adult_and_is_not_cached(tmp_path):
    cache = NarrowCache(tmp_path)
    for reply in (RuntimeError("down"), "maybe", '{"under_18": "perhaps"}', "", '["8-year-old"]'):
        model = FakeModel({"toddler": reply})
        record = _record(model, "toddler", "a <toddler> playing in the sand", cache=cache)
        assert "minor" not in record, reply
        assert not set(_age_bank(record)["narrowed"] or ()) & _young()
    model = FakeModel({"toddler": '{"under_18": "yes"}'})
    assert "minor" in _record(model, "toddler", "a <toddler> playing in the sand", cache=cache)
    model = FakeModel({})   # the yes is cached now: asked no more
    assert "minor" in _record(model, "toddler", "a <toddler> playing in the sand", cache=cache) and model.asked == []


def test_only_a_yes_counts_whatever_the_narrowing_keeps():
    # A no with only young ages kept: no age seeds at all (the writer is told they are an adult).
    model = FakeModel({}, keep=sorted(_young()))
    record = _record(model, "girl", "a <girl> in a cafe")
    assert "minor" not in record and _age_bank(record)["narrowed"] is None
    assert seeding.seeds_of(record).age is None
    # A yes with only adult ages kept: still no minor.
    model = FakeModel({"girl": '{"under_18": "yes"}'}, keep=[t for t in _ages() if t not in _young()][:5])
    assert "minor" not in _record(model, "girl", "a <girl> in a cafe")


def test_a_user_lists_ages_count_only_after_a_yes():
    lists = [{"n": 1, "line": 1, "items": ["8-year-old", "30-year-old"]}]
    model = FakeModel({}, keep=None)
    model.keep = None

    async def ask(messages, project_id, tokens):   # each list item narrowed to itself
        user = messages[1]["content"]
        if messages[0]["content"] == narrow.UNDER_18_SYSTEM:
            return await model(messages, project_id, tokens)
        word = user.split('fit "')[1].split('"')[0]
        return json.dumps([word]) if word in _ages() else json.dumps([t for t in _ages() if t not in _young()])
    prompt = "a <person>, {8-year-old|30-year-old} at the beach"
    assert "minor" not in _record(ask, "person", prompt, lists=lists)
    model.yes = {"8-year-old": '{"under_18": "yes"}'}
    assert _record(ask, "person", prompt, lists=lists)["minor"] == ["8-year-old"]


def test_a_list_slot_about_someone_reads_their_age_with_the_yes_or_no():
    reading = {"n": 1, "kind": "list", "label": "Outfit", "lead": "in", "category": "outfit",
               "list": {"list": "person.outfit.summer", "about": "her outfit", "presentation": "feminine"}}
    prompt = "a girl in <outfit> at the beach"
    model = FakeModel({})
    assert "minor" not in _record(model, "outfit", prompt, reading=reading)
    model = FakeModel({prompt: '{"under_18": "yes"}'})
    assert _record(model, "outfit", prompt, reading=reading)["minor"]


def test_the_reply_is_read_as_yes_no_or_nothing():
    assert parse_under_18('{"under_18": "yes"}') is True
    assert parse_under_18('Sure: {"under_18": "No"}') is False
    assert parse_under_18('{"under_18": true}') is True
    assert parse_under_18("<think>hmm</think>no") is False
    assert parse_under_18("Yes.") is True
    for bad in ("", "maybe", "yes and no", '{"child": "yes"}', '{"under_18": "unsure"}', None):
        assert parse_under_18(bad) is None


def test_the_question_carries_the_policy_and_the_prompt():
    msgs = narrow.under_18_messages("girl", "the girl's age", "a <girl> in a cafe")
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert '"A girl" or "a boy" alone is a young adult' in system
    for w in ("little girl", "toddler", "schoolboy", "teenager"):
        assert w in system
    assert '"girl"' in user and "a <girl> in a cafe" in user


def test_under_18_never_raises_and_reads_the_cache_only_without_a_model(tmp_path):
    cache = NarrowCache(tmp_path)

    async def broken(*a):
        raise RuntimeError("down")
    assert asyncio.run(under_18("toddler", cache, broken)) is None
    assert asyncio.run(under_18("toddler", cache, None)) is None

    async def yes(*a):
        return '{"under_18": "yes"}'
    assert asyncio.run(under_18("toddler", cache, yes)) is True
    assert asyncio.run(under_18("toddler", cache, None)) is True


def test_a_narrowing_retry_starts_differently_and_a_one_string_reply_is_read():
    from prompt_programs.vocab import vocabulary
    leaf = vocabulary().get("animal.dog_breed")
    vals = [v.text for v in leaf.eligible()][:20]
    sent: List[str] = []

    async def ask(messages, project_id, tokens):
        sent.append(messages[1]["content"])
        return "!" * 200 if len(sent) == 1 else json.dumps([", ".join(vals[:3])])
    got = asyncio.run(narrow._ask_subset(leaf, "dog", None, ask, None, "the dog's breed", "", "k", vals))
    assert got == vals[:3]
    assert not sent[0].startswith(narrow.RETRY_LEAD) and sent[1] == narrow.RETRY_LEAD + sent[0]


def test_a_yes_counts_only_when_asked_again_it_is_a_yes_too(tmp_path):
    replies = ['{"under_18": "yes"}', '{"under_18": "no"}']

    async def flip(*a):
        return replies.pop(0)
    cache = NarrowCache(tmp_path)
    assert asyncio.run(under_18("boy", cache, flip, None, "the boy's age", "a <boy> at the park")) is False
    assert asyncio.run(under_18("boy", cache, None, None, "the boy's age", "a <boy> at the park")) is False   # cached
    asked = []

    async def no(*a):
        asked.append(1)
        return '{"under_18": "no"}'
    assert asyncio.run(under_18("chef", None, no)) is False and asked == [1]   # a no is asked once
