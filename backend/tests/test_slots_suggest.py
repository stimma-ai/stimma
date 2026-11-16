"""Suggest (prompt_programs/suggest.py), with a fake model: what code keeps of a reply (phrases,
each Detail or Any with its kind, and adds from the fixed list), phrases already on screen kept,
the cache, the retry, the kind of selected words, exact text kept from the model, and the routes."""

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


def phrase(text, way="detail", kind="", names="kind"):
    return {"phrase": text, "way": way, "kind": kind, "names": names}


def reply(*phrases, medium="photo", camera_stated=True, people=(), face_described=True):
    """A reply in the model's shape. By default nothing is missing: no adds."""
    return {"phrases": [p if isinstance(p, dict) else phrase(p) for p in phrases], "medium": medium,
            "camera_stated": camera_stated, "people": list(people), "face_described": face_described}


def put(prompt, add):
    """The prompt with an add written in, as the editor writes it (utils/promptSuggestions insertAdd)."""
    return prompt[:add["at"]] + add["text"] + prompt[add["at"]:]


FARMER = "a farmer in rural Vietnam"
EMPTY = {"phrases": [], "adds": []}


# --------------------------------------------------------------------------- phrases

class TestPhrases:
    async def test_offsets_kinds_and_ways_in_prompt_order(self):
        ask = Fake(reply(phrase("rural Vietnam", "any", "region"), phrase("farmer", kind="person")))
        got = await sg.suggest(FARMER, ask)
        assert got["phrases"] == [
            {"from": 2, "to": 8, "text": "farmer", "kind": "person", "way": "detail", "mode": "kind", "label": "farmer"},
            {"from": 12, "to": 25, "text": "rural Vietnam", "kind": "region", "way": "any", "mode": "kind",
             "label": "rural Vietnam"}]
        for v in got["phrases"]:
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
        assert [(v["text"], prompt[v["from"]:v["to"]]) for v in got["phrases"]] == [("cat", "cat"), ("a tree", "a tree")]
        assert got["phrases"][0]["from"] > prompt.index("\n")  # the cat in the text, not the comment's

    async def test_overlaps_and_the_whole_prompt_are_dropped(self):
        got = await sg.suggest("# a note\nred bicycle by a tree",
                               Fake(reply("red bicycle by a tree", "bicycle", "red bicycle", "tree")))
        assert [v["text"] for v in got["phrases"]] == ["bicycle", "tree"]

    async def test_at_most_one_more_than_three_and_bare_strings_are_dropped(self):
        prompt = "a fox, a hare, an owl, a stoat, a mole"
        got = await sg.suggest(prompt, Fake({"phrases": ["fox", phrase("hare"), phrase("owl"), phrase("stoat"),
                                                         phrase("mole"), phrase("fox")]}))
        assert [v["text"] for v in got["phrases"]] == ["hare", "owl", "stoat", "mole"]
        assert (sg.MAX_PHRASES, sg.MAX_ANY) == (3, 1)

    async def test_one_any_at_most_and_only_with_a_kind(self):
        prompt = "a woman with a short bob in a red dress walking a golden retriever in Paris"
        got = await sg.suggest(prompt, Fake(reply(
            phrase("short bob", "any"),                       # no kind: Detail
            phrase("red dress", "any", "red dress"),          # its own words are no kind: Detail
            phrase("golden retriever", "ANY", "dog."),        # the first Any, its kind cleaned
            phrase("Paris", "any", "city"))))                 # a second Any: Detail, kind kept
        assert [(v["text"], v["way"], v["kind"]) for v in got["phrases"]] == [
            ("short bob", "detail", ""), ("red dress", "detail", ""), ("golden retriever", "any", "dog"),
            ("Paris", "detail", "city")]
        got = await sg.suggest("a woman", Fake(reply(phrase("woman", "sideways", "<person>"))))   # an unknown way, a kind with marks
        assert [(v["way"], v["kind"]) for v in got["phrases"]] == [("detail", "")]
        got = await sg.suggest("a dog in Paris", Fake(reply(phrase("Paris", "any", "city"), phrase("dog", "any", "animal"))))
        assert [(v["text"], v["way"]) for v in got["phrases"]] == [("dog", "detail"), ("Paris", "any")]

    @pytest.mark.parametrize("kind", ["a {red|blue} thing", "[EXACT_1]", "# note", "two\nlines",
                                      "far too many words here", "x" * 31, 4, None])
    async def test_a_kind_is_plain_words(self, kind):
        got = await sg.suggest("a short bob", Fake(reply(phrase("short bob", "any", kind))))
        assert [(v["way"], v["kind"]) for v in got["phrases"]] == [("detail", "")]

    async def test_each_phrase_says_whether_it_names_one_thing(self):
        prompt = "a farmer at the Eiffel Tower with a dog"
        got = await sg.suggest(prompt, Fake(reply(phrase("farmer", names="kind"), phrase("Eiffel Tower", names=" One "),
                                                  phrase("dog", names="several"))))
        assert [(v["text"], v["mode"]) for v in got["phrases"]] == [("farmer", "kind"), ("Eiffel Tower", "one"), ("dog", "kind")]
        for word in ('"detail"', '"any"', '"kind"', '"names"', '"one"'):
            assert word in sg.SUGGEST_SYSTEM

    async def test_each_phrase_has_a_label_for_its_chip(self):
        prompt = "a scruffy old dog in a worn leather jacket by the Eiffel Tower, a woman with a short bob"
        got = await sg.suggest(prompt, Fake(reply(
            {**phrase("scruffy old dog"), "label": "  dog. "},                           # trimmed
            {**phrase("worn leather jacket"), "label": "a very long label for it"},     # too long: last two words
            {**phrase("Eiffel Tower"), "label": "<landmark>"},                          # marks: last two words
            {**phrase("short bob", "any", "hairstyle"), "label": 4})))                  # not words: last two words
        assert [(v["text"], v["label"]) for v in got["phrases"]] == [
            ("scruffy old dog", "dog"), ("worn leather jacket", "leather jacket"), ("Eiffel Tower", "Eiffel Tower"),
            ("short bob", "short bob")]
        got = await sg.suggest("a fox", Fake(reply({**phrase("fox"), "label": "red fox"})))
        assert got["phrases"][0]["label"] == "red fox"
        got = await sg.suggest("a fox", Fake(reply("fox")))   # missing: the phrase's own words
        assert got["phrases"][0]["label"] == "fox"
        assert '"label"' in sg.SUGGEST_SYSTEM

    async def test_a_bad_reply_gives_nothing_quietly(self):
        for junk in ({"phrases": 3, "people": "x", "medium": 4}, {"phrases": [1, None, {"phrase": 4}, {"phrase": "a"}]}, {}):
            assert await sg.suggest(FARMER, Fake(junk)) == EMPTY


