"""Where the Fluent branches meet: said=, context facets, per-subject groups, the age policy and
the prepare fallback, each checked against the others (no one branch's tests see these)."""


from prompt_programs.narrow import NarrowCache, narrow_entry

from tests.test_prompt_program_context import Ask, draws_of, entry_of, mismatched


# --------------------------------------------------------------------------- said x context

SAID_DESCENT = '''
descent = pick("descent", cls="person.ethnicity", said="Japanese", about="her descent", label="Descent", phase=1, line=1)
eyes = pick("eyes", cls="person.eye_color", about="her eye colour", seed=["brown"], label="Eyes", phase=1, line=1)
emit("A", descent, "woman with", eyes, "eyes")
'''


class TestSaidGivesContext:
    def test_the_users_descent_weights_the_colouring(self, tmp_path):
        e = entry_of(SAID_DESCENT, "a Japanese woman")
        miss = 0
        for r, d in draws_of(e, tmp_path, range(200)):
            assert d["descent"].value == "Japanese"
            miss += mismatched("person.eye_color", "eye_family", d["eyes"].value, "Japanese")
        assert miss < 15

    def test_words_that_are_no_list_value_give_context_through_the_stated_reading(self, tmp_path):
        src = SAID_DESCENT.replace('said="Japanese"', 'said="japanese"')
        e = entry_of(src, "a japanese woman",
                     stated_context=[{"of": "", "cls": "person.ethnicity", "values": ["Japanese"]}])
        miss = sum(mismatched("person.eye_color", "eye_family", d["eyes"].value, "Japanese")
                   for _, d in draws_of(e, tmp_path, range(200)))
        assert miss < 15

    async def test_a_said_descent_has_the_prompt_read_for_its_person(self, tmp_path):
        e = entry_of(SAID_DESCENT, "a Japanese woman")
        ask = Ask(read={"stated_ethnicity": "Japanese woman"}, keep={"Japanese woman": ["Japanese"]})
        await narrow_entry(e, NarrowCache(tmp_path), ask)
        assert e["stated_context"] == [{"of": "", "cls": "person.ethnicity", "values": ["Japanese"]}]
        assert not any(kind == "subset" and "descent" == phrase for kind, phrase in ask.calls)

    def test_a_said_taker_is_never_weighted(self, tmp_path):
        src = ('descent = pick("descent", cls="person.ethnicity", about="her descent", seed=["Korean"], label="Descent", phase=1, line=1)\n'
               'eyes = pick("eyes", cls="person.eye_color", said="green", about="her eye colour", label="Eyes", phase=2, line=1)\n'
               'emit("A", descent, "woman with", eyes, "eyes")')
        e = entry_of(src, "a woman with green eyes")
        for r, d in draws_of(e, tmp_path, range(30), pins={"descent": ["Japanese"]}):
            assert d["eyes"].value == "green"
            assert not [k for k in r.revision["pools"] if k.startswith("eyes") and " | context " in k], r.revision["pools"]
        # ticked alternatives are the user's choice too: drawn unweighted
        seen = set()
        for r, d in draws_of(e, tmp_path / "t", range(60), pins={"descent": ["Japanese"], "eyes": ["green", "blue"]}):
            seen.add(d["eyes"].value)
        assert seen == {"green", "blue"}


# --------------------------------------------------------------------------- said x groups

from prompt_programs.draws import person_of  # noqa: E402
from prompt_programs.options import program_minors  # noqa: E402
from prompt_programs.runtime import subject_of  # noqa: E402
from prompt_programs.vocab import vocabulary  # noqa: E402

from tests.test_prompt_program_subjects import (  # noqa: E402
    AGE, ETH, OUTFIT, STYLE, bound, by_id, hand, sections, subject_problems, written,
)


SAID_DRESS, SAID_MATCHING = ', said="red dress"', ', said="matching red dresses"'


class TestSaidInsideASubject:
    def test_a_said_pick_is_grouped_under_its_subject(self):
        src = hand(("mother", [AGE, STYLE]), ("daughter", [AGE, STYLE]),
                   extra_lines=[f"o = {bound('mother.outfit', OUTFIT, extra=SAID_DRESS)}"])
        src, checked, _ = written(src, "a mother in a red dress and her daughter")
        info = checked["info"]
        assert not subject_problems(checked) and not [p for p in checked["problems"] if "said" in p]
        c = by_id(info)["mother.outfit"]
        assert c["said"] == "red dress" and c["group"] == "mother"
        assert sections(info) == [("mother", None), ("daughter", None)]

    def test_a_flat_id_said_pick_is_repaired_under_its_subject_too(self):
        src = hand(extra_lines=[f"a = {bound('mother_age', AGE)}", f"b = {bound('mother_outfit', OUTFIT, extra=SAID_DRESS)}",
                                f"c = {bound('daughter_age', AGE)}", f"d = {bound('daughter_hairstyle', STYLE)}"])
        fixed, checked, _ = written(src, "a mother in a red dress and her daughter")
        assert '"mother.outfit"' in fixed and by_id(checked["info"])["mother.outfit"]["said"] == "red dress"

    def test_a_said_pick_naming_no_subject_is_not_rejected_as_partly_grouped(self):
        src = hand(("twin1", [STYLE]), ("twin2", [STYLE]),
                   extra_lines=[f"o = {bound('outfit', OUTFIT, extra=SAID_MATCHING)}"])
        assert not subject_problems(written(src, "twins in matching red dresses")[1])
        plain = hand(("twin1", [STYLE]), ("twin2", [STYLE]), extra_lines=[f"o = {bound('outfit', OUTFIT)}"])
        assert subject_problems(written(plain, "twins in matching red dresses")[1])   # unchanged without said


