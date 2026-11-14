"""Fixed values (a slot's drawn value) survive the per-image improver exactly, or the
prompt goes unimproved."""
from types import SimpleNamespace

import prompt_pipeline as pp

PROMPT = "a young woman reading in a laundromat at night"
WOMAN = (2, 13, "person-1")  # "young woman"
LATE = {"autoImprove": {"enabled": True, "instructions": ""}}


def _db(session_factory):
    return SimpleNamespace(async_session_maker=session_factory)


def _fake_improve(monkeypatch, answers):
    """Answer each improve call in turn; an answer may be a function of the request."""
    import routes.prompt_enhancement as pe

    requests = []

    async def fake_improve(request, session):
        requests.append(request)
        answer = answers[min(len(requests), len(answers)) - 1]
        text = answer(request) if callable(answer) else answer
        return pe.ImprovePromptResponse(improved_prompt=text)

    monkeypatch.setattr(pe, "improve_prompt", fake_improve)
    return requests


def test_mark_values_wraps_each_span():
    assert pp.mark_values(PROMPT, [WOMAN]) == "a ⟦young woman⟧ reading in a laundromat at night"
    assert pp.mark_values("ab cd", [(3, 5), (0, 2)]) == "⟦ab⟧ ⟦cd⟧"
    # Overlapping, empty and out-of-range spans are left alone.
    assert pp.mark_values("ab cd", [(0, 2), (1, 4), (3, 3), (4, 9)]) == "⟦ab⟧ cd"


def test_spans_of_marks_finds_values_again():
    text, spans = pp.spans_of_marks("a ⟦red⟧ hat on a ⟦young woman⟧")
    assert text == "a red hat on a young woman"
    assert [text[s:e] for s, e in spans] == ["red", "young woman"]


def test_verify_and_unmark_needs_every_value_exactly():
    values = ["young woman", "35mm"]
    good = "A ⟦young woman⟧ reads, shot on ⟦35mm⟧ film."
    assert pp.verify_and_unmark(good, values) == "A young woman reads, shot on 35mm film."
    assert pp.verify_and_unmark("A ⟦young girl⟧ reads, shot on ⟦35mm⟧ film.", values) is None
    # A value copied exactly with its marks dropped is still a good answer.
    assert pp.verify_and_unmark("A young woman reads, shot on ⟦35mm⟧ film.", values) == "A young woman reads, shot on 35mm film."
    assert pp.verify_and_unmark("A young woman reads, shot on film.", values) is None
    # A value inside a longer word is not the value: the build "short" is gone here.
    assert pp.verify_and_unmark("A woman in denim shorts.", ["short"]) is None
    assert pp.verify_and_unmark("A short woman in denim shorts.", ["short"]) == "A short woman in denim shorts."
    assert pp.verify_and_unmark("A ⟦Young woman⟧ reads on ⟦35mm⟧.", values) is None



def test_a_value_that_opens_a_sentence_may_come_back_capitalized():
    # Overnight, four of eight <grandmother> images lost Improve to these: the value was copied
    # whole, only with a sentence's capital, or with its article just outside the marks.
    values = ["grandmother", "her pet tabby cat", "the dim blue light from a television screen"]
    got = pp.verify_and_unmark(
        "A 1990s snapshot of a small apartment. A ⟦grandmother⟧ sits on a sofa with ⟦her pet tabby cat⟧. "
        "⟦The dim blue light from a television screen⟧ shines on a coffee table.", values)
    assert got is not None and "The dim blue light from a television screen shines" in got
    assert pp.verify_and_unmark(
        "A ⟦grandmother⟧ holds ⟦her pet tabby cat⟧. The ⟦dim blue light from a television screen⟧ hangs above.", values)
    assert pp.verify_and_unmark(
        "An ⟦eye-level shot from the dog's perspective⟧ shows a beagle.", ["an eye-level shot from the dog's perspective"])
    # mid-sentence a capital is still a change, and so are other words
    assert pp.verify_and_unmark("She sits by ⟦The dim blue light from a television screen⟧.", values[2:]) is None
    assert pp.verify_and_unmark("An eye-level shot from the perspective of a beagle.",
                                ["an eye-level shot from the dog's perspective"]) is None


async def test_correct_answer_comes_back_without_marks(generation_app, generation_db_session, monkeypatch):
    requests = _fake_improve(monkeypatch, [lambda r: r.prompt + ", lit by a flickering tube light"])
    outcome = {}
    out = await pp.run_prompt_pipeline(
        _db(generation_db_session), PROMPT, LATE, model="krea2_turbo", fixed_spans=[WOMAN], level="fill",
        outcome=outcome)
    assert requests[0].prompt == "a ⟦young woman⟧ reading in a laundromat at night"
    assert requests[0].marked and requests[0].level == "fill"
    assert out == PROMPT + ", lit by a flickering tube light"
    assert outcome == {"improved": "true", "target": [50, 80, "words"]}


async def test_altered_value_retries_with_a_hint(generation_app, generation_db_session, monkeypatch):
    requests = _fake_improve(monkeypatch, [
        "a ⟦young girl⟧ reading in a laundromat",
        "a ⟦young woman⟧ reading under a fluorescent strip in a laundromat at night",
    ])
    outcome = {}
    out = await pp.run_prompt_pipeline(
        _db(generation_db_session), PROMPT, LATE, model="krea2_turbo", fixed_spans=[WOMAN], level="expand",
        outcome=outcome)
    assert len(requests) == 2
    assert requests[0].instructions is None
    assert "⟦young woman⟧" in requests[1].instructions
    assert out == "a young woman reading under a fluorescent strip in a laundromat at night"
    assert outcome["improved"] == "true"