# --------------------------------------------------------------------------- phrases on screen stay

class TestPrevious:
    PROMPT = "a golden retriever and a cat on a sofa"
    SHOWN = {"phrases": [{"text": "sofa", "way": "any", "kind": "furniture", "mode": "kind"},
                         {"text": "cat", "way": "detail", "kind": "animal", "mode": "one"}],
             "adds": ["camera"]}

    async def test_shown_phrases_are_kept_first_as_they_were(self):
        got = await sg.suggest(self.PROMPT, Fake(reply(phrase("golden retriever", "any", "dog"),
                                                       phrase("cat", "any", "pet"))), previous=self.SHOWN)
        assert [(v["text"], v["way"], v["kind"], v["mode"]) for v in got["phrases"]] == [
            ("golden retriever", "detail", "dog", "kind"),   # the one Any is the shown sofa's
            ("cat", "detail", "animal", "one"),              # as shown, not as the reply says
            ("sofa", "any", "furniture", "kind")]

    async def test_a_shown_phrase_keeps_its_label(self):
        shown = {"phrases": [{"text": "golden retriever", "way": "any", "kind": "dog", "mode": "kind", "label": "dog"}]}
        got = await sg.suggest(self.PROMPT, Fake(reply({**phrase("golden retriever"), "label": "retriever"})), previous=shown)
        assert [(v["text"], v["label"]) for v in got["phrases"]] == [("golden retriever", "dog")]
        shown = {"phrases": [{"text": "golden retriever", "way": "any", "kind": "dog", "mode": "kind"}]}   # from before labels
        got = await sg.suggest(self.PROMPT, Fake(reply()), previous=shown)
        assert [(v["text"], v["label"]) for v in got["phrases"]] == [("golden retriever", "golden retriever")]

    async def test_a_reply_repeating_a_shown_phrase_keeps_it_once(self):
        prompt = "a dog chasing a dog"
        shown = {"phrases": [{"text": "dog", "way": "detail", "kind": "animal", "mode": "kind"}], "adds": []}
        got = await sg.suggest(prompt, Fake(reply("dog")), previous=shown)
        assert [(v["from"], v["text"]) for v in got["phrases"]] == [(2, "dog")]

    async def test_a_shown_phrase_that_no_longer_fits_goes(self):
        prompt = "a golden retriever and a cat on a <sofa>"
        got = await sg.suggest(prompt, Fake(reply(phrase("golden retriever", "any", "dog"))), previous=self.SHOWN)
        assert [(v["text"], v["way"]) for v in got["phrases"]] == [("golden retriever", "any"), ("cat", "detail")]

    async def test_shown_phrases_count_toward_the_cap(self):
        prompt = "a fox, a hare, an owl, a stoat, a mole"
        shown = {"phrases": [{"text": t, "way": "detail", "kind": "animal"} for t in ("mole", "stoat", "owl")]}
        got = await sg.suggest(prompt, Fake(reply("fox", "hare")), previous=shown)
        assert [v["text"] for v in got["phrases"]] == ["fox", "owl", "stoat", "mole"]

    async def test_the_model_is_told_and_the_cache_knows(self, tmp_path):
        ask = Fake(reply("cat"))
        await sg.suggest(self.PROMPT, ask, previous=self.SHOWN)
        turn = ask.calls[0][1]["content"]
        assert "On screen now, from your last answer: sofa: any, kind furniture; cat: detail, kind animal." in turn
        ask = Fake(reply("cat"))
        await sg.suggest(self.PROMPT, ask)
        assert "On screen now" not in ask.calls[0][1]["content"]
        assert sg.suggest_key(self.PROMPT, "m", self.SHOWN) != sg.suggest_key(self.PROMPT, "m")
        # Adds shown don't change what the model is asked.
        assert sg.suggest_key(self.PROMPT, "m", self.SHOWN) == sg.suggest_key(self.PROMPT, "m", {**self.SHOWN, "adds": []})
        cache = NarrowCache(tmp_path)
        ask = Fake(reply("cat"), reply("sofa"))
        await sg.suggest(self.PROMPT, ask, cache, previous=self.SHOWN)
        await sg.suggest(self.PROMPT, ask, cache)
        await sg.suggest(self.PROMPT, ask, cache, previous=self.SHOWN)
        assert len(ask.calls) == 2


