"""A person's face: Face > part > values (fill.face_parts), and how often a drawn face shows
something distinctive (a scar, a birthmark, vitiligo, a prominent mark or a strongly unusual
feature). What counts as distinctive is the vocabulary's own tag (`distinctive`), read from the
values drawn; nothing here reads their words."""

from typing import Any, Dict, Optional

import pytest

from prompt_programs.fill import fill
from prompt_programs.fluent import pool_options, runtime_for
from prompt_programs.narrow import facet_only
from prompt_programs.slots import compose, parse
from prompt_programs.vocab import vocabulary

PROMPT = "A <young woman> in a kitchen"
READING = {"n": 1, "kind": "person", "label": "Young woman", "lead": "",
           "person": {"noun": "woman", "presentation": "feminine", "stated": {"age": "young"},
                      "vary": ["age", "descent", "build", "hair", "hair_color"], "outfit": "person.outfit.casual"}}
FACE = "young_woman.face"
DRAWS = 2000
LIMIT = 0.025


def entry() -> Dict[str, Any]:
    """As prepare leaves it: the age narrowed by "young", the face by her presentation (a facet
    filter, as narrow.py applies it)."""
    e = compose(parse(PROMPT), {1: READING})
    face = vocabulary().get("person.face")
    e["key"] = "face-test"
    e["filters"] = {"young_woman.age": [f"{a}-year-old" for a in range(20, 36)],
                    FACE: facet_only(face, [v.text for v in face.matching({"presentation": "feminine"})])}
    return e


@pytest.fixture(scope="module")
def e():
    return entry()


def parts_of(e) -> list:
    return [c["id"] for c in e["choices"] if c.get("part_of") == FACE]


def draws(e, n: int, pins=None, edits: Optional[Dict[str, Any]] = None):
    rt = runtime_for(e, store=None, mine={}, edits=edits)
    for s in range(n):
        yield fill(e, s, pins, None, edits, options=rt.options)


def shown_values(r):
    """(list id, value) of each face value this draw shows: the face's own piece, or its parts'."""
    v = vocabulary()
    out = []
    for d in r.draws:
        if d.value is None or d.hidden or not (d.id == FACE or d.id.startswith(FACE + ".")):
            continue
        out.append((d.cls, d.value))
    for cls, value in out:
        assert v.get(cls).value(value) is not None, (cls, value)
    return out


def distinctive(r) -> bool:
    v = vocabulary()
    return any(v.get(cls).value(value).distinctive for cls, value in shown_values(r))


def test_a_face_is_its_parts_each_bound_to_its_own_list(e):
    face = vocabulary().get("person.face")
    parts = [c for c in e["choices"] if c.get("part_of") == FACE]
    assert [c["cls"] for c in parts] == list(face.parts) == [f"person.feature.{p}" for p in face.local_facets["piece"]]
    assert all(c["starts_off"] and c["slot"] == "young_woman" for c in parts)
    labels = [c["label"] for c in parts]
    assert labels[:2] == ["Face shape", "Eye shape"] and len(set(labels)) == 12
    # A part offers its list: "nothing notable" first, then its subtle values; marked ones only once picked.
    nose = next(c for c in parts if c["cls"] == "person.feature.nose")
    leaf = vocabulary().get("person.feature.nose")
    assert nose["options"][0] == leaf.plain and not any(leaf.value(o).marked for o in nose["options"])
    # Untouched, the face and its parts add nothing.
    for r in draws(e, 20):
        assert not shown_values(r)


def test_choosing_values_in_parts_puts_those_in_in_the_faces_order(e):
    v = vocabulary()
    nose = next(x.text for x in v.get("person.feature.nose").values if x.marked)
    eyes = next(x.text for x in v.get("person.feature.eyes").values if not x.marked and x.text != v.get("person.feature.eyes").plain)
    for r in draws(e, 5, pins={f"{FACE}.nose": [nose], f"{FACE}.eyes": [eyes]}):
        got = {d.id: d.value for d in r.draws}
        assert FACE not in got   # the face is its parts: it draws no piece of its own
        assert got[f"{FACE}.nose"] == nose and got[f"{FACE}.eyes"] == eyes
        assert f"{eyes}, {nose}" in r.prompt
    # The parts' own records are what an image keeps; a value kept from an older image goes in beside them.
    kept = next(x.text for x in v.get("person.face").values if x.tags["piece"] == ["lips"] and not x.opt_in)
    r = next(draws(e, 1, pins={FACE: [kept], f"{FACE}.nose": [nose]}))
    assert {d.id: d.value for d in r.draws}[FACE] == kept and f"{kept}, {nose}" in r.prompt


