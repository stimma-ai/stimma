"""said=: a pick that stands for a thing the user named draws their words, exactly as written,
in every image until they tick other options; the writer marks it, validation holds it to an
exact stretch of the prompt, and a reading marks the picks a writer forgot to."""

import json
import time

import pytest

from prompt_programs import prepare as prep
from prompt_programs.draws import PickSpec, draw, fixed_text
from prompt_programs.fix import judged_picks
from prompt_programs.narrow import NarrowCache, narrow_entry
from prompt_programs.options import GeneratedOptions, OptionJob, OptionStore, ProgramContext, gen_key, generation_messages
from prompt_programs.runtime import discover, run
from prompt_programs.said import add_said, apply_said, candidates, parse, read_said
from prompt_programs.store import ProgramStore
from prompt_programs.vocab import vocabulary

USER = "cinematic shot of a yellow ferrari car in a desert"
FERRARI = '''
car = pick("car", said="yellow ferrari", about="the car", seed=["red lamborghini", "silver porsche"], label="Car", phase=1, added=True)
sky = pick("sky", about="the desert sky", seed=["clear blue", "dusty orange", "stormy gray"], label="Sky", phase=2, added=True)
emit("Cinematic shot of a", car, "car in a desert under a", sky, "sky.")
'''
# The same program as a forgetful writer writes it: the car pick varies the user's car.
FORGOT = FERRARI.replace('said="yellow ferrari", ', "")


def values(r):
    return {d.id: d.value for d in r.draws}


def entry_for(program=FERRARI, prompt=USER, **kw):
    info = discover(program)
    return {"key": "said1", "program": program, "prompt": prompt, "loras": [], "params": {}, "mode": "prose",
            "choices": info["choices"], "groups": info["groups"], **kw}


@pytest.fixture(autouse=True)
def no_profile(monkeypatch):
    import prompt_programs.fluent as fl
    monkeypatch.setattr(fl, "_profile_store", lambda pid: None)
    monkeypatch.setattr(fl, "filler_for", lambda pid: (_ for _ in ()).throw(RuntimeError("no filler in tests")))


# --------------------------------------------------------------------------- runtime semantics

class TestTheUsersWordsByDefault:
    def test_every_draw_uses_their_words_exactly(self):
        for s in range(30):
            r = draw(FERRARI, s)
            assert values(r)["car"] == "yellow ferrari" and "a yellow ferrari car" in r.prompt
            assert run(FERRARI, s).prompt.startswith("Cinematic shot of a yellow ferrari car")
        assert len({values(draw(FERRARI, s))["sky"] for s in range(30)}) > 1  # the rest still varies

    def test_it_is_a_choice_from_their_text_with_the_whole_pool(self):
        d = next(x for x in draw(FERRARI, 3).draws if x.id == "car")
        assert d.source == "text" and d.pinned and d.said == "yellow ferrari"
        assert d.options == ["yellow ferrari", "red lamborghini", "silver porsche"]
        assert d.to_dict()["said"] == "yellow ferrari"
        c = next(x for x in discover(FERRARI)["choices"] if x["id"] == "car")
        assert c["said"] == "yellow ferrari" and c["source"] == "text" and c["options"][0] == "yellow ferrari"

    def test_ticking_others_widens_it(self):
        pins = {"car": ["yellow ferrari", "red lamborghini"]}
        got = {values(draw(FERRARI, s, pins))["car"] for s in range(40)}
        assert got == {"yellow ferrari", "red lamborghini"}
        assert {values(run(FERRARI, s, pins))["car"] for s in range(40)} == got
        assert {values(draw(FERRARI, s, {"car": ["silver porsche"]}))["car"] for s in range(5)} == {"silver porsche"}

    def test_a_kept_value_replays_and_a_deleted_word_draws_from_the_rest(self):
        assert values(draw(FERRARI, 1, fixed={"car": "silver porsche"}))["car"] == "silver porsche"
        gone = {"car": {"remove": ["yellow ferrari"]}}
        assert {values(draw(FERRARI, s, edits=gone))["car"] for s in range(30)} <= {"red lamborghini", "silver porsche"}

    def test_the_programs_text_shows_their_words(self):
        assert fixed_text(FERRARI).startswith("Cinematic shot of a yellow ferrari car in a desert under a [Sky]")

    def test_per_person_picks_in_a_loop(self):
        src = '''
dogs = group("dogs", 2, label="Dogs", line=1)
emit("Two dogs on a beach:")
for i in range(dogs):
    breed = pick(f"dogs[{i+1}].breed", said="husky", about="this dog's breed", seed=["border collie"], label="Breed", phase=1)
    emit("a", breed, ";")
'''
        r = draw(src, 4)
        assert [d.value for d in r.draws] == ["husky", "husky"]
        r = draw(src, 4, {"dogs[2].breed": ["border collie"]})
        assert [d.value for d in r.draws] == ["husky", "border collie"]

    async def test_a_bound_pick_leads_with_their_words_and_is_never_narrowed(self, tmp_path):
        src = '''
dog = pick("dog", cls="animal.dog_breed", said="husky", about="the dog", seed=["beagle"], label="Dog", phase=1)
emit("A", dog, "playing on the beach")
'''
        entry = entry_for(src, "a husky playing on the beach")
        store = OptionStore(tmp_path / "o")
        opts = GeneratedOptions(store, ProgramContext.of(entry), generate=False)
        r = draw(src, 2, options=opts)
        d = r.draws[0]
        assert d.value == "husky" and d.options[0] == "husky" and len(d.options) > 10
        assert set(d.options[1:]) <= {v.text for v in vocabulary().get("animal.dog_breed").values}

        class NoAsk:
            async def __call__(self, *a):
                raise AssertionError("a said pick is never narrowed")
        assert await narrow_entry(entry, NarrowCache(tmp_path / "n"), NoAsk()) == []
        assert "dog" not in (entry.get("filters") or {})