# --------------------------------------------------------------------------- adds

class TestAdds:
    async def test_a_face_after_the_first_person_and_a_camera_at_the_end(self):
        got = await sg.suggest(FARMER, Fake(reply(people=["farmer", "rural Vietnam"], camera_stated=False, face_described=False)))
        assert [(a["key"], a["label"]) for a in got["adds"]] == [("face", "Face"), ("camera", "Camera")]
        face, camera = got["adds"]
        assert set(face) == {"key", "label", "at", "text"}
        assert put(FARMER, face) == "a farmer with <face> in rural Vietnam"
        assert put(FARMER, camera) == "a farmer in rural Vietnam, <camera>"

    @pytest.mark.parametrize("prompt, person, face", [
        ("a <woman> reading in a cafe", "woman", "a <woman> with <face> reading in a cafe"),
        ("a <young woman> reading", "woman", "a <young woman> with <face> reading"),
        ("a woman with a short bob", "woman", "a woman with <face> and a short bob"),
        ("a <woman> with a short bob", "woman", "a <woman> with <face> and a short bob"),
        ("a woman\twith  a short bob", "woman", "a woman\twith  <face> and a short bob"),
        ("a woman without a hat", "woman", "a woman with <face> without a hat"),
    ])
    async def test_a_face_after_a_slot_and_before_with(self, prompt, person, face):
        got = await sg.suggest(prompt, Fake(reply(people=[person], face_described=False)))
        assert [a["key"] for a in got["adds"]] == ["face"]
        assert put(prompt, got["adds"][0]) == face

    @pytest.mark.parametrize("prompt, camera", [
        ("a farmer,", "a farmer, <camera>"),
        ("a farmer; ", "a farmer; <camera> "),
        ("a farmer\n# keep it calm\n", "a farmer, <camera>\n# keep it calm\n"),
        ("# a note\na <farmer> in a field\n\n", "# a note\na <farmer> in a field, <camera>\n\n"),
    ])
    async def test_the_camera_goes_at_the_end_of_the_last_picture_line(self, prompt, camera):
        got = await sg.suggest(prompt, Fake(reply(camera_stated=False)))
        assert [a["key"] for a in got["adds"]] == ["camera"]
        assert put(prompt, got["adds"][0]) == camera

    @pytest.mark.parametrize("medium, stated, wanted", [
        ("photo", False, True), ("", False, True), ("Photograph", False, True), (None, False, True),
        ("photo", True, False), ("photo", None, False), ("watercolor", False, False), ("anime illustration", False, False),
    ])
    async def test_a_camera_only_for_a_photo_that_doesnt_say_how_it_is_taken(self, medium, stated, wanted):
        got = await sg.suggest(FARMER, Fake(reply(medium=medium, camera_stated=stated)))
        assert [a["key"] for a in got["adds"]] == (["camera"] if wanted else [])

    @pytest.mark.parametrize("people, described", [
        (["farmer"], True), (["farmer"], None), ([], False), (["fisherman"], False), (["f"], False),
        ("farmer", False), ([4], False), (["farmer"], "no"),
    ])
    async def test_no_face_when_described_or_no_person_in_the_prompt(self, people, described):
        got = await sg.suggest(FARMER, Fake({**reply(face_described=described), "people": people}))
        assert got["adds"] == []

    async def test_the_next_person_is_tried_and_a_slot_holds_them_as_a_whole_run(self):
        prompt = "# the man stays\na <woman> and a girl"
        got = await sg.suggest(prompt, Fake(reply(people=["man", "girl"], face_described=False)))
        assert put(prompt, got["adds"][0]) == "# the man stays\na <woman> and a girl with <face>"

    async def test_no_face_for_a_person_only_in_a_note_or_exact_text(self):
        for prompt in ("# the farmer stays\na field at dawn", "a sign that reads [farmer] in a field"):
            got = await sg.suggest(prompt, Fake(reply(people=["farmer"], face_described=False)))
            assert got["adds"] == []

    async def test_an_add_is_skipped_when_its_slot_is_there(self):
        for prompt, skipped in (("a farmer with <face>, <camera>", {"face", "camera"}),
                                ("a farmer, <Camera>", {"camera"}),
                                ("a <face> of a farmer", {"face"})):
            got = await sg.suggest(prompt, Fake(reply(people=["farmer"], camera_stated=False, face_described=False)))
            assert {"face", "camera"} - {a["key"] for a in got["adds"]} == skipped

    def test_the_adds_are_a_fixed_list(self):
        assert [(a["key"], a["slot"], a["place"]) for a in sg.ADDS] == [("face", "face", "after_person"), ("camera", "camera", "end")]
        for gone in ("looks", "vary", "shot_stated"):
            assert f'"{gone}"' not in sg.SUGGEST_SYSTEM
        # A label is only a phrase's now, never an add's (adds take theirs from ADDS).
        assert '"label"' not in sg.SUGGEST_SYSTEM.split('"medium"')[-1]


