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
        self.max_tokens = []

    async def __call__(self, messages, project_id, max_tokens):
        self.calls.append(messages)
        self.max_tokens.append(max_tokens)
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


# --------------------------------------------------------------------------- a photo's photography

LIGHT_LISTS = ["lighting.dramatic", "lighting.indoor_practical", "lighting.natural", "lighting.studio"]
PARTS = {  # each photography chip, as it is offered
    "light": {"name": "light", "label": "light", "kind": "light", "lists": LIGHT_LISTS},
    "angle": {"name": "camera angle", "label": "angle", "kind": "list", "lists": ["camera.angle"]},
    "lens": {"name": "lens", "label": "lens", "kind": "list", "lists": ["camera.lens"]},
    "film_look": {"name": "film look", "label": "film look", "kind": "list", "lists": ["camera.film_look"]},
    "shot_size": {"name": "framing", "label": "framing", "kind": "list", "lists": ["camera.shot_size"]},
}
CAMERA = ["angle", "lens", "film_look", "shot_size"]


def photo(*texts, adds=(), is_photo=True, stated=()):
    return {**vary(*texts, adds=adds), "photo": is_photo, "stated": list(stated)}


def names(got):
    return [a["name"] for a in got["adds"]]


def parts(*ids):
    return [PARTS[i]["name"] for i in ids]