# --------------------------------------------------------------------------- groups x context x age policy

class TestOnePersonRule:
    def test_person_of_follows_the_subject_the_id_names(self):
        for cid in ("friends[2].age", "friends[2].outfit.colours", "friends[2].outfit.style", "woman1.hair",
                    "mother.outfit", "mother.outfit.colours", "twin_2.hairstyle"):
            s = subject_of(cid)
            assert s is not None and person_of(cid) and cid == person_of(cid) + "." + s[2], cid
        for cid in ("outfit", "outfit.colours", "param.steps"):
            assert subject_of(cid) is None and person_of(cid) == "", cid
        assert person_of("friends[{}].age") == "friends[{}]"   # a loop's site: its member

    def test_flat_ids_are_repaired_before_the_age_policy_reads_them(self):
        src = hand(extra_lines=[f"a = {bound('mother_age', AGE)}", f"b = {bound('mother_outfit', OUTFIT)}",
                                f"c = {bound('daughter_age', AGE)}", f"d = {bound('daughter_outfit', OUTFIT)}"])
        fixed, checked, _ = written(src, "a mother and her 8-year-old daughter")
        choices = checked["info"]["choices"]
        entry = {"choices": choices, "filters": {"daughter.age": ["8–10-year-old"]}}
        assert dict(program_minors(entry)) == {"daughter": ("8–10-year-old",)}
        assert {person_of(c["id"]) for c in choices if c.get("cls") == OUTFIT} == {"mother", "daughter"}

    def test_a_shared_age_speaks_for_every_subject(self, tmp_path):
        src = ('age = pick("age", cls="person.age_band", about="their age", seed=["8–10-year-old"], label="Age", phase=1, line=1, shared=True)\n'
               'a = pick("twin1.outfit", cls="person.outfit.summer", about="what she wears", seed=["a swimsuit"], label="Outfit", phase=1, line=1)\n'
               'b = pick("twin2.outfit", cls="person.outfit.summer", about="what she wears", seed=["a swimsuit"], label="Outfit", phase=1, line=1)\n'
               'emit("Two", age, "twins at the beach, one in", a, "and one in", b)')
        e = entry_of(src, "two 8-year-old twins at the beach", filters={"age": ["8–10-year-old"]})
        adult = {v.text for v in vocabulary().get("person.outfit.summer").eligible() if v.adult_only}
        assert adult
        for _, d in draws_of(e, tmp_path, range(40)):
            assert not adult & set(d["twin1.outfit"].options) and not adult & set(d["twin2.outfit"].options)

    def test_a_shared_detail_is_fit_for_the_youngest(self, tmp_path):
        src = ('ka = pick("kid.age", cls="person.age_band", about="the child\'s age", seed=["8–10-year-old"], label="Age", phase=1, line=1)\n'
               'ma = pick("mother.age", cls="person.age_band", about="the mother\'s age", seed=["35–39-year-old"], label="Age", phase=1, line=1)\n'
               'o = pick("outfit", cls="person.outfit.summer", about="what they both wear", seed=["a swimsuit"], label="Outfit", phase=1, line=1, shared=True)\n'
               'emit("A", ka, "child and her", ma, "mother at the beach, both in", o)')
        e = entry_of(src, "a child and her mother in matching swimsuits", filters={"kid.age": ["8–10-year-old"]})
        adult = {v.text for v in vocabulary().get("person.outfit.summer").eligible() if v.adult_only}
        for _, d in draws_of(e, tmp_path, range(40)):
            assert not adult & set(d["outfit"].options)

    def test_a_said_age_nothing_narrowed_still_limits_its_person(self, tmp_path):
        adult = {v.text for v in vocabulary().get("person.outfit.summer").eligible() if v.adult_only}
        for said in ("8–10-year-old", "eight year old"):   # a list value, and words nothing read
            src = (f'ga = pick("girl.age", cls="person.age_band", said="{said}", about="her age", label="Age", phase=1, line=1)\n'
                   'o = pick("girl.outfit", cls="person.outfit.summer", about="what she wears", seed=["a swimsuit"], label="Outfit", phase=2, line=1)\n'
                   's = pick("outfit", cls="person.outfit.summer", about="what they all wear", seed=["a swimsuit"], label="Outfit", phase=2, line=1, shared=True)\n'
                   'emit("A", ga, "girl at the beach in", o, "beside friends in", s)')
            e = entry_of(src, f"a {said} girl at the beach")   # no filters: narrowing never ran
            assert dict(program_minors(e)).get("girl"), said
            for _, d in draws_of(e, tmp_path / said.replace(" ", "_"), range(40)):
                assert d["girl.age"].value == said
                assert not adult & set(d["girl.outfit"].options) and not adult & set(d["outfit"].options)
        # an adult age in the list's own words stays an adult
        e = entry_of(src.replace(f'said="{said}"', 'said="35–39-year-old"'), "a 35-year-old woman at the beach")
        assert not dict(program_minors(e))

    def test_a_shared_descent_gives_each_subject_context(self, tmp_path):
        src = ('eth = pick("ethnicity", cls="person.ethnicity", about="their descent", seed=["Korean"], label="Descent", phase=1, line=1, shared=True)\n'
               'a = pick("woman.eyes", cls="person.eye_color", about="her eyes", seed=["brown"], label="Eyes", phase=1, line=1)\n'
               'b = pick("man.eyes", cls="person.eye_color", about="his eyes", seed=["brown"], label="Eyes", phase=1, line=1)\n'
               'emit("A", eth, "couple: she has", a, "eyes, he has", b, "eyes")')
        e = entry_of(src, "a Japanese couple")
        miss = 0
        for _, d in draws_of(e, tmp_path, range(200), pins={"ethnicity": ["Japanese"]}):
            miss += mismatched("person.eye_color", "eye_family", d["woman.eyes"].value, "Japanese")
            miss += mismatched("person.eye_color", "eye_family", d["man.eyes"].value, "Japanese")
        assert miss < 30

    async def test_a_shared_age_pick_means_no_one_is_read_again(self, tmp_path):
        src = ('age = pick("age", cls="person.age_band", about="their age", seed=["25–29-year-old"], label="Age", phase=1, line=1, shared=True)\n'
               'a = pick("twin1.outfit", cls="person.outfit.summer", about="what she wears", seed=["a swimsuit"], label="Outfit", phase=1, line=1)\n'
               'b = pick("twin2.outfit", cls="person.outfit.summer", about="what she wears", seed=["a swimsuit"], label="Outfit", phase=1, line=1)\n'
               'emit("Two", age, "twins, one in", a, "and one in", b)')
        e = entry_of(src, "two twins at the beach")
        ask = Ask()
        await narrow_entry(e, NarrowCache(tmp_path), ask)
        assert not any("stated_age" in text for kind, text in ask.calls if kind == "read")


