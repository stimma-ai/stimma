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


async def test_prompt_at_length_makes_no_call(generation_app, generation_db_session, monkeypatch):
    requests = _fake_improve(monkeypatch, ["never used"])
    prompt = "a young woman " + " ".join(["word"] * 120)
    outcome = {}
    out = await pp.run_prompt_pipeline(
        _db(generation_db_session), prompt, LATE, model="flux1-dev", fixed_spans=[WOMAN], level="expand",
        outcome=outcome)
    assert requests == [] and out == prompt
    assert outcome == {"improved": "skipped", "target": [80, 120, "words"]}


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