class TestPhoto:
    async def test_a_photo_is_sent_every_part_it_lacks_in_order(self):
        """Light, then angle, then lens, then film look, then framing; all of them: the editor
        caps them once it has hidden the ones a slot is read as."""
        got = await sg.suggest(DORM, Fake(photo("young man", adds=["background"])))
        assert got["adds"] == [{"name": "background", "label": "background"}] + [PARTS[p] for p in PARTS]
        assert [v["text"] for v in got["vary"]] == ["young man"]

    async def test_each_part_the_prompt_states_is_hidden_on_its_own(self):
        # "cell phone selfie": the framing and the format, so the angle and the lens are still offered
        got = await sg.suggest(DORM, Fake(photo(stated=["shot_size", "film_look"])))
        assert names(got) == parts("light", "angle", "lens")
        got = await sg.suggest(DORM, Fake(photo(stated=["film_look"])))
        assert names(got) == parts("light", "angle", "lens", "shot_size")
        got = await sg.suggest(DORM, Fake(photo(stated=[" Light ", "angle", "camera"])))  # camera: not a part, skipped
        assert names(got) == parts("lens", "film_look", "shot_size")
        got = await sg.suggest(DORM, Fake(photo(stated=["light", "angle", "lens", "film_look"])))
        assert names(got) == parts("shot_size")
        assert names(await sg.suggest(DORM, Fake(photo(stated=list(PARTS))))) == []

    async def test_a_slot_on_a_part_hides_that_part_only(self):
        prompt = "a <young man> in a dorm room, <camera angle>, shot with <Lens>"
        got = await sg.suggest(prompt, Fake(photo()))
        assert names(got) == parts("light", "film_look", "shot_size")
        got = await sg.suggest("a <young man> in a dorm room, lit by <light>", Fake(photo()))
        assert names(got) == parts(*CAMERA)

    async def test_not_a_photo_offers_none(self):
        got = await sg.suggest(DORM, Fake(photo(adds=["light"], is_photo=False)))
        assert got["adds"] == [{"name": "light", "label": "light"}]  # the model's own, as before

    @pytest.mark.parametrize("fields", [
        {},                                       # neither field
        {"photo": "yes", "stated": []},           # not a boolean
        {"photo": True},                          # stated missing
        {"photo": True, "stated": "light"},       # not a list
        {"photo": True, "stated": ["light", 3]},  # not names
    ])
    async def test_unreadable_fields_offer_none_and_keep_the_rest(self, fields):
        ask = Fake({**vary("young man", adds=["light", "background"]), **fields})
        got = await sg.suggest(DORM, ask)
        assert got["adds"] == [{"name": "light", "label": "light"}, {"name": "background", "label": "background"}]
        assert [v["text"] for v in got["vary"]] == ["young man"] and len(ask.calls) == 1  # no retry for it

    async def test_the_models_photography_adds_give_way(self):
        """For a photo, an add of the same words as a photography part's slot, or the whole
        camera, is left to the vocabulary's chip."""
        got = await sg.suggest(DORM, Fake(photo(adds=["Light", "background", "camera", "lens"])))
        assert names(got) == ["background"] + parts(*PARTS)
        assert all("kind" in a for a in got["adds"][1:])

    async def test_the_models_light_stands_in_for_the_plain_one(self):
        prompt = "an old man reading on a porch"
        reply = {**photo(stated=["film_look"]), "adds": [
            {"name": "weather", "label": "weather"},
            {"name": "golden hour light", "label": "golden hour", "part": "light", "after": "on a porch",
             "insert": " in <golden hour light>"},
            {"name": "dim light", "label": "dim light", "part": "light"},       # one light only
            {"name": "telephoto lens", "label": "telephoto", "part": "lens"},   # the camera is the vocabulary's
            {"name": "season", "label": "season"}, {"name": "sky", "label": "sky"}]}  # two of its own at most
        got = await sg.suggest(prompt, Fake(reply))
        assert got["adds"] == [
            {"name": "weather", "label": "weather"}, {"name": "season", "label": "season"},
            {"name": "golden hour light", "label": "golden hour", "kind": "light", "lists": LIGHT_LISTS,
             "after": "on a porch", "insert": " in <golden hour light>"},
            PARTS["angle"], PARTS["lens"], PARTS["shot_size"]]

    async def test_the_models_light_is_dropped_when_the_light_is_stated(self):
        reply = {**photo(stated=["light"]), "adds": [{"name": "window light", "label": "window light", "part": "light"}]}
        assert names(await sg.suggest(DORM, Fake(reply))) == parts(*CAMERA)

    async def test_a_part_is_only_read_for_a_photo(self):
        reply = {**photo(is_photo=False), "adds": [{"name": "window light", "label": "window light", "part": "light"}]}
        assert (await sg.suggest(DORM, Fake(reply)))["adds"] == [{"name": "window light", "label": "window light"}]

    async def test_only_lists_the_vocabulary_has(self, monkeypatch):
        monkeypatch.setattr(sg, "PHOTO", (sg.Part("lens", "lens", "lens", "list", ("camera.lens", "camera.nope")),
                                          sg.Part("weather", "weather", "weather", "list", ("nature.nope",)),
                                          sg.Part("light", "light", "light", "light", ("lighting",))))
        got = await sg.suggest(DORM, Fake(photo()))
        assert [(a["name"], a["lists"]) for a in got["adds"]] == [("lens", ["camera.lens"]), ("light", LIGHT_LISTS)]

    async def test_the_cache_keeps_the_reply_and_offers_again(self, tmp_path):
        cache = NarrowCache(tmp_path)
        ask = Fake({**photo(stated=["angle"]), "adds": [{"name": "window light", "label": "window", "part": "light"}]})
        first = await sg.suggest(DORM, ask, cache, model="m")
        assert names(first) == ["window light"] + parts("lens", "film_look", "shot_size")
        assert await sg.suggest(DORM, ask, cache, model="m") == first and len(ask.calls) == 1

    def test_the_prompt_asks_for_every_part(self):
        assert '"photo": true' in sg.SUGGEST_SYSTEM and '"stated": ["shot_size"]' in sg.SUGGEST_SYSTEM
        assert '"part": "light"' in sg.SUGGEST_SYSTEM
        for p in sg.PHOTO:
            assert f'"{p.part}"' in sg.SUGGEST_SYSTEM and f"<{p.name}>" in sg.SUGGEST_SYSTEM

    def test_every_part_has_its_lists(self):
        for p in sg.PHOTO:
            assert sg.photo_lists(p.lists), p.part
            assert p.kind in ("light", "list")
        assert [p.part for p in sg.PHOTO] == ["light", "angle", "lens", "film_look", "shot_size"]


