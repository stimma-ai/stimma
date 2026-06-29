"""Regression tests for strip_thinking_tags orphan-tag handling.

A reasoning model can stream the `<think>` opener to the thinking channel and
leak a bare `</think>` closer into the content channel (or vice-versa). The
paired/nested handling never catches a lone tag, so it used to surface in the
visible assistant message (see the celestial-photos transcript)."""

from llm import strip_thinking_tags


def test_orphan_closing_tag_is_removed():
    assert "</think>" not in strip_thinking_tags("Done.</think>Found it — ComfyUI.")


def test_orphan_opening_tag_is_removed():
    assert "<think>" not in strip_thinking_tags("<think>reasoning leaked here")


def test_well_formed_pair_still_stripped():
    assert strip_thinking_tags("before<think>hidden</think>after") == "beforeafter"


def test_plain_text_untouched():
    assert strip_thinking_tags("just a normal message") == "just a normal message"


def test_all_known_tag_variants():
    for tag in ("think", "thinking", "thought", "analysis", "reasoning"):
        assert strip_thinking_tags(f"visible</{tag}>") == "visible"
