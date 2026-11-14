"""The built-in vocabulary draws as it did before kinds became data: for a panel of slot readings,
the narrowed plan, the writer's seeds and its turn text are compared with a snapshot taken from the
code before the change (tests/fixtures/fluent_kinds_golden.json). Narrowing is faked
deterministically, so the snapshot covers what code decides from data, not what a model answers.

Regenerate only on purpose: FLUENT_KINDS_GOLDEN=write uv run pytest tests/test_prompt_program_kinds_equivalence.py
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from pathlib import Path
from typing import Any, Dict, List

import pytest

GOLDEN = Path(__file__).parent / "fixtures" / "fluent_kinds_golden.json"


def _person(**kw: Any) -> Dict[str, Any]:
    base = {"noun": "person", "presentation": "", "stated": {}, "vary": ["age", "descent", "build", "hair", "hair_texture", "hair_color"],
            "outfit": "person.outfit.casual"}
    return {**base, **kw}


# (id, prompt, words, reading's kind, its fields, the default place)
PANEL: List[Any] = [
    ("chef", "a <chef> in a kitchen", "chef", "person", _person(noun="chef"), "US"),
    ("young_woman", "a <young woman> in a kitchen at night", "young woman", "person",
     _person(noun="woman", presentation="feminine", stated={"age": "young"}), None),
    ("elder", "an <elderly African man> reading on a porch", "elderly African man", "person",
     _person(noun="man", presentation="masculine", stated={"age": "elderly", "descent": "African"},
             vary=["age", "descent", "build", "hair", "hair_texture", "hair_color", "facial_hair"]), "US"),
    ("farmer", "a <farmer> in rural Vietnam", "farmer", "person",
     _person(noun="farmer", outfit="person.outfit.casual", place="Vietnam"), "US"),
    ("couple", "a <couple> at a restaurant", "couple", "person", _person(noun="couple", people="couple"), "US"),
    ("family", "a <family> at the beach", "family", "person", _person(noun="family", people="family"), "US"),
    ("friends", "<three friends> waiting at a bus stop", "three friends", "person",
     _person(noun="friends", people="group"), "US"),
    ("elf", "an <elf> in a forest", "elf", "person", _person(noun="elf", being="other"), "US"),
    ("worn", "a <dancer> in a <costume>", "dancer", "person",
     _person(noun="dancer", outfit="", clothes_part={"n": 2, "words": "costume"}), None),
    ("clothes", "a <nurse> in green scrubs", "nurse", "person",
     _person(noun="nurse", outfit="", clothes="in green scrubs", vary=["age", "descent", "hair", "hairstyle"]), None),
    ("pet", "a man on a porch with his <pet>", "pet", "animal",
     {"noun": "pet", "vary": ["species", "life_stage"], "type": "pet", "breed": "", "stated": {}}, None),
    ("dog", "a <dog> on a porch", "dog", "animal",
     {"noun": "dog", "vary": ["breed", "life_stage"], "breed": "animal.dog_breed", "stated": {}}, None),
    ("camera", "a farmer in a field, <camera>", "camera", "camera", {"vary": ["shot_size", "lens", "angle", "film_look"]}, None),
    ("light", "a couple at a restaurant, lit by <light>", "light", "light", {"list": ""}, None),
    ("studio", "a portrait, <studio lighting>", "studio lighting", "light", {"list": "lighting.studio"}, None),
    ("hairstyle", "1girl, <hairstyle>, beach", "hairstyle", "list",
     {"list": "person.hairstyle", "about": "the girl's hairstyle", "presentation": "feminine"}, None),
    ("angle", "a dog on a porch, <camera angle>", "camera angle", "list", {"list": "camera.angle", "about": "the camera angle"}, None),
    ("car", "a <sports car> on a mountain road", "sports car", "free",
     {"about": "a sports car", "lists": ["vehicle.road_vehicle", "object.color"]}, None),
]


def _old_reading(kind: str, got: Dict[str, Any]) -> Dict[str, Any]:
    """A panel reading as the code before kinds-as-data took it (heritage true/false)."""
    from prompt_programs import seeding
    got = dict(got)
    if kind == "person" and not hasattr(seeding, "kind_plan"):
        if got.pop("being", "human") != "human":
            got["heritage"] = False
    return got


def _fake_subset(leaf: Any, phrase: str, *a: Any, **k: Any) -> List[str]:
    """A deterministic stand-in for the narrowing question: the age list keeps 18 to 29 for words
    with "young", 70 and over for "elderly", every adult age else; any other list keeps two values
    of three (by place), so narrowing visibly narrows."""
    from prompt_programs.vocab import AGE_LIST
    vals = [v.text for v in leaf.values]
    if leaf.id == AGE_LIST:
        def years(t: str) -> int:
            return int(t.split("-")[0]) if t[:1].isdigit() else -1
        adults = [t for t in vals if years(t) >= 18 and not leaf.value(t).opt_in]
        if "young" in phrase:
            return [t for t in adults if years(t) <= 29]
        if "elderly" in phrase:
            return [t for t in adults if years(t) >= 70]
        return adults
    return [t for i, t in enumerate(vals) if i % 3 != 2]


def snapshot(monkeypatch: Any) -> Dict[str, Any]:
    from prompt_programs import narrow, places, seeding
    from prompt_programs import variants as V

    async def subset(leaf, phrase, *a, **k):
        return _fake_subset(leaf, phrase)
    monkeypatch.setattr(narrow, "subset", subset)
    out: Dict[str, Any] = {}
    for pid, prompt, words, kind, got, home in PANEL:
        monkeypatch.setattr(places, "default_place", lambda home=home: home)
        reading = {"n": 1, "kind": kind, "label": words, "lead": "", "category": "", kind: _old_reading(kind, got)}
        p = seeding.plan(reading, words)
        a = prompt.index("<" + words + ">")
        entry = {"prompt": prompt, "segments": [],
                 "slots": [{"id": "s1", "n": 1, "words": words, "state": "ready", "line": 1}],
                 "readings": {"slots": [reading]}, "lists": []}
        asyncio.run(seeding.narrow_seeds(entry, None, object()))
        record = entry["seeds"]["s1"]
        seeds = seeding.seeds_of(record)
        slot = V.Slot(words=words, prompt=prompt, span=(a, a + len(words) + 2), kind=kind, category="")
        rows = []
        for seed in (1, 2):
            drawn = V.draw_seeds(random.Random(seed), seeds, slot.n, words)
            msgs = V.messages(slot, drawn, seeds)
            rows.append({"lines": [s.line() for s in drawn.specs], "seeds": [s.seeds() for s in drawn.specs],
                         "user": msgs[1]["content"]})
        banks = [{k: v for k, v in b.items() if k in ("role", "list", "phrase", "where", "age", "scene", "narrowed")}
                 for b in record["banks"]]

        def vals(b):
            return [b.list_id, [list(x) for x in b.values]] if b is not None else None
        summary = {"descent": vals(seeds.descent), "gender": vals(seeds.gender), "age": vals(seeds.age),
                   "core": vals(seeds.core), "spread": vals(seeds.spread), "ideas": [vals(b) for b in seeds.ideas],
                   "minor": list(seeds.minor)}
        out[pid] = {"plan": [(b["role"], b["list"], b["phrase"]) for b in p["banks"]], "banks": banks,
                    "place": record.get("place"), "people": record.get("people", ""), "n": slot.n,
                    "descent": list(seeds.descent.values) if seeds.descent is not None else None, "seeds": summary,
                    "person": kind == "person", "draws": rows}
    return out


def _unseeded(user: str) -> str:
    return user.split("\nSeeds, one line per variant:")[0].split("\nSpread the variants across")[0]


def _jsonable(x: Any) -> Any:
    return json.loads(json.dumps(x))


def test_built_in_draws_match_the_snapshot(monkeypatch):
    got = _jsonable(snapshot(monkeypatch))
    if os.environ.get("FLUENT_KINDS_GOLDEN") == "write":
        GOLDEN.write_text(json.dumps(got, ensure_ascii=False, indent=1) + "\n")
        pytest.skip("snapshot written")
    want = json.loads(GOLDEN.read_text())
    assert sorted(got) == sorted(want)
    for pid in want:
        for field in ("plan", "banks", "people", "n", "descent"):
            assert got[pid][field] == want[pid][field], (pid, field)
        # A place context weights a heritage; a slot that draws none (a group, an elf) has none now,
        # so its pool no longer changes with the default place it never used.
        assert got[pid]["place"] == (want[pid]["place"] if want[pid]["descent"] is not None else None), pid
        assert got[pid]["seeds"] == want[pid]["seeds"], pid
        for g, w in zip(got[pid]["draws"], want[pid]["draws"]):
            if want[pid]["person"]:   # drawn from the same random stream: the very same seed lines
                assert g["lines"] == w["lines"], pid
                assert g["seeds"] == w["seeds"], pid
                assert g["user"] == w["user"], pid
            else:
                # The code before shuffled a person's aspects for every slot, so a slot of another
                # kind drew its ideas from a later point of the random stream: the same banks
                # (above) and the same turn text besides the seed lines, drawn afresh.
                assert _unseeded(g["user"]) == _unseeded(w["user"]), pid
