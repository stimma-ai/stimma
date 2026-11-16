"""Suggest (prompt_programs/suggest.py), with a fake model: what code keeps of a reply (vary
phrases, looks, adds), the cache, the retry, exact text kept from the model, and the route."""

import json

import httpx
import pytest
from fastapi import FastAPI

from prompt_programs import suggest as sg
from prompt_programs.narrow import NarrowCache


class Fake:
    """A model that gives its replies in turn and records what it was asked."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.max_tokens = []

    async def __call__(self, messages, project_id, max_tokens):
        self.calls.append(messages)
        self.max_tokens.append(max_tokens)
        reply = self.replies.pop(0)
        return reply if isinstance(reply, str) else json.dumps(reply)


def reply(*phrases, looks=(), adds=(), shot_stated=False):
    return {"vary": [{"phrase": p, "label": f"different {p}"} for p in phrases], "medium": "photo",
            "shot_stated": shot_stated,
            "looks": [{"text": t, "label": t.split(",")[0]} for t in looks],
            "adds": [{"text": t, "label": t.split()[-1]} for t in adds]}


FARMER = "a farmer in rural Vietnam"
LOOKS = ["candid documentary photo, wide shot, soft morning mist",
         "cinematic film still, low angle, golden hour backlight",
         "natural portrait, 85mm lens, overcast daylight"]
EMPTY = {"vary": [], "looks": [], "adds": []}


# --------------------------------------------------------------------------- vary

class TestVary:
    async def test_offsets_are_the_phrases_with_their_labels(self):
        ask = Fake(reply("rural Vietnam", "farmer"))
        got = await sg.suggest(FARMER, ask)
        assert [(v["text"], v["label"]) for v in got["vary"]] == [
            ("farmer", "different farmer"), ("rural Vietnam", "different rural Vietnam")]   # prompt order
        for v in got["vary"]:
            assert FARMER[v["from"]:v["to"]] == v["text"]
        assert ask.calls[0][0]["role"] == "system" and FARMER in ask.calls[0][1]["content"]
        assert ask.max_tokens == [sg.SUGGEST_TOKENS]

    async def test_what_is_dropped(self):
        prompt = ("# keep the <cat> as he is\n"
                  "a <young man> with a cat, [exact red scarf] and a {blue|green} hat, {{mood}}, under a tree")
        phrases = ["hidden lamp",        # not in the prompt
                   "keep",               # only on the comment line
                   "young man",          # inside a slot
                   "red scarf",          # inside verbatim
                   "blue",               # inside a list
                   "mood",               # inside a name
                   "ca",                 # part of a word
                   "cat", "a tree"]
        got = await sg.suggest(prompt, Fake(reply(*phrases)))
        assert [(v["text"], prompt[v["from"]:v["to"]]) for v in got["vary"]] == [("cat", "cat"), ("a tree", "a tree")]
        assert got["vary"][0]["from"] > prompt.index("\n")  # the cat in the text, not the comment's

    async def test_overlaps_and_the_whole_prompt_are_dropped(self):
        got = await sg.suggest("# a note\nred bicycle by a tree", Fake(reply("red bicycle by a tree", "bicycle", "red bicycle", "tree")))
        assert [v["text"] for v in got["vary"]] == ["bicycle", "tree"]

    async def test_at_most_three_and_a_bare_string_or_bad_label_is_kept_as_its_words(self):
        prompt = "a fox, a hare, an owl, a stoat"
        got = await sg.suggest(prompt, Fake({"vary": ["fox", {"phrase": "hare", "label": "<hares>"}, "owl", "stoat"]}))
        assert [(v["text"], v["label"]) for v in got["vary"]] == [("fox", "fox"), ("hare", "hare"), ("owl", "owl")]
        assert sg.MAX_VARY == 3

    async def test_each_phrase_says_whether_it_is_varied_or_fleshed_out(self):
        prompt = "a farmer at the Eiffel Tower with a dog"
        got = await sg.suggest(prompt, Fake({"vary": [
            {"phrase": "farmer", "how": "vary", "label": "different farmers"},
            {"phrase": "Eiffel Tower", "how": "one", "label": "more of the Eiffel Tower"},
            {"phrase": "dog", "how": "something else"}]}))
        assert [(v["text"], v["mode"]) for v in got["vary"]] == [("farmer", "kind"), ("Eiffel Tower", "one"), ("dog", "kind")]
        assert '"one"' in sg.SUGGEST_SYSTEM and '"how"' in sg.SUGGEST_SYSTEM


# --------------------------------------------------------------------------- looks and adds

class TestLooksAndAdds:
    async def test_three_looks_and_two_adds_as_fixed_words(self):
        got = await sg.suggest(FARMER, Fake(reply(looks=LOOKS + ["one more look, wide, soft light"],
                                                  adds=["carrying a heavy bamboo basket", "walking through a rice paddy",
                                                        "a water buffalo nearby"])))
        assert [l["text"] for l in got["looks"]] == LOOKS
        assert got["looks"][0]["label"] == "candid documentary photo"
        assert [a["text"] for a in got["adds"]] == ["carrying a heavy bamboo basket", "walking through a rice paddy"]
        assert set(got["looks"][0]) == {"text", "label"} and set(got["adds"][0]) == {"text", "label"}

    async def test_no_looks_when_the_shot_is_stated(self):
        got = await sg.suggest(FARMER, Fake(reply(looks=LOOKS, adds=["carrying a bamboo basket"], shot_stated=True)))
        assert got["looks"] == [] and [a["text"] for a in got["adds"]] == ["carrying a bamboo basket"]

    @pytest.mark.parametrize("bad", [
        "with a <hat>", "in [EXACT_1] light", "a {red|blue} sky", "a | b c", "# note words", "two\nlines here",
        "short", " ".join(["word"] * 30),
    ])
    async def test_fixed_words_hold_no_marks_and_fit_the_length(self, bad):
        got = await sg.suggest(FARMER, Fake({"looks": [{"text": bad, "label": "x"}], "adds": [{"text": bad, "label": "x"}]}))
        assert got["looks"] == [] and got["adds"] == []

    async def test_words_already_in_the_prompt_add_nothing(self):
        prompt = "a farmer in rural Vietnam, carrying a bamboo basket"
        got = await sg.suggest(prompt, Fake(reply(adds=["carrying a bamboo basket", "steam rising from the paddy"])))
        assert [a["text"] for a in got["adds"]] == ["steam rising from the paddy"]

    async def test_a_trailing_period_and_a_missing_label(self):
        got = await sg.suggest(FARMER, Fake({"adds": [{"text": "a water buffalo nearby."}]}))
        assert got["adds"] == [{"text": "a water buffalo nearby", "label": "a water buffalo nearby"}]

    @pytest.mark.parametrize("junk", [{"vary": 3, "looks": "x", "adds": None}, {"looks": [1, None, {"text": 4}]}, {}])
    async def test_a_bad_reply_gives_nothing_quietly(self, junk):
        assert await sg.suggest(FARMER, Fake(junk)) == EMPTY


# --------------------------------------------------------------------------- the call

class TestCall:
    async def test_cache_makes_one_call(self, tmp_path):
        cache = NarrowCache(tmp_path)
        ask = Fake(reply("farmer", looks=LOOKS))
        first = await sg.suggest(FARMER, ask, cache, model="m")
        assert await sg.suggest(FARMER, ask, cache, model="m") == first
        assert len(ask.calls) == 1
        await sg.suggest(FARMER + " ", Fake(reply("farmer")), cache, model="m")   # another prompt, even by a space
        assert len(list(tmp_path.rglob("*.json"))) == 2

    async def test_an_old_versions_cache_entry_is_not_read(self, tmp_path, monkeypatch):
        cache = NarrowCache(tmp_path)
        monkeypatch.setattr(sg, "SUGGEST_VERSION", "suggest-4")
        cache.put_raw(sg.suggest_key(FARMER, "m"), {"vary": [], "adds": [{"name": "light"}]})
        monkeypatch.undo()
        got = await sg.suggest(FARMER, Fake(reply("farmer")), cache, model="m")
        assert [v["text"] for v in got["vary"]] == ["farmer"]

    async def test_empty_and_raw_make_no_call(self):
        ask = Fake()
        for prompt in ("", "   \n ", "# only a note"):
            assert await sg.suggest(prompt, ask) == EMPTY
        assert await sg.suggest(FARMER, ask, raw=True) == EMPTY
        assert ask.calls == []

    async def test_unreadable_reply_is_retried_once_and_not_cached(self, tmp_path):
        cache = NarrowCache(tmp_path)
        ask = Fake("sure! here you go", reply("farmer"))
        got = await sg.suggest(FARMER, ask, cache)
        assert [v["text"] for v in got["vary"]] == ["farmer"] and len(ask.calls) == 2
        assert "JSON" in ask.calls[1][-1]["content"]
        ask = Fake("no", "still no")
        assert await sg.suggest("a cat", ask, cache) == EMPTY
        assert len(ask.calls) == 2 and len(list(tmp_path.rglob("*.json"))) == 1

    async def test_the_parts_that_already_vary_are_named(self):
        ask = Fake(reply())
        await sg.suggest("a <farmer> in rural Vietnam at <time of day>", ask)
        assert "Already changing from picture to picture: <farmer>, <time of day>." in ask.calls[0][1]["content"]
        ask = Fake(reply())
        await sg.suggest(FARMER, ask)
        assert "Already changing" not in ask.calls[0][1]["content"]

    def test_the_prompt_says_square_brackets_are_hidden(self):
        assert "never copy them, never touch them" in sg.SUGGEST_SYSTEM
        for gone in ("joins", "stated", "insert"):
            assert f'"{gone}"' not in sg.SUGGEST_SYSTEM


# --------------------------------------------------------------------------- the route

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
        ask = Fake(reply("farmer", looks=LOOKS[:1], adds=["carrying a bamboo basket"]))
        monkeypatch.setattr(sg, "ask_model", ask)
        async with client as c:
            r = await c.post("/api/prompt-programs/suggest", json={"prompt": FARMER, "project_id": 3})
            assert r.status_code == 200
            assert r.json() == {"vary": [{"from": 2, "to": 8, "text": "farmer", "label": "different farmer", "mode": "kind"}],
                                "looks": [{"text": LOOKS[0], "label": "candid documentary photo"}],
                                "adds": [{"text": "carrying a bamboo basket", "label": "basket"}]}
            again = await c.post("/api/prompt-programs/suggest", json={"prompt": FARMER})
            assert again.json() == r.json() and len(ask.calls) == 1
            assert (await c.post("/api/prompt-programs/suggest", json={"prompt": FARMER, "raw": True})).json() == EMPTY
        assert list((tmp_path / "a" / "prompt_programs" / "suggest").rglob("*.json"))

    async def test_add_is_gone(self, client):
        async with client as c:
            r = await c.post("/api/prompt-programs/add", json={"prompt": "a cat", "name": "light"})
            assert r.status_code in (404, 405)


# --------------------------------------------------------------------------- exact text stays private

class TestExactTextIsNeverSent:
    SECRET = "Jane Q. Example, 12 Elm St"

    def sent(self, ask):
        return json.dumps(ask.calls, ensure_ascii=False)

    async def test_suggest_sends_a_token_not_the_text(self):
        prompt = f"a woman holding a sign that reads [{self.SECRET}] in a park"
        ask = Fake(reply("woman", "park"))
        got = await sg.suggest(prompt, ask)
        assert self.SECRET not in self.sent(ask) and "[EXACT_1]" in self.sent(ask)
        for v in got["vary"]:   # offsets still index the prompt as typed
            assert prompt[v["from"]:v["to"]] == v["text"]

    async def test_nor_with_slots_nor_on_the_retry(self):
        prompt = f"a <woman> holding a sign that reads [{self.SECRET}] at <place>"
        ask = Fake("not json", reply())
        await sg.suggest(prompt, ask)
        assert len(ask.calls) == 2
        assert self.SECRET not in self.sent(ask) and "[EXACT_1]" in self.sent(ask)
        assert "Already changing from picture to picture: <woman>, <place>." in ask.calls[0][1]["content"]

    async def test_a_reply_naming_the_token_is_dropped(self):
        prompt = f"a sign that reads [{self.SECRET}] in a park"
        got = await sg.suggest(prompt, Fake({"vary": [{"phrase": "[EXACT_1]"}, {"phrase": "EXACT_1"}],
                                             "looks": [{"text": "close-up of [EXACT_1], soft daylight, shallow focus"}],
                                             "adds": [{"text": "a bench beside EXACT_1 sign"}]}))
        assert got["vary"] == [] and got["looks"] == []
        assert all("[" not in a["text"] for a in got["adds"])