# --------------------------------------------------------------------------- the call

class TestCall:
    async def test_cache_makes_one_call(self, tmp_path):
        cache = NarrowCache(tmp_path)
        ask = Fake(reply("farmer", camera_stated=False))
        first = await sg.suggest(FARMER, ask, cache, model="m")
        assert first["adds"] and first["phrases"]
        assert await sg.suggest(FARMER, ask, cache, model="m") == first
        assert len(ask.calls) == 1
        await sg.suggest(FARMER + " ", Fake(reply("farmer")), cache, model="m")   # another prompt, even by a space
        await sg.suggest(FARMER, Fake(reply("farmer")), cache, model="other")    # another model
        assert len(list(tmp_path.rglob("*.json"))) == 3

    async def test_an_old_versions_cache_entry_is_not_read(self, tmp_path, monkeypatch):
        cache = NarrowCache(tmp_path)
        monkeypatch.setattr(sg, "SUGGEST_VERSION", "suggest-9")
        cache.put_raw(sg.suggest_key(FARMER, "m"), {"phrases": [], "adds": []})
        monkeypatch.undo()
        got = await sg.suggest(FARMER, Fake(reply("farmer")), cache, model="m")
        assert [v["text"] for v in got["phrases"]] == ["farmer"]

    async def test_a_cache_entry_in_the_old_shape_is_not_read(self, tmp_path):
        cache = NarrowCache(tmp_path)
        cache.put_raw(sg.suggest_key(FARMER, "m"), {"vary": [], "looks": [], "adds": []})
        got = await sg.suggest(FARMER, Fake(reply("farmer")), cache, model="m")
        assert [v["text"] for v in got["phrases"]] == ["farmer"]

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
        assert [v["text"] for v in got["phrases"]] == ["farmer"] and len(ask.calls) == 2
        assert ask.calls[1][-2] == {"role": "assistant", "content": "sure! here you go"}
        assert "JSON" in ask.calls[1][-1]["content"]
        ask = Fake("no", "[1, 2]")
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