class TestJoins:
    async def test_an_adds_join_is_kept_when_it_fits(self):
        prompt = "an old man reading on a porch at dusk"
        got = await sg.suggest(prompt, Fake({"vary": [], "adds": [
            {"name": "weather", "label": "weather", "after": "on a porch", "insert": " in <weather>"},
            {"name": "hat", "label": "hat", "after": "on a deck", "insert": " in a <hat>"},      # not in the prompt
            {"name": "pet", "label": "pet", "after": "at dusk", "insert": ", with a <dog>"},       # other words
            {"name": "sky", "label": "sky"}]}))                                                   # none given
        assert got["adds"] == [{"name": "weather", "label": "weather", "after": "on a porch", "insert": " in <weather>"},
                               {"name": "hat", "label": "hat"}, {"name": "pet", "label": "pet"}]

    async def test_a_photos_joins_go_with_its_parts(self):
        prompt = "an old man reading on a porch at dusk"
        got = await sg.suggest(prompt, Fake({**photo(stated=["light"]), "joins": {
            "angle": {"after": "at dusk", "insert": ", seen from <camera angle>"},
            "lens": {"after": "at dusk", "insert": ", shot with <camera>"},     # the wrong slot: no join
            "camera": {"after": "at dusk", "insert": ", shot on <camera>"}}}))  # not a part
        angle, lens, film, _ = got["adds"]
        assert (angle["after"], angle["insert"]) == ("at dusk", ", seen from <camera angle>")
        assert "after" not in lens and "insert" not in lens and "insert" not in film

    async def test_joins_are_ignored_when_it_is_not_a_photo(self):
        got = await sg.suggest(DORM, Fake({**photo(is_photo=False), "joins": "garbled"}))
        assert got["adds"] == []

    async def test_a_photo_keeps_two_of_its_own(self):
        got = await sg.suggest(DORM, Fake(photo(adds=["weather", "season", "background"])))
        assert names(got) == ["weather", "season"] + parts(*PARTS)
        got = await sg.suggest(DORM, Fake(photo(adds=["weather", "season", "background"], is_photo=False)))
        assert names(got) == ["weather", "season", "background"]


# --------------------------------------------------------------------------- add

class TestSplice:
    """Writing a suggested add in where Suggest said, with no model: code checks only structure."""

    def test_it_writes_the_slot_in_after_the_words(self):
        prompt = "an old man reading on a porch at dusk"
        done, problem = sg.splice(prompt, "light", "on a porch at dusk", ", lit by <light>")
        assert problem == "" and done["prompt"] == "an old man reading on a porch at dusk, lit by <light>"
        assert done["prompt"][done["slot"]["from"]:done["slot"]["to"]] == "<light>"
        done, _ = sg.splice(prompt, "weather", "reading", " in <weather>")
        assert done["prompt"] == "an old man reading in <weather> on a porch at dusk"

    @pytest.mark.parametrize("after,insert,why", [
        ("on a deck", ", <light>", "not in the prompt"),
        ("a", ", <light>", "more than once"),
        ("", ", <light>", "needs"),
        (None, ", <light>", "needs"),
        ("at dusk", ", lit by the sun", "once"),                  # no slot
        ("at dusk", ", <light> and <light>", "once"),             # two
        ("at dusk", ", lit by <warm light>", "once"),             # other words
        ("at dusk", ", <light> {soft|hard}", "brackets"),         # a list too
        ("at dusk", ", <light> [exact]", "brackets"),
        ("at dusk", ",\n<light>", "brackets"),                    # a new line
        ("on a por", "ch, <light>", "inside a word"),
        ("reading", "<light> ", "inside a word"),                  # runs into the word before
        ("reading ", "<light>", "next word"),                      # and into the next
    ])
    def test_what_does_not_fit(self, after, insert, why):
        done, problem = sg.splice("an old man reading on a porch at dusk", "light", after, insert)
        assert done is None and why in problem

    def test_marks_are_kept(self):
        prompt = "a <young man> on a {red|blue} bench\n# keep it calm"
        done, problem = sg.splice(prompt, "light", "keep it", " in <light>")       # on the note line
        assert done is None and problem   # a note line holds no slots
        done, problem = sg.splice(prompt, "light", "<young", " <light>")           # inside a slot
        assert done is None
        done, _ = sg.splice(prompt, "light", "{red|blue} bench", ", lit by <light>")
        assert done["prompt"] == "a <young man> on a {red|blue} bench, lit by <light>\n# keep it calm"


