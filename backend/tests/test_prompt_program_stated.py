"""A value the user stated for a listed detail ("an Irish woman", "emerald eyes", "a 30 year old
man") is a choice set to their value: a bound pick with said= their words. Every image draws
their words until they tick others; the list's other values are there to tick; their person's
age is still read for the minors policy; the fix judge never scores their value."""

from prompt_programs.fix import judged_picks
from prompt_programs.narrow import NarrowCache, narrow_entry
from prompt_programs.options import program_minors
from prompt_programs.vocab import vocabulary

from tests.test_prompt_program_context import Ask, draws_of, entry_of

IRISH = '''
eth = pick("ethnicity", cls="person.ethnicity", said="Irish", about="her descent", seed=["Scottish"], label="Ethnicity", phase=1, line=1)
eyes = pick("eyes", cls="person.eye_color", said="emerald", about="her eye color", seed=["hazel"], label="Eyes", phase=2, line=1)
hair = pick("hair_color", cls="person.hair_color", about="her hair color", seed=["auburn"], label="Hair color", phase=2, line=1, added=True)
emit("An", eth, "woman with", eyes, "eyes and", hair, "hair in a cafe")
'''


def values_of(cls):
    return {v.text for v in vocabulary().get(cls).values}


class TestPegged:
    def test_their_value_is_drawn_every_time_whether_or_not_the_list_has_it(self, tmp_path):
        assert "Irish" in values_of("person.ethnicity") and "emerald" not in values_of("person.eye_color")
        e = entry_of(IRISH, "an Irish woman with emerald eyes in a cafe")
        hairs = set()
        for r, d in draws_of(e, tmp_path, range(30)):
            assert d["ethnicity"].value == "Irish" and d["eyes"].value == "emerald"
            assert "An Irish woman with emerald eyes and" in r.prompt
            hairs.add(d["hair_color"].value)
        assert len(hairs) > 3   # what they left open still varies

    def test_the_choice_shows_their_value_first_and_the_list_to_tick(self, tmp_path):
        e = entry_of(IRISH, "an Irish woman with emerald eyes in a cafe")
        by = {c["id"]: c for c in e["choices"]}
        assert by["ethnicity"]["said"] == "Irish" and by["eyes"]["said"] == "emerald"
        assert by["eyes"]["options"][0] == "emerald" and by["eyes"]["source"] == "text"
        _, d = next(draws_of(e, tmp_path, [0]))
        for cid, cls in (("ethnicity", "person.ethnicity"), ("eyes", "person.eye_color")):
            opts = d[cid].options
            assert opts[0] == by[cid]["said"] and opts.count(by[cid]["said"]) == 1
            assert len(set(opts) & values_of(cls)) > 10, cid

    def test_ticking_others_widens_it(self, tmp_path):
        e = entry_of(IRISH, "an Irish woman with emerald eyes in a cafe")
        pins = {"ethnicity": ["Irish", "Korean"], "eyes": ["emerald", "gray"]}
        seen = {"ethnicity": set(), "eyes": set()}
        for _, d in draws_of(e, tmp_path, range(60), pins=pins):
            for k in seen:
                seen[k].add(d[k].value)
        assert seen == {"ethnicity": {"Irish", "Korean"}, "eyes": {"emerald", "gray"}}
        for _, d in draws_of(e, tmp_path / "only", range(10), pins={"ethnicity": ["Korean"]}):
            assert d["ethnicity"].value == "Korean" and d["eyes"].value == "emerald"

    def test_the_fix_judge_never_scores_their_value(self, tmp_path):
        e = entry_of(IRISH, "an Irish woman with emerald eyes in a cafe")
        r, _ = next(draws_of(e, tmp_path, [3]))
        judged = {d.id for d in judged_picks(r)}
        assert "hair_color" in judged and not judged & {"ethnicity", "eyes"}

    def test_each_persons_value_is_their_own(self, tmp_path):
        src = ('m = pick("man.ethnicity", cls="person.ethnicity", said="Japanese", about="his descent", seed=["Korean"], label="Ethnicity", phase=1, line=1)\n'
               'w = pick("wife.ethnicity", cls="person.ethnicity", said="Nigerian", about="her descent", seed=["Ghanaian"], label="Ethnicity", phase=1, line=1)\n'
               'emit("A", m, "man and his", w, "wife shopping at a market")')
        e = entry_of(src, "a Japanese man and his Nigerian wife shopping at a market")
        for r, d in draws_of(e, tmp_path, range(10)):
            assert r.prompt.startswith("A Japanese man and his Nigerian wife")
        for _, d in draws_of(e, tmp_path / "t", range(30), pins={"wife.ethnicity": ["Nigerian", "Kenyan"]}):
            assert d["man.ethnicity"].value == "Japanese" and d["wife.ethnicity"].value in {"Nigerian", "Kenyan"}


