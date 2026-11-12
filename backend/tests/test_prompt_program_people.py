"""person(): the engine describes a person; the writer says who they are and where they stand."""
from prompt_programs.draws import analyze
from prompt_programs.people import DETAILS, expand_people
from prompt_programs.vocab import vocabulary

ONE = '''woman = person("woman", noun="woman", presentation="feminine", detail="full")
outfit = pick("woman.outfit", cls="person.outfit.casual", about=f"what the {woman} wears to cook", seed=["a linen apron"], label="Outfit", phase=2, added=True)
emit("A portrait of", woman, ", in her kitchen, wearing", outfit, ".")
'''



def bound(source):
    """{pick id: list} of the expanded program's bound picks, read from its text."""
    import ast
    out = {}
    for n in ast.walk(ast.parse(expand_people(source))):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "pick":
            kw = {k.arg: k.value for k in n.keywords}
            if "cls" in kw:
                out[ast.unparse(n.args[0]).strip("f\'\"")] = ast.literal_eval(kw["cls"])
    return out


class TestEveryPersonIsFullyDescribed:
    def test_a_person_gets_every_detail_as_an_ordinary_pick_of_theirs(self):
        got = bound(ONE)
        for key in ("age", "descent", "skin", "hair", "hair_color", "eyes", "face", "build"):
            assert got[f"woman.{key}"] == DETAILS[key][0]
        assert "woman.facial_hair" not in got and got["woman.outfit"] == "person.outfit.casual"
        assert all(vocabulary().get(cls) is not None for cls in got.values())
        analyze(expand_people(ONE))   # the expanded program is a valid program

    def test_a_pick_written_under_the_persons_own_id_is_the_only_one(self):
        # the writer's own pick of a detail, with no list: person() makes no second pick under that id
        src = expand_people('alien = person("alien", noun="alien")\n'
                            'skin = pick("alien.skin", about="the alien\'s skin", seed=["warty green skin"], label="Skin", phase=2, added=True)\n'
                            'emit("A photo of", alien, "with", skin, ".")\n')
        assert src.count('"alien.skin"') + src.count("'alien.skin'") == 1 and "person.skin_tone" not in src
        analyze(src)

    def test_a_detail_named_as_the_persons_own_is_their_pick_placed_by_hand(self):
        src = expand_people('w = person("woman", noun="woman")\nemit("A", w.noun, "with", w.hair, "hair down:", w, ".")\n')
        assert "w.hair" not in src and "w.noun" not in src
        emitted = src.strip().splitlines()[-1]
        assert emitted.count("w_hair,") == 1 and "'A', 'woman', 'with', w_hair" in emitted   # placed once, where they put it
        analyze(src)

    def test_a_person_placed_twice_is_described_once(self):
        src = expand_people('man = person("man", noun="man")\nemit("A photo of", man, "on a pier.")\nemit("Behind", man, ", gulls.")\n')
        first, second = src.strip().splitlines()[-2:]
        assert "man_age" in first and "man_face" in first
        assert second == "emit('Behind', 'the', 'man', ', gulls.')"
        analyze(src)

    def test_a_placement_that_may_not_run_never_stands_for_the_description(self):
        src = expand_people('w = person("woman", noun="woman")\nif False:\n    emit(w)\nemit("A portrait of", w)\n')
        assert "w_age" in src.strip().splitlines()[-1]

    def test_a_detail_named_as_the_persons_own_is_the_programs_pick_when_it_wrote_one(self):
        src = expand_people('w = person("woman", noun="woman")\n'
                            'h = pick("woman.hair", seed=["curly"], about="her hair", phase=2, added=True)\n'
                            'emit(w, "with", w.hair, "hair")\n')
        assert src.strip().splitlines()[-1].endswith("'with', h, 'hair')")
        analyze(src)

    def test_a_detail_named_outside_emit_stays_in_the_description(self):
        src = expand_people('w = person("woman", noun="woman")\n'
                            'hat = pick("hat", about=f"a hat for {w.hair} hair", seed=["a beret"], phase=3, added=True)\n'
                            'emit(w, "wearing", hat)\n')
        assert "w_hair, w_hair_color, 'hair'" in src.strip().splitlines()[-1]

    def test_the_description_stands_where_the_program_put_the_person(self):
        emit = expand_people(ONE).strip().splitlines()[-1]
        assert emit.startswith("emit('A portrait of', 'a', woman_build, woman_age, woman_descent, 'woman', 'with', woman_skin, 'skin'")
        assert emit.endswith("woman_face, ', in her kitchen, wearing', outfit, '.')")
        assert "what the {'woman'} wears" in expand_people(ONE)   # elsewhere the person is their noun

    def test_a_man_gets_facial_hair_and_the_lists_with_features_of_one_sex_are_told(self):
        src = expand_people('man = person("man", noun="fisherman", presentation="masculine", detail="full")\nemit(man, ", on a pier.")\n')
        assert "pick('man.facial_hair', cls='person.facial_hair'" in src
        assert "pick('man.face', cls='person.face', where={'presentation': 'masculine'}" in src
        assert "pick('man.build', cls='person.build', where={'presentation': 'masculine'}" in src

    def test_the_writer_passes_narrowing_words_only_for_an_age(self):
        src = expand_people('w = person("w", noun="woman", where={"age": "in her early thirties", "hair_color": "red"})\nemit(w)\n')
        assert "where='in her early thirties'" in src and "red" not in src

    def test_a_person_in_a_loop_is_brief_and_keeps_the_loops_id(self):
        src = expand_people('friends = group("friends", 3, label="Friends", line=1)\nfor i in range(friends):\n'
                            '    f = person(f"friends[{i+1}]", noun="friend")\n    emit(f, ";")\n')
        assert "pick(f'friends[{i + 1}].face', cls='person.face'" in src and "pick(f'friends[{i + 1}].age'" in src
        assert ".skin'" not in src and ".build'" not in src and ".eyes'" not in src
        analyze(src)

    def test_the_noun_may_be_the_users_list(self):
        src = expand_people('job = pick("job", ["chef", "firefighter"], label="Job", source="list", phase=1, line=1)\n'
                            'man = person("man", noun=job)\nemit(man, ", walking home.")\n')
        assert "man_descent, job, 'with'" in src