class TestAdd:
    async def test_suggests_join_makes_no_call(self):
        ask = Fake()
        prompt = "dorm room with a <young man>"
        got = await sg.add(prompt, "light", ask, after="<young man>", insert=", lit by <light>", suggested_for=prompt)
        assert got["prompt"] == "dorm room with a <young man>, lit by <light>" and ask.calls == []

    async def test_a_join_that_no_longer_fits_asks_the_model(self):
        prompt = "dorm room with an <old man>"   # the prompt moved on since Suggest
        ask = Fake({"after": "<old man>", "insert": ", lit by <light>"})
        got = await sg.add(prompt, "light", ask, after="<young man>", insert=", lit by <light>",
                           suggested_for="dorm room with a <young man>")
        assert got["prompt"] == "dorm room with an <old man>, lit by <light>" and len(ask.calls) == 1

    async def test_a_join_for_an_edited_prompt_is_not_used_even_when_it_still_fits(self):
        """Suggest answered for "a cat on a porch"; the user then wrote on. The join's words are
        still there, but splicing would land beside what the edit added: the model places it."""
        before, prompt = "a cat on a porch", "a cat on a porch, lit by candlelight"
        ask = Fake({"after": "a cat", "insert": " in <light>"})
        got = await sg.add(prompt, "light", ask, after="on a porch", insert=", lit by <light>", suggested_for=before)
        assert got["prompt"] == "a cat in <light> on a porch, lit by candlelight" and len(ask.calls) == 1
        ask = Fake({"after": "a cat", "insert": " in <light>"})   # no prompt said: not trusted either
        got = await sg.add(prompt, "light", ask, after="on a porch", insert=", lit by <light>")
        assert len(ask.calls) == 1

    async def test_a_good_reply(self):
        prompt = "dorm room with a <young man>"
        ask = Fake({"after": "<young man>", "insert": ", lit by <light>"})
        got = await sg.add(prompt, "light", ask)
        assert got["prompt"] == "dorm room with a <young man>, lit by <light>"
        assert got["prompt"][got["slot"]["from"]:got["slot"]["to"]] == "<light>"
        assert len(ask.calls) == 1 and "<light>" in ask.calls[0][1]["content"]
        assert ask.max_tokens == [sg.ADD_TOKENS] and sg.ADD_TOKENS <= 64

    async def test_a_reply_that_does_not_fit_is_retried_once(self):
        prompt = "dorm room with a <young man>"
        ask = Fake({"after": "<young  man>", "insert": ", lit by <light>"}, {"after": "<young man>", "insert": ", lit by <light>"})
        got = await sg.add(prompt, "light", ask)
        assert got["prompt"] == "dorm room with a <young man>, lit by <light>" and len(ask.calls) == 2
        assert "not in the prompt" in ask.calls[1][-1]["content"]

    @pytest.mark.parametrize("bad", [
        "not json",
        {"prompt": "dorm room with a <young man>, lit by <light>"},     # the old shape
        {"after": "dorm room", "insert": " lit"},                      # nothing new
        {"after": "<young man>", "insert": ", <light> and <camera>"},  # two new
        {"after": "<young man>", "insert": ", lit by <warm light>"},   # other words
    ])
    async def test_falls_back_after_two_bad_replies(self, bad):
        prompt = "dorm room with a <young man>"
        ask = Fake(bad, bad)
        got = await sg.add(prompt, "light", ask)
        assert got["prompt"] == "dorm room with a <young man>, <light>" and len(ask.calls) == 2
        assert got["prompt"][got["slot"]["from"]:got["slot"]["to"]] == "<light>"

    async def test_a_bare_join_is_kept_at_once(self):
        """No second call over how the part is joined: a usable reply is used."""
        ask = Fake({"after": "a young man", "insert": ", <light>"})
        got = await sg.add("dorm room with a young man", "light", ask)
        assert got["prompt"] == "dorm room with a young man, <light>" and len(ask.calls) == 1

    def test_the_add_prompt_asks_for_the_place_only(self):
        assert '{"after": ' in sg.ADD_SYSTEM and '"prompt"' not in sg.ADD_SYSTEM

    async def test_a_comment_line_is_not_written_on(self):
        prompt = "a cat\n# soft colors"
        bad = {"after": "soft colors", "insert": ", <light>"}
        got = await sg.add(prompt, "light", Fake(bad, bad))
        assert got["prompt"] == "a cat, <light>\n# soft colors"
        got = await sg.add(prompt, "light", Fake({"after": "a cat", "insert": " in <light>"}))
        assert got["prompt"] == "a cat in <light>\n# soft colors"

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
            monkeypatch.setattr(sg, "ask_model", Fake(photo(stated=CAMERA)))
            r = await c.post("/api/prompt-programs/suggest", json={"prompt": "a cat on a porch"})
            assert r.json()["adds"] == [PARTS["light"]]
            assert (await c.post("/api/prompt-programs/suggest", json={"prompt": DORM, "raw": True})).json() == {
                "vary": [], "adds": []}
        assert list((tmp_path / "a" / "prompt_programs" / "suggest").rglob("*.json"))

    async def test_add(self, client, monkeypatch):
        monkeypatch.setattr(sg, "ask_model", Fake({"after": "<young man>", "insert": ", lit by <light>"}))
        async with client as c:
            r = await c.post("/api/prompt-programs/add", json={"prompt": "dorm room with a <young man>", "name": "light"})
            assert r.status_code == 200
            assert r.json() == {"prompt": "dorm room with a <young man>, lit by <light>", "slot": {"from": 37, "to": 44}}
            r = await c.post("/api/prompt-programs/add", json={"prompt": "a cat", "name": "a:b"})
            assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_slot"

    async def test_a_fresh_chip_click_calls_no_model(self, client, monkeypatch):
        """Suggest's answer says where each add goes; clicking one sends that back and the
        server splices it in. The one model call is Suggest's."""
        prompt = "an old man reading on a porch at dusk"
        reply = {"vary": ["old man"], "adds": [{"name": "weather", "label": "weather", "after": "on a porch",
                                                "insert": " in <weather>"}],
                 "photo": True, "stated": ["light", "angle", "film_look", "shot_size"],
                 "joins": {"lens": {"after": "at dusk", "insert": ", shot with <lens>"}}}
        ask = Fake(reply)
        monkeypatch.setattr(sg, "ask_model", ask)
        async with client as c:
            adds = (await c.post("/api/prompt-programs/suggest", json={"prompt": prompt})).json()["adds"]
            assert [(a["name"], a.get("insert")) for a in adds] == [("weather", " in <weather>"), ("lens", ", shot with <lens>")]
            for a, written in zip(adds, ["an old man reading on a porch in <weather> at dusk",
                                         "an old man reading on a porch at dusk, shot with <lens>"]):
                r = await c.post("/api/prompt-programs/add", json={"prompt": prompt, "name": a["name"], "after": a["after"],
                                                                  "insert": a["insert"], "suggested_for": prompt})
                assert r.json()["prompt"] == written
            assert len(ask.calls) == 1
            # The prompt changed after Suggest answered: the join is not used, the model places it.
            edited = prompt + ", lit by candlelight"
            monkeypatch.setattr(sg, "ask_model", Fake({"after": "old man", "insert": " in <weather>"}))
            r = await c.post("/api/prompt-programs/add", json={"prompt": edited, "name": "weather", "after": "on a porch",
                                                              "insert": " in <weather>", "suggested_for": prompt})
            assert r.json()["prompt"] == "an old man in <weather> reading on a porch at dusk, lit by candlelight"