AGE = '''
age = pick("{who}.age", cls="person.age_band", said="{said}", about="{whose} age", seed=["25–29-year-old"], label="Age", phase=1, line=1)
outfit = pick("{who}.outfit", about="what {who} wears outdoors", seed=["a windbreaker and jeans"], label="Outfit", phase=2, line=1, added=True)
emit("A", age, "{who}", "{doing}, wearing", outfit)
'''


def age_entry(who, said, doing):
    src = AGE.format(who=who, said=said, whose="her" if who == "girl" else "his", doing=doing)
    return entry_of(src, f"a {said} {who} {doing}")


class TestStatedAgeAndMinors:
    async def test_a_stated_age_is_read_even_with_nothing_else_of_theirs_bound(self, tmp_path):
        # The man's only bound pick is his own stated age: it is read, so he is an adult.
        e = age_entry("man", "30 year old", "fishing at dawn")
        ask = Ask(read={"man.stated_age": "30 year old"}, keep={"30 year old": ["30–34-year-old"]})
        await narrow_entry(e, NarrowCache(tmp_path), ask)
        assert e["ages"] == {"man": ["30–34-year-old"]}
        assert not dict(program_minors(e))
        assert "man.age" not in (e.get("filters") or {})   # their words are never narrowed away
        for _, d in draws_of(e, tmp_path / "d", range(10)):
            assert d["man.age"].value == "30 year old"

    async def test_a_stated_childs_age_limits_her_pools_even_when_ticked_to_adults(self, tmp_path):
        e = age_entry("girl", "12 year old", "flying a kite on a hill")
        ask = Ask(read={"girl.stated_age": "12 year old"}, keep={"12 year old": ["11–12-year-old"]})
        await narrow_entry(e, NarrowCache(tmp_path), ask)
        assert dict(program_minors(e)) == {"girl": ("11–12-year-old",)}
        for _, d in draws_of(e, tmp_path / "d", range(10)):
            assert d["girl.age"].value == "12 year old"
        # ticking adult ages is the user's own choice of value; her pools stay a minor's
        for _, d in draws_of(e, tmp_path / "t", range(10), pins={"girl.age": ["25–29-year-old"]}):
            assert d["girl.age"].value == "25–29-year-old"
        assert dict(program_minors(e)) == {"girl": ("11–12-year-old",)}

    def test_unread_the_childs_age_still_counts_as_a_minors(self):
        e = age_entry("girl", "12 year old", "flying a kite on a hill")   # narrowing never ran
        assert dict(program_minors(e)).get("girl")


FORGOT = '''
eyes = pick("eyes", cls="person.eye_color", about="her eye color", seed=["emerald"], label="Eyes", phase=1, line=1)
hair = pick("hair_color", cls="person.hair_color", about="her hair color", seed=["auburn"], label="Hair color", phase=1, added=True)
emit("A woman with", eyes, "eyes and", hair, "hair")
'''


class TestAForgottenMarkOnAListedDetail:
    def test_a_bound_pick_from_their_text_is_asked_about_and_an_added_one_is_not(self):
        from prompt_programs.said import candidates
        e = entry_of(FORGOT, "a woman with emerald eyes")
        assert [c["id"] for c in candidates(e)] == ["eyes"]
        # marked added but pointing at the user's line: still asked about
        e = entry_of(FORGOT.replace('label="Eyes", phase=1, line=1)', 'label="Eyes", phase=1, line=1, added=True)'),
                     "a woman with emerald eyes")
        assert [c["id"] for c in candidates(e)] == ["eyes"]

    def test_marking_it_undoes_its_narrowing_so_the_list_is_there_to_tick(self, tmp_path):
        from prompt_programs.said import apply_said
        e = entry_of(FORGOT, "a woman with emerald eyes", filters={"eyes": ["green"]})
        eyes = next(c for c in e["choices"] if c["id"] == "eyes")
        eyes.update(options=["green"], where="emerald")
        assert apply_said(e, {"eyes": "emerald"})
        assert "eyes" not in e["filters"] and "where" not in eyes and eyes["said"] == "emerald"
        assert eyes["options"][0] == "emerald"
        for _, d in draws_of(e, tmp_path, range(20)):
            assert d["eyes"].value == "emerald"
        _, d = next(draws_of(e, tmp_path / "o", [0]))
        assert len(set(d["eyes"].options) & values_of("person.eye_color")) > 10


