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
