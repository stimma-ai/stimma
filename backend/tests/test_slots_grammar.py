"""The slot grammar, against the case file the frontend tests read too."""

import json
from pathlib import Path

import pytest

import prompt_pipeline as pp
from prompt_programs.slots import find_slots, parse, unwrap_slots

CASES = json.loads((Path(__file__).parent / "../../frontend/src/utils/slotGrammar.cases.json").read_text("utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["text"][:40] for c in CASES])
def test_case_file(case):
    assert [list(s) for s in find_slots(case["text"])] == case["slots"]


def test_parse_cuts_the_prompt_in_order():
    prompt = "# she visits him\nan <elderly African man> on a porch, {summer|autumn} evening, with his <pet>"
    parsed = parse(prompt)
    assert "".join(s.text for s in parsed.segments) == prompt
    assert [s.kind for s in parsed.segments] == ["comment", "text", "slot", "text", "list", "text", "slot"]
    first, pet = parsed.slots()
    assert first.words == "elderly African man" and first.line == 2
    assert prompt[first.span[0]:first.span[1]] == "<elderly African man>"
    assert pet.words == "pet"
    assert parsed.lists()[0].items == ["summer", "autumn"]
    assert parsed.varies()
    assert not parse("a plain prompt\n# with a <note>").varies()


def test_unwrap_leaves_what_is_not_a_slot():
    assert unwrap_slots("a <young man> [x <y z>] {<a b>|c} <d>hi</d>") == "a young man [x <y z>] {<a b>|c} <d>hi</d>"


def test_final_prompt_uses_a_slot_as_written():
    assert pp.process_final_prompt("dorm room with a <young man>, <d>hi</d> <lora:x:0.8>") == (
        "dorm room with a young man, <d>hi</d> <lora:x:0.8>")
    assert pp.process_final_prompt("[a <b c> d] and <e f>") == "a <b c> d and e f"