class TestAnAgeLeftWithoutItsList:
    SRC = '''
man_age = pick("man.age_band", about="the man's age", seed=["middle-aged"], label="Age", phase=1, added=True)
wife_age = pick("wife.age", about="the wife's age", seed=["young adult"], label="Age", phase=1, added=True)
job = pick("job", ["chef", "baker"], label="Job", source="list", phase=1, line=1)
mood = pick("mood", about="the mood at the market", seed=["busy"], label="Mood", phase=1, added=True)
emit("A", man_age, "man and his", wife_age, job, "wife at a market,", mood)
'''

    def test_it_is_bound_to_the_age_list_and_draws_adults(self, tmp_path):
        from prompt_programs.prepare import fix_age_lists
        fixed, notes = fix_age_lists(self.SRC)
        assert fixed.count('cls="person.age_band"') == 2 and len(notes) == 2
        assert 'pick("job", ["chef", "baker"], label="Job"' in fixed and 'pick("mood", about=' in fixed
        e = entry_of(fixed, "a man and his wife at a market")
        adults = {v.text for v in vocabulary().get("person.age_band").values if not v.minor}
        for _, d in draws_of(e, tmp_path, range(30)):
            assert d["man.age_band"].value in adults and d["wife.age"].value in adults

    def test_per_person_ids_in_a_loop_and_bound_ones_are_left(self):
        from prompt_programs.prepare import fix_age_lists
        loop = ('friends = group("friends", 2, label="Friends", line=1)\n'
                'for i in range(friends):\n'
                '    a = pick(f"friends[{i+1}].age", about="this friend\'s age", seed=["20s"], label="Age", phase=1, added=True)\n'
                '    emit("a", a, "friend")')
        fixed, _ = fix_age_lists(loop)
        assert 'pick(f"friends[{i+1}].age", cls="person.age_band", about=' in fixed
        assert fix_age_lists(fixed) == (fixed, [])
        stated = 'a = pick("age", cls="person.age_band", said="30 year old", about="his age", seed=["35–39-year-old"], label="Age", phase=1, line=1)'
        assert fix_age_lists(stated) == (stated, [])


class TestThroughPerson:
    SRC = ('w = person("woman", noun="woman", presentation="feminine", said={"descent": "Irish", "eyes": "emerald", "age": "30 year old"})\n'
           'emit("A photo of", w, ", in a cafe.")')

    def test_person_gives_the_stated_details_said_and_draws_the_rest(self, tmp_path):
        from prompt_programs.people import expand_people
        src = expand_people(self.SRC)
        e = entry_of(src, "a photo of a 30 year old Irish woman with emerald eyes in a cafe")
        by = {c["id"]: c for c in e["choices"]}
        assert (by["woman.descent"]["said"], by["woman.eyes"]["said"], by["woman.age"]["said"]) == ("Irish", "emerald", "30 year old")
        assert by["woman.eyes"]["cls"] == "person.eye_color" and not by["woman.hair_color"].get("said")
        skins = set()
        for r, d in draws_of(e, tmp_path, range(20)):
            assert "30 year old Irish woman" in r.prompt and "emerald eyes" in r.prompt
            skins.add(d["woman.skin"].value)
        assert len(skins) > 2
        for _, d in draws_of(e, tmp_path / "t", range(30), pins={"woman.descent": ["Irish", "Korean"]}):
            assert d["woman.descent"].value in {"Irish", "Korean"}

    async def test_a_stated_childs_age_through_person_still_limits_her(self, tmp_path):
        from prompt_programs.people import expand_people
        src = expand_people('g = person("girl", noun="girl", presentation="feminine", said={"age": "12 year old"})\n'
                            'emit(g, ", flying a kite on a hill")')
        e = entry_of(src, "a 12 year old girl flying a kite on a hill")
        ask = Ask(read={"girl.stated_age": "12 year old"}, keep={"12 year old": ["11–12-year-old"]})
        await narrow_entry(e, NarrowCache(tmp_path), ask)
        assert dict(program_minors(e)).get("girl") == ("11–12-year-old",)
