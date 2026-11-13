"""Suggest and Add (prompt_programs/suggest.py), with a fake model: what code keeps of a
suggestion reply, the cache, Add's checks, retry and plain fallback, and the routes."""

import json

import httpx
import pytest
from fastapi import FastAPI

from prompt_programs import suggest as sg
from prompt_programs.narrow import NarrowCache
from prompt_programs.slots import find_slots


class Fake:
    """A model that gives its replies in turn and records what it was asked."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    async def __call__(self, messages, project_id, max_tokens):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        return reply if isinstance(reply, str) else json.dumps(reply)


def vary(*texts, adds=()):
    return {"vary": list(texts), "adds": [{"name": a, "label": a} for a in adds]}


DORM = "dorm room with a young man in a denim jacket, reading"


# --------------------------------------------------------------------------- suggest

class TestSuggest:
    async def test_offsets_are_the_phrases(self):
        ask = Fake(vary("young man", "denim jacket", "dorm room", adds=["light", "camera"]))
        got = await sg.suggest(DORM, ask)
        assert [v["text"] for v in got["vary"]] == ["dorm room", "young man", "denim jacket"]  # in prompt order
        for v in got["vary"]:
            assert DORM[v["from"]:v["to"]] == v["text"]
        assert got["adds"] == [{"name": "light", "label": "light"}, {"name": "camera", "label": "camera"}]
        assert ask.calls[0][0]["role"] == "system" and DORM in ask.calls[0][1]["content"]

    async def test_what_is_dropped(self):
        prompt = ("# keep the <cat> as he is\n"
                  "a <young man> with a cat, [exact red scarf] and a {blue|green} hat, {{mood}}, under a tree")
        ask = Fake(vary("hidden lamp",        # not in the prompt
                        "keep",               # only on the comment line
                        "young man",          # inside a slot
                        "red scarf",          # inside verbatim
                        "blue",               # inside a list
                        "mood",               # inside a name
                        "a tree", "under a",  # overlaps the phrase before it
                        "ca",                 # part of a word
                        "cat"))
        got = await sg.suggest(prompt, ask)
        assert [(v["text"], prompt[v["from"]:v["to"]]) for v in got["vary"]] == [("cat", "cat"), ("a tree", "a tree")]
        assert got["vary"][0]["from"] > prompt.index("\n")  # the cat in the text, not the comment's

    async def test_the_whole_prompt_is_not_a_phrase(self):
        got = await sg.suggest("# a note\nred bicycle", Fake(vary("red bicycle", "bicycle")))
        assert [v["text"] for v in got["vary"]] == ["bicycle"]

    async def test_caps(self):
        words = [f"thing{i}" for i in range(10)]
        prompt = ", ".join(words)
        got = await sg.suggest(prompt, Fake(vary(*words, adds=["light", "camera", "weather", "season", "lens"])))
        assert [v["text"] for v in got["vary"]] == words[:sg.MAX_VARY]
        assert [a["name"] for a in got["adds"]] == ["light", "camera", "weather"]

    async def test_adds_are_checked(self):
        prompt = "a <young man> at the beach"
        ask = Fake({"vary": ["beach"], "adds": [{"name": "young man"}, {"name": "beach"}, {"name": "a:b"}, {"name": "x"},
                                                {"name": "time of day", "label": "time"}, "light", {"name": "Light"}]})
        got = await sg.suggest(prompt, ask)
        assert got["adds"] == [{"name": "time of day", "label": "time"}, {"name": "light", "label": "light"}]

    async def test_cache_makes_one_call(self, tmp_path):
        cache = NarrowCache(tmp_path)
        ask = Fake(vary("young man"))
        first = await sg.suggest(DORM, ask, cache, model="m")
        assert await sg.suggest(DORM, ask, cache, model="m") == first
        assert len(ask.calls) == 1
        # another prompt, even by a space, is asked again
        await sg.suggest(DORM + " ", Fake(vary("young man")), cache, model="m")
        assert len(list(tmp_path.rglob("*.json"))) == 2

    async def test_empty_and_raw_make_no_call(self):
        ask = Fake()
        for prompt in ("", "   \n ", "# only a note"):
            assert await sg.suggest(prompt, ask) == {"vary": [], "adds": []}
        assert await sg.suggest(DORM, ask, raw=True) == {"vary": [], "adds": []}
        assert ask.calls == []

    async def test_unreadable_reply_is_retried_once_and_not_cached(self, tmp_path):
        cache = NarrowCache(tmp_path)
        ask = Fake("sure! here you go", vary("young man"))
        got = await sg.suggest(DORM, ask, cache)
        assert [v["text"] for v in got["vary"]] == ["young man"] and len(ask.calls) == 2
        assert "JSON" in ask.calls[1][-1]["content"]
        ask = Fake("no", "still no")
        assert await sg.suggest("a cat", ask, cache) == {"vary": [], "adds": []}
        assert len(ask.calls) == 2 and len(list(tmp_path.rglob("*.json"))) == 1


# --------------------------------------------------------------------------- add

class TestAdd:
    async def test_a_good_reply(self):
        prompt = "dorm room with a <young man>"
        written = "dorm room with a <young man>, lit by <light>"
        ask = Fake({"prompt": written})
        got = await sg.add(prompt, "light", ask)
        assert got["prompt"] == written
        assert written[got["slot"]["from"]:got["slot"]["to"]] == "<light>"
        assert len(ask.calls) == 1 and "<light>" in ask.calls[0][1]["content"]

    async def test_trimmed_ends_are_put_back(self):
        prompt = "1girl, solo, smiling\n"
        got = await sg.add(prompt, "light", Fake({"prompt": "1girl, solo, smiling, <light>"}))
        assert got["prompt"] == "1girl, solo, smiling, <light>\n"
        assert got["prompt"][got["slot"]["from"]:got["slot"]["to"]] == "<light>"

    async def test_an_altered_slot_is_retried(self):
        prompt = "dorm room with a <young man>"
        written = "dorm room with a <young man>, lit by <light>"
        ask = Fake({"prompt": "dorm room with a <man>, lit by <light>"}, {"prompt": written})
        got = await sg.add(prompt, "light", ask)
        assert got["prompt"] == written and len(ask.calls) == 2
        assert "<young man>" in ask.calls[1][-1]["content"]

    @pytest.mark.parametrize("bad", [
        "not json",
        {"prompt": "dorm room with a <young man>"},                             # nothing new
        {"prompt": "dorm room with a <young man>, <light> and <camera>"},      # two new
        {"prompt": "dorm room with a <young man>, lit by <warm light>"},       # other words
        {"prompt": "a dorm room with a <young man>, lit by <light>"},          # changed the text
        {"prompt": "dorm room with a <young man>, {lit|shaded} by <light>"},   # a new list too
    ])
    async def test_falls_back_after_two_bad_replies(self, bad):
        prompt = "dorm room with a <young man>"
        ask = Fake(bad, bad)
        got = await sg.add(prompt, "light", ask)
        assert got["prompt"] == "dorm room with a <young man>, <light>" and len(ask.calls) == 2
        assert got["prompt"][got["slot"]["from"]:got["slot"]["to"]] == "<light>"

    async def test_words_joined_by_only_a_comma_are_asked_again_once(self):
        """A reply that says the prompt is written in words but adds a bare tag is asked once more
        to join it with words; a second bare one, or a tag prompt, is kept as written."""
        prompt = "dorm room with a young man"
        bare = {"form": "words", "prompt": "dorm room with a young man, <light>"}
        joined = {"form": "words", "prompt": "dorm room with a young man, lit by <light>"}
        ask = Fake(bare, joined)
        assert (await sg.add(prompt, "light", ask))["prompt"] == joined["prompt"] and len(ask.calls) == 2
        assert 'joined with only ","' in ask.calls[1][-1]["content"]
        ask = Fake(bare, bare)
        assert (await sg.add(prompt, "light", ask))["prompt"] == bare["prompt"] and len(ask.calls) == 2
        ask = Fake(bare, "not json")
        assert (await sg.add(prompt, "light", ask))["prompt"] == bare["prompt"]
        tags = {"form": "tags", "prompt": "1girl, long hair, <light>"}
        ask = Fake(tags)
        assert (await sg.add("1girl, long hair", "light", ask))["prompt"] == tags["prompt"] and len(ask.calls) == 1

    def test_the_add_prompt_asks_for_the_form_first(self):
        assert '"form": "words"' in sg.ADD_SYSTEM and "even when it is short" in sg.ADD_SYSTEM

    async def test_a_comment_line_after_the_text_stays_last(self):
        prompt = "dorm room with a <young man>.\n# keep it calm"
        moved = {"prompt": "# keep it calm\ndorm room with a <young man>, lit by <light>."}
        got = await sg.add(prompt, "light", Fake(moved, moved))
        assert got["prompt"] == "dorm room with a <young man>., <light>\n# keep it calm"
        assert got["prompt"][got["slot"]["from"]:got["slot"]["to"]] == "<light>"
        written = "dorm room with a <young man>, lit by <light>.\n# keep it calm"
        got = await sg.add(prompt, "light", Fake({"prompt": written}))
        assert got["prompt"] == written and got["prompt"].endswith("\n# keep it calm")

    async def test_a_comment_line_is_not_written_on(self):
        prompt = "a cat\n# soft colors"
        bad = {"prompt": "a cat\n# soft colors, <light>"}
        got = await sg.add(prompt, "light", Fake(bad, bad))
        assert got["prompt"] == "a cat, <light>\n# soft colors"

    async def test_no_text_makes_no_call(self):
        ask = Fake()
        assert await sg.add("", "light", ask) == {"prompt": "<light>", "slot": {"from": 0, "to": 7}}
        got = await sg.add("# a note", "pet", ask)
        assert got["prompt"] == "# a note\n<pet>" and find_slots(got["prompt"]) == [(9, 14)]
        assert ask.calls == []

    def test_check_added_says_what_is_wrong(self):
        before = "a {red|blue} car on [Main Street] with a <driver>"
        span, problem = sg.check_added(before, "a {red|blue} car on [Main St] with a <driver>, <light>", "light")
        assert span is None and "[Main Street]" in problem
        span, problem = sg.check_added(before, before + " at <time of day>", "time of day")
        assert problem == "" and (before + " at <time of day>")[span[0]:span[1]] == "<time of day>"


# --------------------------------------------------------------------------- the routes

@pytest.fixture
def client(tmp_path, monkeypatch):
    import app_dirs
    from routes import prompt_programs as route
    monkeypatch.setattr(app_dirs, "get_profile_dir", lambda pid="default": tmp_path / str(pid))
    monkeypatch.setattr(route, "get_current_profile", lambda: "a")

    async def no_model(project_id):
        return "fake"
    monkeypatch.setattr(sg, "model_name", no_model)
    app = FastAPI()
    app.include_router(route.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class TestRoutes:
    async def test_suggest(self, client, monkeypatch, tmp_path):
        ask = Fake(vary("young man", adds=["light"]))
        monkeypatch.setattr(sg, "ask_model", ask)
        async with client as c:
            r = await c.post("/api/prompt-programs/suggest", json={"prompt": DORM, "project_id": 3})
            assert r.status_code == 200
            assert r.json() == {"vary": [{"from": 17, "to": 26, "text": "young man"}],
                                "adds": [{"name": "light", "label": "light"}]}
            again = await c.post("/api/prompt-programs/suggest", json={"prompt": DORM})
            assert again.json() == r.json() and len(ask.calls) == 1
            assert (await c.post("/api/prompt-programs/suggest", json={"prompt": DORM, "raw": True})).json() == {
                "vary": [], "adds": []}
        assert list((tmp_path / "a" / "prompt_programs" / "suggest").rglob("*.json"))

    async def test_add(self, client, monkeypatch):
        monkeypatch.setattr(sg, "ask_model", Fake({"prompt": "dorm room with a <young man>, lit by <light>"}))
        async with client as c:
            r = await c.post("/api/prompt-programs/add", json={"prompt": "dorm room with a <young man>", "name": "light"})
            assert r.status_code == 200
            assert r.json() == {"prompt": "dorm room with a <young man>, lit by <light>", "slot": {"from": 37, "to": 44}}
            r = await c.post("/api/prompt-programs/add", json={"prompt": "a cat", "name": "a:b"})
            assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_slot"