class TestNothingIsDrawnTwiceOrLeftOut:
    def test_a_person_never_emitted_stands_where_they_were_made(self):
        src = expand_people('w = person("w", noun="woman", detail="full")\nemit("In a kitchen.")\n')
        assert src.index("emit('a', w_build") < src.index("emit('In a kitchen.')")

    def test_the_writers_own_pick_on_a_persons_list_becomes_that_persons_detail(self):
        src = expand_people('w = person("woman", noun="woman")\n'
                            'hair = pick("hair", cls="person.hair_color", about="her hair", seed=["dark"], label="Hair", phase=2, added=True)\n'
                            'emit(w, ", with", hair, "hair.")\n')
        assert "hair = pick('woman.hair_color', cls='person.hair_color'" in src      # drawn as hers: fits her descent and age
        assert "w_hair_color" not in src and "', with', hair, 'hair.')" in src        # said once, where the writer said it

    def test_a_detail_the_user_asked_to_vary_is_left_to_their_pick(self):
        src = expand_people('w = person("woman", noun="woman")\n'
                            'eyes = pick("eyes", cls="person.eye_color", about="her eyes", seed=["green"], label="Eyes", phase=2, line=2)\n'
                            'emit(w, ", with", eyes, "eyes.")\n')
        assert "eyes = pick('eyes', cls='person.eye_color'" in src and "w_eyes" not in src

    def test_a_person_in_an_emitted_f_string_is_described_there(self):
        src = expand_people('w = person("woman", noun="woman", detail="full")\nm = person("man", noun="man", detail="full")\n'
                            'emit(f"A portrait of {w} and {m} in a kitchen.")\n')
        emit = src.strip().splitlines()[-1]
        assert src.count("emit(") == 1    # neither is emitted again where they were made
        assert emit.index("'A portrait of '") < emit.index("w_face") < emit.index("' and '") < emit.index("m_face") < emit.index("' in a kitchen.'")
        from prompt_programs.draws import draw
        assert "A portrait of a slender" in draw(src, 1).prompt

    def test_the_rest_of_an_emitted_f_string_stays_one_string(self):
        from prompt_programs.draws import draw
        src = expand_people('w = person("woman", noun="woman", detail="full")\nh = 12\nemit(f"Portrait of {w}, at {h:02}:{30:02}, in {\'day\'}light.")\n')
        assert ", at 12:30, in daylight." in draw(src, 1).prompt

    def test_leave_and_a_program_without_people(self):
        src = expand_people('w = person("w", noun="woman", leave=["eyes", "build"])\nemit(w, ", with emerald eyes.")\n')
        assert "w_eyes" not in src and "w_build" not in src and "w_face" in src
        plain = 'x = pick("x", about="a thing", seed=["a"], label="X", phase=1)\nemit(x)\n'
        assert expand_people(plain) == plain and expand_people("emit(person(") == "emit(person("


class TestAGroupsWordsAreEveryMembers:
    async def test_an_age_read_for_one_member_narrows_them_all(self, tmp_path):
        from prompt_programs.narrow import NarrowCache, narrow_entry
        from prompt_programs.runtime import discover
        src = expand_people('kids = group("kids", 3, label="Kids", line=1)\nfor i in range(kids):\n'
                            '    k = person(f"kids[{i+1}]", noun="kid")\n    emit(k, ";")\n')
        info = discover(src)
        entry = {"key": "k", "program": src, "loras": [], "params": {}, "mode": "prose", "choices": info["choices"],
                 "groups": info["groups"], "prompt": "kids playing football"}

        async def ask(messages, project_id, max_tokens):
            import json
            if "find the words" in messages[0]["content"]:   # the reading names the first kid and stops
                return json.dumps({"kids[1].age": "kids"})
            return json.dumps(["5–7-year-old", "8–10-year-old", "11–12-year-old"])
        await narrow_entry(entry, NarrowCache(tmp_path), ask)
        for i in (1, 2, 3):
            assert entry["filters"][f"kids[{i}].age"] == ["5–7-year-old", "8–10-year-old", "11–12-year-old"]