# --------------------------------------------------------------------------- the kind of selected words

class TestKindOf:
    PROMPT = "a woman with a short bob in Paris"

    def span(self, words, prompt=PROMPT):
        at = prompt.index(words)
        return at, at + len(words)

    async def test_the_kind_of_the_words(self):
        ask = Fake(' "Hairstyle."\nit is cut short ', "hairstyle\nbecause it is one")
        assert await sg.kind_of(self.PROMPT, *self.span("short bob"), ask) == "Hairstyle"
        assert await sg.kind_of(self.PROMPT, *self.span("bob"), ask) == "hairstyle"
        assert ask.calls[0][0] == {"role": "system", "content": sg.KIND_SYSTEM}
        assert ask.calls[0][1]["content"].endswith("The phrase: short bob") and self.PROMPT in ask.calls[0][1]["content"]
        assert ask.max_tokens == [sg.KIND_TOKENS] * 2

    @pytest.mark.parametrize("answer", ["", "   ", "short bob", "a {cut|style}", "it is a kind of hairstyle worn short"])
    async def test_nothing_when_it_cant_be_said(self, answer):
        assert await sg.kind_of(self.PROMPT, *self.span("short bob"), Fake(answer)) == ""

    async def test_no_call_for_no_words_or_marks(self):
        ask = Fake()
        prompt = "a <woman> with [a short bob]"
        for start, end in ((5, 5), (8, 3), (-1, 4), (0, 999), self.span("<woman>", prompt), self.span("[a short", prompt)):
            assert await sg.kind_of(prompt, start, end, ask) == ""
        assert ask.calls == []

    @pytest.mark.parametrize("answer", ["none", "None.", ' "none" ', "NONE\nnothing is wider"])
    async def test_none_says_nothing_is_wider(self, answer):
        assert await sg.kind_of("a person in a park", 2, 8, Fake(answer)) == ""

    async def test_the_words_given_back_are_nothing_wider(self):
        assert await sg.kind_of("a person in a park", 2, 8, Fake("Person")) == ""

    async def test_cached_by_the_prompt_and_the_span_empty_answers_too(self, tmp_path):
        cache = NarrowCache(tmp_path)
        ask = Fake("hairstyle", "city", "none", "bob")
        assert await sg.kind_of(self.PROMPT, *self.span("short bob"), ask, cache, model="m") == "hairstyle"
        assert await sg.kind_of(self.PROMPT, *self.span("short bob"), ask, cache, model="m") == "hairstyle"
        assert await sg.kind_of(self.PROMPT, *self.span("Paris"), ask, cache, model="m") == "city"
        for _ in range(2):   # "none", then the words given back: each asked once, then cached as ""
            assert await sg.kind_of(self.PROMPT, *self.span("woman"), ask, cache, model="m") == ""
            assert await sg.kind_of(self.PROMPT, *self.span("bob"), ask, cache, model="m") == ""
        assert len(ask.calls) == 4 and len(list(tmp_path.rglob("*.json"))) == 4

    async def test_a_new_version_asks_again(self, tmp_path, monkeypatch):
        cache = NarrowCache(tmp_path)
        assert sg.SUGGEST_VERSION == "suggest-12"
        assert await sg.kind_of(self.PROMPT, *self.span("woman"), Fake("none"), cache, model="m") == ""
        monkeypatch.setattr(sg, "SUGGEST_VERSION", "suggest-13")
        assert await sg.kind_of(self.PROMPT, *self.span("woman"), Fake("person"), cache, model="m") == "person"

    def test_the_prompts_say_when_nothing_is_wider(self):
        assert 'Reply "none" when no plain, wider word' in sg.KIND_SYSTEM
        assert 'Never "any" for a phrase whose kind is no wider than its words.' in sg.SUGGEST_SYSTEM

    async def test_a_suggested_none_kind_is_no_kind(self):
        got = await sg.suggest("a person in a park", Fake(reply(phrase("person", "any", "none"))))
        assert [(v["text"], v["way"], v["kind"]) for v in got["phrases"]] == [("person", "detail", "")]


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
        ask = Fake(reply(phrase("farmer", kind="person"), people=["farmer"], camera_stated=False, face_described=False))
        monkeypatch.setattr(sg, "ask_model", ask)
        async with client as c:
            r = await c.post("/api/prompt-programs/suggest", json={"prompt": FARMER, "project_id": 3})
            assert r.status_code == 200
            assert r.json() == {
                "phrases": [{"from": 2, "to": 8, "text": "farmer", "kind": "person", "way": "detail", "mode": "kind",
                             "label": "farmer"}],
                "adds": [{"key": "face", "label": "Face", "at": 8, "text": " with <face>"},
                         {"key": "camera", "label": "Camera", "at": 25, "text": ", <camera>"}]}
            again = await c.post("/api/prompt-programs/suggest", json={"prompt": FARMER})
            assert again.json() == r.json() and len(ask.calls) == 1
            assert (await c.post("/api/prompt-programs/suggest", json={"prompt": FARMER, "raw": True})).json() == EMPTY
        assert list((tmp_path / "a" / "prompt_programs" / "suggest").rglob("*.json"))

    async def test_suggest_with_what_is_shown(self, client, monkeypatch):
        ask = Fake(reply("farmer"))
        monkeypatch.setattr(sg, "ask_model", ask)
        previous = {"phrases": [{"text": "rural Vietnam", "way": "any", "kind": "region", "mode": "kind"}], "adds": ["camera"]}
        async with client as c:
            r = await c.post("/api/prompt-programs/suggest", json={"prompt": FARMER, "previous": previous})
            assert r.status_code == 200
            assert [(v["text"], v["way"]) for v in r.json()["phrases"]] == [("farmer", "detail"), ("rural Vietnam", "any")]
        assert "On screen now, from your last answer: rural Vietnam: any, kind region." in ask.calls[0][1]["content"]

    async def test_suggest_kind(self, client, monkeypatch, tmp_path):
        ask = Fake("region")
        monkeypatch.setattr(sg, "ask_model", ask)
        async with client as c:
            r = await c.post("/api/prompt-programs/suggest-kind", json={"prompt": FARMER, "start": 12, "end": 25, "project_id": 3})
            assert r.status_code == 200 and r.json() == {"kind": "region"}
            again = await c.post("/api/prompt-programs/suggest-kind", json={"prompt": FARMER, "start": 12, "end": 25})
            assert again.json() == {"kind": "region"} and len(ask.calls) == 1
            assert (await c.post("/api/prompt-programs/suggest-kind", json={"prompt": FARMER, "start": 30, "end": 40})).json() == {"kind": ""}
            assert (await c.post("/api/prompt-programs/suggest-kind", json={"prompt": FARMER})).status_code == 422
        assert "The phrase: rural Vietnam" in ask.calls[0][1]["content"]
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
        ask = Fake(reply("woman", "park", people=["woman"], face_described=False, camera_stated=False))
        got = await sg.suggest(prompt, ask)
        assert self.SECRET not in self.sent(ask) and "[EXACT_1]" in self.sent(ask)
        for v in got["phrases"]:   # offsets still index the prompt as typed
            assert prompt[v["from"]:v["to"]] == v["text"]
        assert [put(prompt, a) for a in got["adds"]] == [
            f"a woman with <face> holding a sign that reads [{self.SECRET}] in a park",
            f"a woman holding a sign that reads [{self.SECRET}] in a park, <camera>"]

    async def test_nor_with_slots_nor_on_the_retry_nor_with_what_is_shown(self):
        prompt = f"a <woman> holding a sign that reads [{self.SECRET}] at <place>"
        ask = Fake("not json", reply())
        await sg.suggest(prompt, ask, previous={"phrases": [{"text": "sign", "way": "detail", "kind": "sign"}]})
        assert len(ask.calls) == 2
        assert self.SECRET not in self.sent(ask) and "[EXACT_1]" in self.sent(ask)
        assert "Already changing from picture to picture: <woman>, <place>." in ask.calls[0][1]["content"]

    async def test_nor_when_asking_a_kind(self):
        prompt = f"a woman holding a sign that reads [{self.SECRET}] in a park"
        ask = Fake("person")
        assert await sg.kind_of(prompt, 2, 7, ask) == "person"
        assert self.SECRET not in self.sent(ask) and "[EXACT_1]" in self.sent(ask)

    async def test_a_reply_naming_the_token_is_dropped(self):
        prompt = f"a sign that reads [{self.SECRET}] in a park"
        got = await sg.suggest(prompt, Fake(reply(phrase("[EXACT_1]"), phrase("EXACT_1"), phrase("park", "any", "[EXACT_1]"),
                                                  people=["EXACT_1"], face_described=False)))
        assert [(v["text"], v["way"], v["kind"]) for v in got["phrases"]] == [("park", "detail", "")]
        assert got["adds"] == []