# --------------------------------------------------------------------------- fallback x said / groups validation

SAID_CAR = '''car = pick("car", said="{said}", about="the car", seed=["red lamborghini"], label="Car", phase=1, line=1)
emit("{before}", car, "on a coastal road")
'''


def checked(src, prompt):
    return written(src, prompt)[1]


class TestWhatTheFirstRungTolerates:
    def test_said_words_the_user_didnt_write_block(self):
        got = checked(SAID_CAR.format(said="blue sports car", before="A cinematic shot of a"),
                      "a cinematic shot of a yellow ferrari on a coastal road")
        assert [p for p in got["blocking"] if "said=" in p]

    def test_said_on_the_users_wildcard_blocks(self):
        src = ('car = pick("car", said="ferrari", about="the car", seed=["a ferrari"], label="Car", phase=1, line=1)\n'
               'emit("A cinematic shot of a", car, "on a coastal road")\n')
        got = checked(src, "a cinematic shot of a {{car}} on a coastal road, a ferrari")
        assert [p for p in got["blocking"] if "smart wildcard" in p]

    def test_said_twice_costs_polish_only(self):
        got = checked(SAID_CAR.format(said="yellow ferrari", before="A cinematic shot of a yellow ferrari:"),
                      "a cinematic shot of a yellow ferrari on a coastal road")
        assert [p for p in got["problems"] if "said once" in p]
        assert not [p for p in got["blocking"] if "said" in p]

    def test_a_grouping_problem_only_costs_structure(self):
        src = hand(("woman1", [AGE, OUTFIT]), ("woman2", [AGE, OUTFIT]), extra_lines=[f"h = {bound('hairstyle', STYLE)}"])
        got = checked(src, "two women at a cafe")
        assert subject_problems(got) and not [p for p in got["blocking"] if "names no one" in p]