class TestTheOnePersonOwnsTheirDetails:
    SRC = ('nurse = person("nurse", noun="nurse", presentation="feminine")\n'
           "expression = pick('expression', cls='person.expression', about=\"the nurse's expression\", seed=['a weary look'], label='Expression', phase=2, added=True)\n"
           "corridor = pick('corridor', about='the hospital setting', seed=['a bright corridor'], label='Setting', phase=1, added=True)\n"
           "emit('A photo of', nurse, ', with', expression, ', in', corridor, '.')\n")

    def test_a_plain_person_detail_takes_the_one_persons_id(self):
        from prompt_programs import prepare as prep
        out, notes = prep.fix_lone_subject(expand_people(self.SRC), "a nurse in a corridor")
        assert 'pick("nurse.expression"' in out and "pick('corridor'" in out   # the scene's detail stays the scene's
        assert notes == ["expression: nurse's, so its id is nurse.expression"]
        assert not prep.validate(out, "a nurse in a corridor", [], set(), "", True)["problems"]

    def test_two_subjects_or_the_users_words_are_left_alone(self):
        from prompt_programs import prepare as prep
        two = expand_people(self.SRC + 'doctor = person("doctor", noun="doctor")\nemit(doctor)\n')
        assert prep.fix_lone_subject(two, "a nurse and a doctor")[0] == two
        said = expand_people(self.SRC.replace("added=True)\ncorridor", 'said="weary")\ncorridor'))
        assert "nurse.expression" not in prep.fix_lone_subject(said, "a weary nurse in a corridor")[0]


class TestPresentationIsContextForOutfits:
    """person(presentation=...) is context for that person's outfit lists: a man isn't drawn a sundress."""

    @staticmethod
    def worn(presentation, n=120):
        import dataclasses
        import tempfile

        from prompt_programs import prepare as prep
        from prompt_programs.fluent import runtime_for
        from prompt_programs.judge import settings
        from prompt_programs.options import OptionStore
        src = expand_people(f'p = person("p", noun="person"{presentation}, detail="full")\n'
                            'outfit = pick("p.outfit", cls="person.outfit.summer", about="what they wear", '
                            'seed=["shorts and a T-shirt"], label="Outfit", phase=2, added=True)\n'
                            'emit(p, ", wearing", outfit, ".")\n')
        src, _ = prep.fix_written(src, "a person on a beach", [])
        info = prep.validate(src, "a person on a beach", [], set(), "", True)["info"]
        entry = {"key": "k" + presentation, "program": src, "choices": info["choices"], "prompt": "a person on a beach", "mode": "prose"}
        store = OptionStore(tempfile.mkdtemp())
        cfg = dataclasses.replace(settings(), generate_options=False)
        out = []
        for seed in range(n):
            r = prep.realize(entry, seed=seed, runtime=runtime_for(entry, store=store, cfg=cfg))
            out.append(str(next(d for d in r.draws if d.id == "p.outfit").value))
        return out

    def test_a_man_draws_no_outfit_made_for_women_and_the_reverse(self):
        feminine = ("sundress", "bikini", "skirt")
        assert not [v for v in self.worn(', presentation="masculine"') if any(w in v for w in feminine)]
        assert [v for v in self.worn(', presentation="feminine"') if any(w in v for w in feminine)]

    def test_with_no_presentation_said_the_whole_list_is_drawn(self):
        got = self.worn("")
        assert [v for v in got if "sundress" in v or "bikini" in v or "skirt" in v] and [v for v in got if "shorts" in v]

    def test_a_list_narrowed_to_the_other_presentation_is_still_drawn(self):
        # every romantic casual outfit is tagged feminine: the user's narrowing stands, nothing aborts
        from prompt_programs.vocab import vocabulary
        leaf = vocabulary().leaves["person.outfit.casual"]
        romantic = [(v.text, v.weight) for v in leaf.matching({"style": "romantic"})]
        assert romantic and all(leaf.context_tags(t, "presentation") == ("feminine",) for t, _ in romantic)
        assert leaf.weigh(romantic, [("presentation", ("masculine",))]) == romantic
        mixed = [(v.text, v.weight) for v in leaf.values]
        after = dict(leaf.weigh(mixed, [("presentation", ("masculine",))]))
        assert all(after[t] == 0 for t, _ in romantic) and any(w > 0 for w in after.values())
