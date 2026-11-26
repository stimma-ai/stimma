"""ELEMENT.md block conditionals: grammar, wildcard pass-through, variables, malformed input."""

import pytest

from elements.template import check, referenced_vars, render, strip_blocks


def test_plain_text_and_wildcards_pass_through():
    src = "A {{wildcard}} and {{segment:hair}} and {{ #ifx }} stay.\n{{/notablock}}"
    out = render(src, {})
    assert out.valid and out.text == src
    assert out.referenced_vars == frozenset()


def test_if_else_picks_branch_and_eats_tag_lines():
    src = "Top\n{{#if lora_active}}\nLoRA on\n{{else}}\nDescribe face\n{{/if}}\nBottom\n"
    assert render(src, {"lora_active": True}).text == "Top\nLoRA on\nBottom"
    assert render(src, {"lora_active": False}).text == "Top\nDescribe face\nBottom"


def test_elif_chain_and_first_match_wins():
    src = (
        "{{#if model_family == \"flux\"}}F{{#elif model_family == \"qwen\"}}Q"
        "{{#elif model_family in [\"sdxl\", \"sd15\"]}}S{{else}}D{{/if}}"
    )
    assert render(src, {"model_family": "flux"}).text == "F"
    assert render(src, {"model_family": "qwen"}).text == "Q"
    assert render(src, {"model_family": "sd15"}).text == "S"
    assert render(src, {"model_family": "veo"}).text == "D"


def test_unless_and_else():
    src = "{{#unless surface == 'chat'}}not chat{{else}}chat{{/unless}}"
    assert render(src, {"surface": "chat"}).text == "chat"
    assert render(src, {"surface": "enhance"}).text == "not chat"


@pytest.mark.parametrize("expr,ctx,expected", [
    ("a and b", {"a": True, "b": False}, False),
    ("a or b", {"a": False, "b": True}, True),
    ("not a", {"a": False}, True),
    ("not (a or b)", {"a": False, "b": False}, True),
    ("a and (b or c)", {"a": True, "b": False, "c": True}, True),
    ("n > 2", {"n": 3}, True),
    ("n >= 3", {"n": 3}, True),
    ("n < 3.5", {"n": 3}, True),
    ("n <= 2", {"n": 3}, False),
    ("n != 3", {"n": 3}, False),
    ("x not in ['a', 'b']", {"x": "c"}, True),
    ("x in ['a', 'b']", {"x": "a"}, True),
    ("flag == true", {"flag": True}, True),
    ("flag == false", {"flag": True}, False),
    ("ratio == \"16:9\"", {"ratio": "16:9"}, True),
    ("'land' in orientation", {"orientation": "landscape"}, True),
    ("n > -1", {"n": 0}, True),
])
def test_expressions(expr, ctx, expected):
    out = render("{{#if " + expr + "}}yes{{else}}no{{/if}}", ctx)
    assert out.valid, out.warnings
    assert out.text == ("yes" if expected else "no")


def test_unknown_variable_is_false_with_one_warning():
    out = render("{{#if mood == 'x'}}a{{/if}}{{#if mood}}b{{/if}}", {})
    assert out.valid and out.text == ""
    assert out.warnings == ["unknown variable 'mood' (treated as false)"]


def test_standard_variables_left_unset_do_not_warn():
    out = render("{{#if model_family == 'flux' and lora_active}}a{{else}}b{{/if}}", {"surface": "chat"})
    assert out.text == "b" and out.warnings == []


def test_mismatched_comparison_is_false_and_warns():
    out = render("{{#if n > 'x'}}a{{else}}b{{/if}}", {"n": 3})
    assert out.text == "b" and out.warnings


def test_referenced_vars_cover_every_branch_and_nesting():
    src = (
        "{{#if model_family == 'flux'}}{{#if aspect_ratio == '16:9'}}wide{{/if}}"
        "{{#elif orientation == 'portrait'}}tall{{else}}{{#unless lora_active}}x{{/unless}}{{/if}}"
        "{{#if n in [limit, 3]}}{{/if}}"
    )
    expected = {"model_family", "aspect_ratio", "orientation", "lora_active", "n", "limit"}
    assert render(src, {"model_family": "flux"}).referenced_vars == expected
    assert referenced_vars(src) == expected


def test_nested_blocks_evaluate():
    src = "{{#if a}}A{{#if b}}B{{else}}b{{/if}}{{/if}}"
    assert render(src, {"a": True, "b": False}).text == "Ab"
    assert render(src, {"a": False, "b": True}).text == ""


def test_blank_lines_collapse():
    src = "One\n\n{{#if a}}\nskipped\n{{/if}}\n\n\nTwo\n"
    assert render(src, {"a": False}).text == "One\n\nTwo"


def test_inline_tags_keep_surrounding_text():
    assert render("Use {{#if a}}trigger{{else}}words{{/if}} here.", {"a": True}).text == "Use trigger here."


def test_wildcards_inside_blocks_survive():
    out = render("{{#if a}}a {{color}} coat{{/if}}", {"a": True})
    assert out.text == "a {{color}} coat"


@pytest.mark.parametrize("src", [
    "{{#if a}}never closed",
    "{{/if}}",
    "{{else}}",
    "{{#if a}}x{{/unless}}",
    "{{#unless a}}x{{#elif b}}y{{/unless}}",
    "{{#if a}}x{{else}}y{{else}}z{{/if}}",
    "{{#if a}}x{{else}}y{{#elif b}}z{{/if}}",
    "{{#if}}x{{/if}}",
    "{{#if a ==}}x{{/if}}",
    "{{#if (a}}x{{/if}}",
    "{{#if a b}}x{{/if}}",
    "{{#if a @ b}}x{{/if}}",
    "{{#if [a, }}x{{/if}}",
])
def test_malformed_keeps_raw_text_with_warning(src):
    out = render(src, {"a": True})
    assert out.valid is False
    assert out.text == src
    assert out.warnings and "template problem" in out.warnings[0]
    assert check(src) is not None


def test_strip_blocks_keeps_every_branch_for_reading():
    src = "# Mira\n\n{{#if lora_active}}\nLoRA owns the face.\n{{else}}\nDescribe the face.\n{{/if}}\n"
    out = strip_blocks(src)
    assert out.valid and out.text == "# Mira\n\nLoRA owns the face.\nDescribe the face."
    assert out.referenced_vars == {"lora_active"}


def test_check_accepts_valid_and_empty():
    assert check("") is None
    assert check("{{#if a}}x{{/if}}") is None