def test_a_part_on_any_mostly_says_nothing_and_never_a_marked_piece(e):
    v = vocabulary()
    edits = {p: {"on": True} for p in parts_of(e)}
    plain = {p: 0 for p in parts_of(e)}
    n = 300
    for r in draws(e, n, edits=edits):
        for d in r.draws:
            if d.id in plain:
                leaf = v.get(d.cls)
                assert not leaf.value(d.value).marked, d.value
                if d.value == leaf.plain:   # nothing notable: no words, nothing to keep
                    plain[d.id] += 1
                    assert d.hidden and d.value not in r.prompt
                else:
                    assert d.value in r.prompt
    assert all(k / n > 0.5 for k in plain.values()), plain


def test_nothing_notable_picked_is_written(e):
    leaf = vocabulary().get("person.feature.skin_marks")
    r = next(draws(e, 1, pins={f"{FACE}.skin_marks": [leaf.plain]}))
    assert leaf.plain in r.prompt


def test_a_face_left_out_leaves_its_parts_out(e):
    nose = vocabulary().get("person.feature.nose").values[1].text
    r = next(draws(e, 1, pins={f"{FACE}.nose": [nose]}, edits={FACE: {"off": True}}))
    assert not shown_values(r) and nose not in r.prompt


def test_a_facet_filter_lets_no_marked_piece_in():
    face = vocabulary().get("person.face")
    matched = [v.text for v in face.matching({"presentation": "feminine"})]
    got = facet_only(face, matched)
    assert got and any(face.value(t).marked for t in matched) and not any(face.value(t).marked for t in got)


def test_distinctive_pieces_are_marked_or_rare():
    for lid, leaf in vocabulary().leaves.items():
        for x in leaf.values:
            if x.distinctive:
                assert lid.startswith("person.feature.") or lid == "person.face", (lid, x.text)
                assert x.marked or x.tier == "unusual", (lid, x.text)


@pytest.mark.parametrize("how", ["face on, nothing chosen", "every part on Any"])
def test_few_faces_show_something_distinctive(e, how):
    """About 2,000 people, seeded: at most 2.5% show a scar, birthmark, vitiligo, a prominent mark
    or a strongly unusual feature, with the face turned on and nothing chosen, and with every part
    on "Any"."""
    edits = {FACE: {"on": True}} if how.startswith("face") else {p: {"on": True} for p in parts_of(e)}
    seen = hits = 0
    for r in draws(e, DRAWS, edits=edits):
        seen += bool(shown_values(r))
        hits += distinctive(r)
    assert seen > DRAWS * 0.9   # the face says something most of the time
    assert hits / DRAWS <= LIMIT, f"{how}: {hits / DRAWS:.2%} distinctive"


def test_the_pools_send_each_part_with_its_groups_and_short_forms(e):
    got = pool_options(e, store=None, mine={})
    nose = f"{FACE}.nose"
    leaf = vocabulary().get("person.feature.nose")
    assert got["options"][nose][0] == leaf.plain
    pool = got["vocab"][nose]
    assert pool["cls"] == leaf.id and pool["short"][leaf.plain] == "nothing notable"
    # The part's own groups are its chips; "nothing notable" is an option, not a group.
    assert list(pool["groups"]) == ["aspect"] and "plain" not in pool["groups"]["aspect"]
    assert {o for o, t in pool["tiers"].items() if t == "opt_in"} == {x.text for x in leaf.values if x.marked}


def test_a_judges_reroll_keeps_nothing_notable_unsaid(e):
    """The fix loop holds every pick it doesn't reroll as `fixed`; a part that said nothing
    notable stays unsaid and unjudged, while the user's pick of it is written."""
    from prompt_programs.fix import fix_draw
    v = vocabulary()
    edits = {p: {"on": True} for p in parts_of(e)}
    rt = runtime_for(e, store=None, mine={}, edits=edits)

    def redraw(seed, fixed, ed):
        return fill(e, seed, None, fixed, ed, options=rt.options)

    class Scorer:   # flags the build, so every other pick is held while it is rerolled
        version, reroll_all = "stub", False

        def __init__(self):
            self.items = []

        def p_wrong(self, items):
            self.items += items
            return [0.9 if it.label == "Build" else 0.0 for it in items]

    r = redraw(4, None, edits)
    quiet = [d for d in r.draws if d.hidden and d.id in edits]
    assert quiet
    judge = Scorer()
    out, rec = fix_draw(r, judge=judge, redraw=redraw, seed=4, user_prompt=PROMPT, cut=0.5, edits=edits)
    assert rec["rerolls"] >= 1
    for d in quiet:
        got = next(x for x in out.draws if x.id == d.id)
        assert got.hidden and got.value == d.value and d.value not in out.prompt
    assert not any(it.value == v.get(d.cls).plain for it in judge.items for d in quiet)