# --------------------------------------------------------------------------- generated alternatives

class TestAlternatives:
    def spec(self, said="yellow ferrari"):
        return PickSpec("car", "Car", "the car", 1, "text", "pick", [said, "red lamborghini"], [], said=said)

    def test_the_generator_is_told_their_words_and_writes_alternatives(self):
        prog = ProgramContext("k", "t", "Cinematic shot of a yellow ferrari car", "prose", True)
        user = generation_messages(OptionJob("k", self.spec(), {}, prog, "t", 0))[1]["content"]
        assert 'The user wrote "yellow ferrari" for this detail' in user and "same kind of thing" in user
        plain = PickSpec("car", "Car", "the car", 1, "text", "pick", ["red lamborghini"], [])
        assert "The user wrote" not in generation_messages(OptionJob("k", plain, {}, prog, "t", 0))[1]["content"]

    def test_their_words_key_the_pool(self, tmp_path):
        a = gen_key(self.spec(), {}, "sig", "prose", True, said="yellow ferrari")
        assert a != gen_key(self.spec(), {}, "sig", "prose", True) != gen_key(self.spec(), {}, "sig", "prose", True, said="red ferrari")
        pool = GeneratedOptions(OptionStore(tmp_path), ProgramContext("k", "t", "t"), generate=False).get(self.spec(), {})
        assert pool.items[0] == "yellow ferrari" and pool.key.endswith("| said yellow ferrari")


# --------------------------------------------------------------------------- validation

