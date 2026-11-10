"""How long a prepare keeps the user waiting: the readings after the writer run side by side
where they don't depend on each other, and a run stops waiting for its prepare well before
the prepare's own deadline (the prepare carries on, and later runs use its program)."""

import asyncio
import json
import re

from prompt_programs.narrow import NarrowCache, narrow_entry
from prompt_programs.runtime import discover


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