async def test_value_altered_twice_sends_the_prompt_unimproved(generation_app, generation_db_session, monkeypatch):
    requests = _fake_improve(monkeypatch, ["an old man reading in a laundromat"])
    outcome = {}
    out = await pp.run_prompt_pipeline(
        _db(generation_db_session), PROMPT + "\n# keep it dim", LATE, model="flux1-dev", fixed_spans=[WOMAN],
        level="expand", outcome=outcome)
    assert len(requests) == 2
    assert out == PROMPT
    assert outcome["improved"] == "fallback" and "fixed value" in outcome["reason"]


async def test_verbatim_text_still_round_trips_beside_marks(generation_app, generation_db_session, monkeypatch):
    prompt = "poster reading [OPEN LATE] with a young woman"
    span = (prompt.index("young woman"), prompt.index("young woman") + len("young woman"), "p")
    requests = _fake_improve(monkeypatch, [lambda r: "A neon " + r.prompt + " in the doorway"])
    out = await pp.run_prompt_pipeline(
        _db(generation_db_session), prompt, LATE, model="flux1-dev", fixed_spans=[span], level="expand")
    assert requests[0].prompt == "poster reading __VERBATIM_A__ with a ⟦young woman⟧"
    assert out == "A neon poster reading OPEN LATE with a young woman in the doorway"


async def test_spans_follow_their_values_through_wildcards(generation_app, generation_db_session, monkeypatch):
    prompt = "a {red|red} hat on a young woman"
    span = (prompt.index("young woman"), len(prompt), "p")
    requests = _fake_improve(monkeypatch, [lambda r: r.prompt + " at a bus stop"])
    out = await pp.run_prompt_pipeline(
        _db(generation_db_session), prompt, LATE, model="flux1-dev", fixed_spans=[span], level="expand")
    assert requests[0].prompt == "a red hat on a ⟦young woman⟧"
    assert out == "a red hat on a young woman at a bus stop"


async def test_long_prompt_is_still_improved(generation_app, generation_db_session, monkeypatch):
    requests = _fake_improve(monkeypatch, [lambda r: r.prompt + ", at a bus stop"])
    prompt = "a young woman " + " ".join(["word"] * 120)
    outcome = {}
    out = await pp.run_prompt_pipeline(
        _db(generation_db_session), prompt, LATE, model="flux1-dev", fixed_spans=[WOMAN], level="expand",
        outcome=outcome)
    assert len(requests) == 1 and out == prompt + ", at a bus stop"
    assert outcome["improved"] == "true"


async def test_unchanged_answer_is_kept_on_the_late_path(generation_app, generation_db_session, monkeypatch):
    requests = _fake_improve(monkeypatch, [lambda r: r.prompt])
    out = await pp.run_prompt_pipeline(
        _db(generation_db_session), PROMPT, LATE, model="sdxl", fixed_spans=[WOMAN], level="expand")
    assert len(requests) == 1 and out == PROMPT


async def test_classic_improve_sends_no_level_and_no_marks(generation_app, generation_db_session, monkeypatch):
    requests = _fake_improve(monkeypatch, [lambda r: r.prompt + ", at dusk"])
    out = await pp.run_prompt_pipeline(_db(generation_db_session), PROMPT, LATE, model="flux1-dev")
    assert requests[0].level is None and not requests[0].marked and requests[0].prompt == PROMPT
    assert out == PROMPT + ", at dusk"


def test_preload_may_equal_its_input_only_on_the_late_path():
    preload = {"originalPrompt": "a cat", "promptSourcesSignature": "s", "processedPrompt": "a cat",
               "improvedPrompt": "a cat"}
    args = dict(prompt="a cat", instructions=None, model=None, is_video=False, is_audio=False,
                input_image_count=0, audio_conditioned=False, source_signature="s")
    assert pp._validated_prompt_preload(preload, **args) is None
    assert pp._validated_prompt_preload(preload, **args, level="fill") == "a cat"


def test_a_doubled_article_before_a_value_is_written_once():
    out = pp.verify_and_unmark("A ⟦a 31-year-old⟧ man waits. Beside him, a ⟦a red hat⟧ rests.", ["a 31-year-old", "a red hat"])
    assert out == "A 31-year-old man waits. Beside him, a red hat rests."


async def test_a_failing_per_image_improver_sends_the_prompt_as_filled(generation_app, generation_db_session, monkeypatch):
    import routes.prompt_enhancement as pe
    from fastapi import HTTPException

    async def empty(request, session):
        raise HTTPException(status_code=502, detail={"code": "prompt_enhancement_failed", "message": "empty"})
    monkeypatch.setattr(pe, "improve_prompt", empty)
    outcome = {}
    out = await pp.run_prompt_pipeline(
        _db(generation_db_session), PROMPT + "\n# keep it dim", LATE, model="flux1-dev", fixed_spans=[WOMAN],
        level="fill", outcome=outcome)
    assert out == PROMPT
    assert outcome["improved"] == "fallback" and outcome["reason"]


async def test_three_empty_answers_send_the_prompt_as_filled(generation_app, generation_db_session, monkeypatch):
    requests = _fake_improve(monkeypatch, ["   "])
    outcome = {}
    out = await pp.run_prompt_pipeline(
        _db(generation_db_session), PROMPT, LATE, model="flux1-dev", fixed_spans=[WOMAN], level="expand",
        outcome=outcome)
    assert len(requests) == 3 and out == PROMPT and outcome["improved"] == "fallback"


async def test_classic_improve_still_fails_the_generation(generation_app, generation_db_session, monkeypatch):
    import pytest
    from fastapi import HTTPException

    _fake_improve(monkeypatch, ["   "])
    with pytest.raises(HTTPException):
        await pp.run_prompt_pipeline(_db(generation_db_session), PROMPT, LATE, model="flux1-dev")