class TestValidation:
    def problems(self, src, prompt=USER):
        return prep.validate(src, prompt, [], set())["problems"]

    def test_their_exact_words_pass(self):
        assert self.problems(FERRARI) == []
        assert self.problems(FERRARI.replace("yellow ferrari", "Yellow  Ferrari")) == []  # case and spacing aside

    def test_words_they_didnt_write_go_back_with_how_to_fix_it(self):
        bad = FERRARI.replace('said="yellow ferrari"', 'said="yellow Ferrari F40"')
        (msg,) = self.problems(bad)
        assert msg.startswith('pick("car") has said="yellow Ferrari F40", but the user\'s prompt doesn\'t say')
        assert "copied exactly from their prompt" in msg and "drop said=" in msg

    def test_their_words_said_twice(self):
        twice = FERRARI.replace('"Cinematic shot of a"', '"A yellow ferrari: cinematic shot of a"')
        assert any("fixed text says \"yellow ferrari\" too" in p for p in self.problems(twice))

    def test_not_on_a_wildcard_a_list_or_a_line_asking_to_vary_it(self):
        wild = 'w = pick("weather", said="rain", about="the weather", seed=["rain"], label="Weather", phase=1)\nemit("a car in", w)\n'
        assert any("smart wildcard" in p for p in self.problems(wild, "a car in {{weather}} rain"))
        asked = FERRARI.replace("added=True)\nsky", "line=2)\nsky")
        assert any("line 2 asks to vary" in p for p in self.problems(asked, USER + "\n# vary the car"))
        listed = 'c = pick("c", ["red", "blue"], said="red", source="list", phase=1, line=1)\nemit("a", c, "car")\n'
        assert self.problems(listed, "a {red|blue} car") == []  # a user list ignores said=
        assert all(d.value in ("red", "blue") for d in draw(listed, 1).draws)

    def test_the_source_and_line_point_at_their_words(self):
        prompt = "a desert at dusk\n" + USER
        info = prep.validate(FERRARI, prompt, [], set())["info"]
        prep.normalize_sources(info, prompt)
        car = next(c for c in info["choices"] if c["id"] == "car")
        assert car["source"] == "text" and car["line"] == 2


# --------------------------------------------------------------------------- the judge, records, replay

class TestJudgeAndReplay:
    def test_the_judge_never_rerolls_their_words(self):
        r = draw(FERRARI, 2)
        assert {d.id for d in judged_picks(r)} == {"sky"}
        for s in range(40):  # widened: drawing their own word is still never judged
            r = draw(FERRARI, s, {"car": ["yellow ferrari", "red lamborghini"]})
            ids = {d.id for d in judged_picks(r)}
            assert ("car" in ids) == (values(r)["car"] != "yellow ferrari")

    def test_realize_records_and_replays(self):
        entry = entry_for()
        r = prep.realize(entry, seed=9)
        rec = r.to_dict()
        assert next(d for d in rec["draws"] if d["id"] == "car") == {
            "id": "car", "value": "yellow ferrari", "kind": "pick", "label": "Car", "source": "text", "pinned": True,
            "phase": 1, "about": "the car", "said": "yellow ferrari"}
        again = prep.realize(entry, seed=9, revision=r.revision)
        assert again.prompt == r.prompt and again.revision == r.revision
        alt = prep.realize(entry, seed=9, pins={"car": ["silver porsche"]})
        same = prep.realize(entry, seed=11, fixed={d.id: d.value for d in alt.draws})
        assert values(same) == values(alt)  # "Same draws": an image that drew an alternative keeps it

    def test_use_these_choices_and_keep_choices_are_pins(self):
        from routes.generation import pins_for_kept_choices
        entry = entry_for()
        assert pins_for_kept_choices(entry, {"Car": "red lamborghini"}) == {"car": ["red lamborghini"]}
        r = prep.realize(entry, seed=1, pins=pins_for_kept_choices(entry, {"car": ["red lamborghini", "yellow ferrari"]}))
        assert values(r)["car"] in ("red lamborghini", "yellow ferrari")


# --------------------------------------------------------------------------- the reading

