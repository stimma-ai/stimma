"""How long a prepare keeps the user waiting: the readings after the writer run side by side
where they don't depend on each other, and a run stops waiting for its prepare well before
the prepare's own deadline (the prepare carries on, and later runs use its program)."""

import asyncio
import json
import re

import pytest

from prompt_programs import prepare as prep
from prompt_programs.narrow import NarrowCache, narrow_entry
from prompt_programs.runtime import discover
from tests.test_prompt_program_session import GOOD, PROMPT, _submit, ensure, model, reply, write  # noqa: F401


def entry_of(src, prompt):
    return {"key": "k", "program": src, "loras": [], "params": {}, "mode": "prose", "prompt": prompt,
            "choices": discover(src)["choices"]}


class TimedAsk:
    """Answers like a model following the instructions, each call taking `delay` seconds;
    records (kind, phrase, start, end) per call."""

    def __init__(self, read=None, keep=None, delay=0.05):
        self.read, self.keep, self.delay, self.calls = read or {}, keep or {}, delay, []

    async def __call__(self, messages, project_id, max_tokens):
        loop = asyncio.get_running_loop()
        start = loop.time()
        await asyncio.sleep(self.delay)
        if "find the words in it" in messages[0]["content"]:
            self.calls.append(("read", "", start, loop.time()))
            return json.dumps(self.read)
        values = json.loads(re.search(r"\n(\[.*?\])\n", messages[1]["content"], re.S).group(1))
        phrase = re.search(r'Which of these fit "(.*?)"', messages[1]["content"]).group(1)
        self.calls.append(("subset", phrase, start, loop.time()))
        keep = self.keep.get(phrase)
        return json.dumps([v for v in values if keep is None or v in keep])

    def of(self, phrase):
        return [c for c in self.calls if c[1] == phrase]


EYES = ('eyes = pick("eyes", cls="person.eye_color", about="her eye colour", seed=["brown"], label="Eyes", phase=1, line=1)\n'
        'emit("A Japanese woman with", eyes, "eyes")')


class TestReadingsSideBySide:
    async def test_the_stated_descent_is_narrowed_beside_the_picks_own_words(self, tmp_path):
        e = entry_of(EYES, "a Japanese woman with brown eyes")
        ask = TimedAsk(read={"stated_ethnicity": "Japanese woman", "eyes": "brown eyes"},
                       keep={"Japanese woman": ["Japanese"]})
        await narrow_entry(e, NarrowCache(tmp_path), ask)
        (_, _, eyes_start, eyes_end), = ask.of("brown eyes")
        (_, _, ctx_start, _), = ask.of("Japanese woman")
        assert ctx_start < eyes_end  # not after it
        assert e["stated_context"] == [{"of": "", "cls": "person.ethnicity", "values": ["Japanese"]}]
        assert "eyes" in e["filters"]

    async def test_a_users_list_values_are_narrowed_while_the_prompt_is_read(self, tmp_path):
        src = ('who = pick("who", ["Japanese", "in a red coat"], source="list", label="Who", phase=1, line=1)\n'
               'eyes = pick("eyes", cls="person.eye_color", about="her eye colour", seed=["brown"], label="Eyes", phase=1, line=2)\n'
               'emit("A", who, "woman with", eyes, "eyes")')
        e = entry_of(src, "a {Japanese|in a red coat} woman")
        ask = TimedAsk(keep={"Japanese": ["Japanese"]})
        await narrow_entry(e, NarrowCache(tmp_path), ask)
        (_, _, _, read_end), = [c for c in ask.calls if c[0] == "read"]
        listed = ask.of("Japanese")
        assert listed and all(start < read_end for _, _, start, _ in listed)
        assert len(listed) == len({(p, s) for _, p, s, _ in listed})  # each asked once
        assert e["list_context"] == {"who": {"Japanese": {"person.ethnicity": ["Japanese"]}}}

    async def test_a_reading_that_runs_out_of_time_leaves_its_picks_pending(self, tmp_path):
        slow = TimedAsk(read={"stated_ethnicity": "Japanese woman", "eyes": "brown eyes"}, delay=1.5)
        e = entry_of(EYES, "a Japanese woman with brown eyes")
        await narrow_entry(e, NarrowCache(tmp_path), slow, seconds=0.2)
        assert "eyes" in e["narrow_pending"] and "stated_context" not in e


# --------------------------------------------------------------------------- how long a run waits

@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(prep, "_took", {})
    monkeypatch.setattr(prep, "_overdue", set())
    monkeypatch.setattr(prep, "RETRY_DELAYS", (60.0,))  # not during these tests


class TestRunWait:
    def test_the_wait_follows_the_writers_recent_prepares(self, fresh):
        assert prep.run_wait("w") == prep.RUN_WAIT_SECONDS  # no history yet
        for s in (2.0, 3.0, 2.5, 4.0, 3.5):
            prep._note_took("w", s)
        assert prep.run_wait("w") == prep.RUN_WAIT_MIN_SECONDS  # a fast writer: the floor
        for s in (32.0,) * 5:
            prep._note_took("slow", s)
        assert prep.run_wait("slow") == prep.prepare_limit()  # a slow one keeps the whole deadline
        for s in (12.0, 14.0, 13.0, 16.0, 15.0):
            prep._note_took("mid", s)
        assert prep.run_wait("mid") == pytest.approx(24.0)
        for _ in range(30):
            prep._note_took("w", 2.0)
        assert len(prep._took["w"]) == prep._TOOK_KEPT

    async def test_a_run_goes_ahead_and_the_prepare_lands_for_the_next(self, model, fresh, monkeypatch):
        monkeypatch.setattr(prep, "RUN_WAIT_SECONDS", 0.2)
        gate = asyncio.Event()

        async def slow():
            await gate.wait()
            return reply(write(GOOD))
        model.replies = [slow]
        first, prompt = await _submit()
        assert first["fallback"]["rung"] == "words" and first["fallback"]["code"] == "prepare_timeout"
        assert prompt == PROMPT
        second, _ = await _submit()  # a lane's next image: no second wait on the same prepare
        assert second["fallback"]["rung"] == "words"
        assert len(model.seen) == 1  # one prepare, still running
        gate.set()
        for _ in range(100):
            if not prep._in_flight:
                break
            await asyncio.sleep(0.01)
        assert not prep._overdue and not prep._failures
        third, _ = await _submit()
        assert "fallback" not in third and third["draws"]
        assert len(model.seen) == 1
        assert list(prep._took.values()) and all(len(v) == 1 for v in prep._took.values())

    async def test_the_editor_waits_the_whole_prepare(self, model, fresh, monkeypatch):
        monkeypatch.setattr(prep, "RUN_WAIT_SECONDS", 0.05)

        async def slow():
            await asyncio.sleep(0.2)
            return reply(write(GOOD))
        model.replies = [slow]
        assert (await ensure())["program"] == GOOD
