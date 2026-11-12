"""A chat model that declines a prompt: it answers in prose instead of writing the program.

Told apart from the other failures by the shape of its replies (no tool call, no code block,
twice in a row before anything was written), never their words. A declined prompt isn't
retried and is remembered under its program key: its runs go out as written, and only
edited words, other settings or another chat model ask again.
"""

import asyncio

import pytest

from llm import FinishReason
from prompt_programs import fallback
from prompt_programs import prepare as prep
from prompt_programs import session as ses
from tests.test_prompt_program_session import (BAD, EDITED, GOOD, PROMPT, Cfg, _down, _route_client, _submit,  # noqa: F401
                                               ensure, model, reply, write)

NO = "I can't help with this request."


def prose(text=NO, finish=FinishReason.STOP):
    return reply(content=text, finish=finish)


@pytest.fixture
def tools(model):
    """The endpoint is known to make tool calls (it has before, in this process)."""
    prep._PROTOCOL[prep._endpoint_id(Cfg())] = "tools"
    return model


class TestWhatCountsAsDeclining:
    async def test_prose_twice_before_writing_is_declined_after_two_calls(self, tools):
        tools.replies = [prose(), prose("I won't write this one.")]
        with pytest.raises(prep.PrepareDeclined) as e:
            await ensure()
        assert len(tools.seen) == 2  # not the whole allowance
        assert "can't help" in e.value.reply and "won't" in e.value.reply  # for the log, never the user
        assert e.value.code == "prepare_declined" and "can't help" not in str(e.value)

    async def test_prose_once_then_a_write_is_a_program(self, tools):
        tools.replies = [prose("Let me think about the picks first."), reply(write(GOOD))]
        entry = await ensure()
        assert entry["program"] == GOOD and entry["session_stats"]["no_tool"] == 1

    async def test_prose_after_a_write_is_not_declining(self, tools):
        tools.replies = [reply(write(BAD)), prose(), prose(), prose()]
        with pytest.raises(prep.PrepareFailed):
            await ensure()
        assert len(tools.seen) == ses.MAX_CALLS

    @pytest.mark.parametrize("second", [
        prose("", FinishReason.STOP),                               # an empty reply
        prose("Here is the start of a very long", FinishReason.LENGTH),  # cut off at the cap
        prose("Sure:\n```python\nemit('A woman')\n```"),            # a program written as text
    ], ids=["empty", "cut-off", "code-block"])
    def test_other_replies_without_a_tool_call_keep_todays_behavior(self, tools, second):
        tools.replies = [prose(), second, prose(), prose()]
        with pytest.raises(prep.PrepareFailed):
            asyncio.run(ensure())
        assert len(tools.seen) == ses.MAX_CALLS

    async def test_an_endpoint_not_yet_known_to_make_tool_calls_is_never_declining(self, model):
        # Prose from a model never seen making a tool call may be a model that can't: today's failure.
        model.replies = [prose() for _ in range(ses.MAX_CALLS)]
        with pytest.raises(prep.PrepareFailed):
            await ensure()
        assert len(model.seen) == ses.MAX_CALLS

    async def test_an_edit_the_writer_declines_is_declined(self, tools):
        tools.replies = [reply(write(GOOD))]
        first = await ensure()
        tools.replies = [prose(), prose()]
        with pytest.raises(prep.PrepareDeclined):
            await ensure(EDITED, base_key=first["key"])
        assert len(tools.seen) == 3


class TestRemembered:
    async def test_the_same_prompt_isnt_asked_again(self, tools):
        tools.replies = [prose(), prose()]
        with pytest.raises(prep.PrepareDeclined):
            await ensure()
        with pytest.raises(prep.PrepareDeclined):
            await ensure()
        assert len(tools.seen) == 2 and not prep._failures  # nothing retried in the background

    async def test_a_restart_remembers_it(self, tools, monkeypatch):
        tools.replies = [prose(), prose()]
        with pytest.raises(prep.PrepareDeclined):
            await ensure()
        monkeypatch.setattr(prep, "_in_flight", {})
        monkeypatch.setattr(prep, "_failures", {})
        with pytest.raises(prep.PrepareDeclined):
            await ensure()
        assert len(tools.seen) == 2

    async def test_a_lookup_from_the_cache_finds_no_program(self, tools):
        tools.replies = [prose(), prose()]
        with pytest.raises(prep.PrepareDeclined):
            await ensure()
        assert await ensure(cache_only=True) is None
        with pytest.raises(prep.PrepareDeclined):  # the editor's lookup is told
            await ensure(cache_only=True, tell_declined=True)
        assert len(tools.seen) == 2

    async def test_edited_words_ask_afresh(self, tools):
        tools.replies = [prose(), prose()]
        with pytest.raises(prep.PrepareDeclined):
            await ensure()
        tools.replies = [reply(write(GOOD_EVENING := GOOD.replace("morning", "evening")))]
        assert (await ensure(EDITED))["program"] == GOOD_EVENING

    async def test_another_chat_model_asks_afresh(self, tools, monkeypatch):
        tools.replies = [prose(), prose()]
        with pytest.raises(prep.PrepareDeclined):
            await ensure()

        class Other(Cfg):
            def get_model(self):
                return "another-writer"

        async def other(project_id):
            return Other(), "tools"
        monkeypatch.setattr(prep, "_writer_endpoint", other)
        tools.replies = [reply(write(GOOD))]
        assert (await ensure())["program"] == GOOD

    async def test_try_again_asks_anyway(self, tools):
        tools.replies = [prose(), prose()]
        with pytest.raises(prep.PrepareDeclined):
            await ensure()
        tools.replies = [reply(write(GOOD))]
        assert (await ensure(force=True))["program"] == GOOD
        assert (await ensure())["program"] == GOOD  # the program now, not the old answer

    async def test_a_background_retry_that_is_declined_stops(self, tools, monkeypatch):
        monkeypatch.setattr(prep, "RETRY_DELAYS", (0.01, 0.01, 0.01))
        tools.replies = [_down(), prose(), prose()]
        await _submit()  # failed: retried in the background
        task = next(iter(prep._failures.values())).task
        await asyncio.wait_for(task, 5)
        assert not prep._failures and len(tools.seen) == 3  # one retry, declined, no more
        with pytest.raises(prep.PrepareDeclined):
            await ensure()


class TestRunsGoOutAsWritten:
    async def test_a_run_uses_the_words_and_says_why(self, tools):
        tools.replies = [prose(), prose()]
        record, prompt = await _submit()
        assert record["fallback"]["rung"] == "words" and record["fallback"]["code"] == "prepare_declined"
        assert prompt == PROMPT and record["key"] is None and not record["draws"]
        assert NO not in record["fallback"].get("message", "")
        again, _ = await _submit()
        assert again["fallback"]["code"] == "prepare_declined" and len(tools.seen) == 2

    async def test_never_an_earlier_program_for_the_same_words(self, tools):
        tools.replies = [reply(write(GOOD))]
        await ensure(enhance="off")
        tools.replies = [prose(), prose()]
        record, prompt = await _submit(enhance="expand")
        assert record["fallback"]["rung"] == "words" and prompt == PROMPT

    def test_the_agent_is_told_plainly(self):
        note = fallback.agent_note(fallback.fallback_note("words", "prepare_declined"))
        assert "declined" in note and "as written" in note
        assert "background" not in note and "prepare" not in note.lower() and "program" not in note.lower()