class TestReading:
    def test_candidates_are_unmarked_picks_the_writer_added(self):
        e = entry_for(FORGOT)
        assert [c["id"] for c in candidates(e)] == ["car", "sky"]
        assert [c["id"] for c in candidates(entry_for())] == ["sky"]

    def test_only_their_exact_words_missing_from_the_programs_text_are_kept(self):
        template = fixed_text(FORGOT)
        ids = ["car", "sky"]
        assert parse('{"car": "yellow ferrari", "sky": null}', ids, USER, template) == {"car": "yellow ferrari"}
        assert parse('{"car": "a Yellow  Ferrari"}', ids, USER, template) == {"car": "a yellow ferrari"}  # their spelling
        assert parse('{"car": "yellow Ferrari F40"}', ids, USER, template) == {}  # not their words
        assert parse('{"car": "desert"}', ids, USER, template) == {}  # the program still says it
        assert parse('{"car": "yellow ferrari", "sky": "yellow ferrari"}', ids, USER, template) == {}  # claimed twice
        assert parse("no", ids, USER, template) is None
        # weak models key the answer as the part was listed
        assert parse('{"car, shown as [Car]": "yellow ferrari", "sky [Sky]": null}', ids, USER, template) == {"car": "yellow ferrari"}

    def test_picks_the_writer_marked_as_the_users_are_asked_about_too_but_not_a_line_asking_to_vary(self):
        src = FORGOT.replace("added=True)\nsky", "line=1)\nsky")
        assert [c["id"] for c in candidates(entry_for(src))] == ["car", "sky"]
        src = FORGOT.replace("added=True)\nsky", "line=2)\nsky")
        assert [c["id"] for c in candidates(entry_for(src, USER + "\n# vary the car"))] == ["sky"]

    def test_add_said_marks_constant_ids_only(self):
        src, done = add_said(FORGOT, {"car": "yellow ferrari"})
        assert done == {"car": "yellow ferrari"} and 'added=True, said="yellow ferrari")' in src
        loop = 'for i in range(group("g", 2)):\n    pick(f"g[{i+1}].car", about="c", seed=["x"], phase=1)\nemit("a")\n'
        assert add_said(loop, {"g[1].car": "x"}) == (loop, {})

    async def test_a_forgotten_mark_is_read_and_applied(self, tmp_path):
        entry = entry_for(FORGOT)
        asked = []

        async def ask(messages, project_id, max_tokens):
            asked.append(messages)
            return json.dumps({"car": "yellow ferrari", "sky": None})
        found = await read_said(entry, NarrowCache(tmp_path), ask)
        assert found == {"car": "yellow ferrari"} and len(asked) == 1
        assert "[Car]" in asked[0][1]["content"] and "yellow ferrari" not in asked[0][1]["content"].split("version:")[1].split("The parts")[0]
        assert await read_said(entry, NarrowCache(tmp_path), ask) == found and len(asked) == 1  # cached
        notes = apply_said(entry, found)
        assert notes == ['car: keeps the user\'s "yellow ferrari"']
        car = next(c for c in entry["choices"] if c["id"] == "car")
        assert car["said"] == "yellow ferrari" and car["source"] == "text" and car["options"][0] == "yellow ferrari"
        assert "yellow ferrari" in entry["example"]
        assert all(values(prep.realize(entry, seed=s))["car"] == "yellow ferrari" for s in range(10))

    async def test_prepare_reads_it_beside_narrowing(self, tmp_path, monkeypatch):
        entry = entry_for(FORGOT)

        async def ask(messages, project_id, max_tokens=4096):
            return json.dumps({"car": "yellow ferrari"})
        monkeypatch.setattr(prep, "_ask_model", ask)
        await prep._narrow(entry, ProgramStore(tmp_path), None, time.monotonic())
        assert 'said="yellow ferrari"' in entry["program"] and "said" in entry["timing"]

    async def test_a_failed_reading_never_fails_the_prepare(self, tmp_path, monkeypatch):
        entry = entry_for(FORGOT)

        async def broken(messages, project_id, max_tokens=4096):
            raise RuntimeError("down")
        monkeypatch.setattr(prep, "_ask_model", broken)
        await prep._narrow(entry, ProgramStore(tmp_path), None, time.monotonic())
        assert entry["program"] == FORGOT


def test_said_is_written_in_the_users_own_spelling():
    src, notes = prep.fix_said(FERRARI.replace('"yellow ferrari"', '"Yellow  Ferrari"'), USER)
    assert 'said="yellow ferrari"' in src and notes
    assert prep.fix_said(FERRARI, USER) == (FERRARI, [])
    assert prep.users_spelling("YELLOW ferrari car", USER) == "yellow ferrari car"
    assert prep.users_spelling("ferrari truck", USER) == ""
