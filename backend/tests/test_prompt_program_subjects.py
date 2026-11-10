"""Per-subject grouping in Fluent programs: with several subjects, each subject's details are
their own picks, grouped under that subject; scene details stay plain; a detail the user asked
to be the same for everyone is one pick marked shared=True. Structure decides (ids, the
per-individual vocabulary namespaces), never the prompt's words."""

import pytest

from prompt_programs import prepare as prep
from prompt_programs.draws import person_of
from prompt_programs.options import program_minors
from prompt_programs.runtime import discover, subject_of
from prompt_programs.vocab import vocabulary


def P(cid, cls=None, about="a detail", seed="x", label="Detail", phase=1, extra=""):
    c = f', cls="{cls}"' if cls else ""
    i = cid if cid.startswith("f\"") else f'"{cid}"'
    return f'pick({i}{c}, about="{about}", seed=["{seed}"], label="{label}", phase={phase}, added=True{extra})'


AGE, ETH, HAIR, STYLE, OUTFIT, DOG = ("person.age_band", "person.ethnicity", "person.hair_color", "person.hairstyle",
                                      "person.outfit.casual", "animal.dog_breed")
SEEDS = {"person.expression": "a frown", AGE: "25–29-year-old", ETH: "Korean", HAIR: "black", STYLE: "a low ponytail", OUTFIT: "a denim jacket",
         DOG: "French bulldog"}


def detail(cls):
    return "outfit" if cls.startswith("person.outfit.") else cls.split(".")[-1]


def bound(cid, cls, phase=1, extra=""):
    return P(cid, cls, seed=SEEDS[cls], phase=phase, extra=extra)


def hand(*people, scene=True, extra_lines=()):
    """A program that writes each subject out by hand: people = [(name, [cls...])]."""
    lines, parts = [], []
    for name, details in people:
        for cls in details:
            var = f"v{len(lines)}"
            cid = name + "." + detail(cls)
            lines.append(f"{var} = {bound(cid, cls)}")
            parts.append(var)
    lines += list(extra_lines)
    parts += [ln.split(" = ")[0] for ln in extra_lines]
    if scene:
        lines.append(f"place = {P('place', about='what the place holds', seed='a long bar')}")
        parts.append("place")
    lines.append("emit(" + ", \", \", ".join(parts) + ")")
    return "\n".join(lines) + "\n"


def loop(group_id, n, details, outside=(), extra_lines=()):
    """A group() with a loop giving each member their own `details`; `outside` picks sit before it."""
    lines = [f'{group_id} = group("{group_id}", {n}, label="{group_id.capitalize()}", line=1)']
    out_vars = []
    for cid, cls in outside:
        lines.append(f"o_{cid} = {bound(cid, cls)}")
        out_vars.append(f"o_{cid}")
    lines += list(extra_lines)
    lines.append(f'emit("They are"{"".join(", " + v for v in out_vars)}, ":")')
    lines.append(f"for i in range({group_id}):")
    vs = []
    for cls in details:
        v = detail(cls)
        cid = 'f"' + group_id + "[{i+1}]." + v + '"'
        lines.append(f"    {v} = {bound(cid, cls)}")
        vs.append(v)
    lines.append("    emit(" + ", ".join(vs) + ', ";")')
    return "\n".join(lines) + "\n"


def written(source, prompt):
    """The program as the app keeps it: the code fixes, then validation."""
    fixed, notes = prep.fix_written(source, prompt, [])
    return fixed, prep.validate(fixed, prompt, [], set(), ""), notes


def subject_problems(checked):
    return [p for p in checked["problems"] if "names no one" in p or "name no one" in p]


def by_id(info):
    return {c["id"]: c for c in info["choices"]}


def sections(info):
    """Subject sections the way the card builds them: (group, index) in first-seen order."""
    out = []
    for c in info["choices"]:
        if c.get("group") and (c["group"], c.get("index")) not in out:
            out.append((c["group"], c.get("index")))
    return out


class TestVocabulary:
    def test_per_individual_lists_come_from_the_namespace(self):
        v = vocabulary()
        assert v.get("person.hairstyle").individual and v.get("person.outfit.casual").individual
        assert v.get("animal.dog_breed").individual
        assert not v.get("scene.weather").individual and not v.get("lighting." + next(
            lid.split(".", 1)[1] for lid in v.leaves if lid.startswith("lighting."))).individual


class TestSubjectIds:
    @pytest.mark.parametrize("cid, want", [
        ("friends[2].age", ("friends", 2, "age")),
        ("woman1.hair", ("woman", 1, "hair")),
        ("woman_2.hair", ("woman", 2, "hair")),
        ("mother.outfit", ("mother", None, "outfit")),
        ("friends[2].outfit.colours", ("friends", 2, "outfit.colours")),
        ("team2[1].age", ("team2", 1, "age")),
        ("outfit", None), ("outfit.colours", None), ("param.steps", None),
    ])
    def test_whose_detail_an_id_names(self, cid, want):
        assert subject_of(cid) == want


class TestShapes:
    """A table of program shapes: what the card gets, and what validation says."""

    def test_two_people_written_by_hand_get_a_header_each(self):
        src, checked, _ = written(hand(("woman1", [AGE, STYLE, OUTFIT]), ("woman2", [AGE, STYLE, OUTFIT])),
                                  "two women chatting at a cafe")
        info = checked["info"]
        assert not subject_problems(checked)
        assert sections(info) == [("woman", 1), ("woman", 2)]
        assert by_id(info)["woman2.hairstyle"]["attr"] == "hairstyle"
        assert by_id(info)["woman1.outfit.colours"]["group"] == "woman"  # a look's colours stay with its wearer
        assert "group" not in by_id(info)["place"]  # the scene is no one's
        assert {g["id"]: g["label"] for g in info["groups"]}["woman"] == "Woman"

    def test_three_friends_in_a_loop(self):
        src, checked, _ = written(loop("friends", 3, [AGE, ETH, STYLE]), "three friends laughing on a beach")
        assert not subject_problems(checked)
        assert sections(checked["info"]) == [("friends", 1), ("friends", 2), ("friends", 3)]
        assert {g["id"]: g["label"] for g in checked["info"]["groups"]}["friends"] == "Friends"

    def test_a_couple_sharing_one_descent_is_rejected_and_told_the_loop(self):
        src, checked, _ = written(loop("couple", 2, [STYLE], outside=[("ethnicity", ETH)]), "a couple dancing")
        said = subject_problems(checked)
        assert said and 'pick("ethnicity")' in said[0] and 'pick(f"couple[{i+1}].ethnicity"' in said[0]
        assert "shared=True" in said[0]  # the way out when the user asked for sameness

    def test_a_family_each_child_draws_their_own_age(self):
        src = loop("children", 2, [AGE, STYLE], extra_lines=[
            f"m = {bound('mother.age', AGE)}", f"f = {bound('father.age', AGE)}", 'emit(m, f)'])
        src, checked, _ = written(src, "a family with two kids walking a dog")
        info = checked["info"]
        assert not subject_problems(checked)
        assert sections(info) == [("mother", None), ("father", None), ("children", 1), ("children", 2)]
        people = {person_of(c["id"]) for c in info["choices"] if c.get("cls") == AGE}
        assert people == {"mother", "father", "children[1]", "children[2]"}
        entry = {"choices": info["choices"], "filters": {"children[1].age_band": ["5–7-year-old"],
                                                         "children[2].age_band": ["11–12-year-old"],
                                                         "mother.age": ["35–39-year-old"]}}
        assert dict(program_minors(entry)) == {"children[1]": ("5–7-year-old",), "children[2]": ("11–12-year-old",)}

    def test_a_person_and_an_animal(self):
        src, checked, _ = written(hand(("woman", [STYLE, OUTFIT]), ("dog", [DOG])), "a woman walking her dog")
        assert not subject_problems(checked)
        assert sections(checked["info"]) == [("woman", None), ("dog", None)]
        flat = hand(("woman", [STYLE, OUTFIT]), extra_lines=[f"breed = {bound('breed', DOG)}"])
        said = subject_problems(written(flat, "a woman walking her dog")[1])
        assert said and 'pick("breed")' in said[0] and "woman.breed" in said[0]

    def test_named_and_unnamed_subjects_together(self):
        src = loop("friends", 2, [STYLE], extra_lines=[f"a = {bound('anna.hairstyle', STYLE)}", "emit(a)"])
        src, checked, _ = written(src, "Anna and her two friends at a market")
        assert not subject_problems(checked)
        assert sections(checked["info"]) == [("anna", None), ("friends", 1), ("friends", 2)]

    def test_a_detail_asked_to_be_the_same_is_one_shared_pick(self):
        same = f"outfit = {bound('outfit', OUTFIT, extra=', shared=True')}"
        src, checked, _ = written(hand(("twin1", [STYLE]), ("twin2", [STYLE]), extra_lines=[same]),
                                  "identical twins in matching outfits")
        info = checked["info"]
        assert not subject_problems(checked)
        assert by_id(info)["outfit"].get("shared") is True and "group" not in by_id(info)["outfit"]
        assert sections(info) == [("twin", 1), ("twin", 2)]
        unmarked = written(hand(("twin1", [STYLE]), ("twin2", [STYLE]),
                                extra_lines=[f"outfit = {bound('outfit', OUTFIT)}"]), "two sisters")[1]
        assert subject_problems(unmarked)  # shared without saying so: one outfit for both by accident

    def test_one_subject_has_no_headers(self):
        for src in (hand(("woman", [AGE, STYLE, OUTFIT])), loop("people", 1, [AGE, STYLE])):
            src, checked, _ = written(src, "a woman reading in a library")
            info = checked["info"]
            assert not subject_problems(checked)
            assert sections(info) == [] and not any(c.get("shared") for c in info["choices"])
        plain = hand(("x", []), extra_lines=[f"h = {bound('hairstyle', STYLE)}", f"o = {bound('outfit', OUTFIT, extra=', shared=True')}"])
        info = written(plain, "a woman")[1]["info"]
        assert sections(info) == [] and not any(c.get("shared") for c in info["choices"])

    def test_flat_ids_that_name_a_subject_are_repaired_in_code(self):
        src = hand(extra_lines=[f"a = {bound('mother_age', AGE)}", f"b = {bound('mother_outfit', OUTFIT)}",
                                f"c = {bound('daughter_age', AGE)}", f"d = {bound('daughter_hairstyle', STYLE)}"])
        fixed, checked, notes = written(src, "a mother and her daughter baking")
        assert '"mother.age"' in fixed and '"daughter.hairstyle"' in fixed and notes
        assert not subject_problems(checked)
        assert sections(checked["info"]) == [("mother", None), ("daughter", None)]
        beside = hand(("woman1", [AGE]), ("woman2", [AGE]), extra_lines=[f"o = {bound('woman1_outfit', OUTFIT)}"])
        fixed, checked, _ = written(beside, "two women")
        assert '"woman1.outfit"' in fixed and not subject_problems(checked)
        work = hand(extra_lines=[f"a = {P('chef_details', about='the chef', seed='a stained apron')}",
                                 f"b = {bound('chef_expression', 'person.expression')}",
                                 f"c = {P('waiter_details', about='the waiter', seed='a black vest')}",
                                 f"d = {bound('waiter_expression', 'person.expression')}"])
        fixed = written(work, "a chef and a waiter arguing")[0]
        assert '"chef.expression"' in fixed and '"waiter.details"' in fixed
        indexed = loop("friends", 2, [AGE], extra_lines=[f"h = {bound('friends_2_hairstyle', STYLE)}", "emit(h)"])
        assert '"friends[2].hairstyle"' in written(indexed, "two friends")[0]

    def test_numbered_plain_ids_are_numbered_subjects(self):
        lines = [f"{v} = {bound(v, cls)}" for v, cls in (("eth1", ETH), ("eth2", ETH), ("age_1", AGE), ("age_2", AGE))]
        couple = 'couple = group("couple", 2, label="Couple", line=1)\n' + "\n".join(lines) + \
                 '\nfor i in range(couple):\n    emit("a partner")\nemit(eth1, eth2, age_1, age_2)\n'
        fixed, checked, _ = written(couple, "a couple dancing")
        assert '"couple[1].eth"' in fixed and '"couple[2].age"' in fixed and not subject_problems(checked)
        assert sections(checked["info"]) == [("couple", 1), ("couple", 2)]
        alone = "\n".join(lines) + "\nemit(eth1, eth2, age_1, age_2)\n"
        assert '"person[2].eth"' in written(alone, "two women")[0]
        shots = 'a = pick("shot1", about="a shot", seed=["wide"], label="Shot", phase=1, added=True)\n' \
                'b = pick("shot2", about="a shot", seed=["close"], label="Shot", phase=1, added=True)\nemit(a, b)\n'
        assert prep.fix_subjects(shots)[1] == []  # numbered scene details are no one's

    def test_one_detail_list_used_once_is_no_subject(self):
        src = hand(extra_lines=[f"a = {bound('hair_color', HAIR)}", f"b = {bound('top_outfit', OUTFIT)}"])
        fixed, _, notes = written(src, "a woman")
        assert '"hair_color"' in fixed and '"top_outfit"' in fixed and not notes

    def test_a_pick_in_a_group_loop_with_a_plain_id_becomes_the_members(self):
        src = ('friends = group("friends", 3, label="Friends", line=1)\n'
               "for i in range(friends):\n"
               f"    a = {bound('age', AGE)}\n"
               "    h = " + bound('f"hair_{i}"', STYLE) + "\n"
               '    emit(a, h, ";")\n')
        fixed, checked, _ = written(src, "three friends")
        assert 'f"friends[{i+1}].age"' in fixed and 'f"friends[{i+1}].hair"' in fixed
        assert sections(checked["info"]) == [("friends", 1), ("friends", 2), ("friends", 3)]

    def test_a_partly_grouped_program_is_rejected(self):
        """The reported bug: some details under the people, the hairstyle left at the top."""
        src = hand(("woman1", [AGE, OUTFIT]), ("woman2", [AGE, OUTFIT]),
                   extra_lines=[f"h = {bound('hairstyle', STYLE)}"])
        said = subject_problems(written(src, "two women at a cafe")[1])
        assert said and 'pick("hairstyle")' in said[0] and "woman1.hairstyle, woman2.hairstyle" in said[0]
        looped = loop("friends", 3, [AGE, OUTFIT], outside=[("hairstyle", STYLE)])
        said = subject_problems(written(looped, "three friends")[1])
        assert said and 'pick(f"friends[{i+1}].hairstyle"' in said[0]
        one_named = hand(("man", [AGE]), extra_lines=[f"h = {bound('hairstyle', STYLE)}"])
        assert subject_problems(written(one_named, "a man and a woman on a train")[1])

    def test_a_wildcards_own_id_is_never_renamed(self):
        src = hand(("friends1", [AGE]), ("friends2", [AGE]),
                   extra_lines=['h = pick("friends_hats", about="their winter hats", seed=["a red beanie"], '
                                'label="Hats", phase=1, line=1)'])
        assert '"friends_hats"' in prep.fix_subjects(src, "two friends wearing {{friends hats}}")[0]


class TestChoicesRoute:
    """What the client gets: every per-subject choice carries its subject (group, index,
    attr), the groups carry labels, in a stable order; shared and scene choices carry none."""

    async def test_the_prepare_route_returns_subjects_in_order(self, monkeypatch):
        import httpx
        from fastapi import FastAPI
        import routes.generation as gen
        from routes import prompt_programs as route

        src, checked, _ = written(hand(("woman", [STYLE]), ("man", [STYLE, OUTFIT]),
                                       extra_lines=[f"o = {bound('outfit', OUTFIT, extra=', shared=True')}"]),
                                  "a man and a woman in matching outfits")
        entry = prep._entry(key="k", tool_id="t", ctx={"mode": "prose"}, elaborate=True, prompt="p", enhanced="",
                            exact={}, source=src, checked=checked, params={}, loras=[])

        async def ensure(**kw):
            return entry

        monkeypatch.setattr(prep, "ensure_program", ensure)
        monkeypatch.setattr(gen, "prompt_enhance_context", lambda *a: {"program_supported": True, "mode": "prose"})
        app = FastAPI()
        app.include_router(route.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            body = (await c.post("/api/prompt-programs/prepare", json={"tool_id": "t", "prompt": "p"})).json()
        rows = [(c["id"], c.get("group"), c.get("index"), c.get("attr"), c.get("shared")) for c in body["choices"]]
        assert rows == [
            ("woman.hairstyle", "woman", None, "hairstyle", None),
            ("man.hairstyle", "man", None, "hairstyle", None),
            ("man.outfit", "man", None, "outfit", None),
            ("man.outfit.colours", "man", None, "outfit.colours", None),
            ("outfit", None, None, None, True),
            ("outfit.colours", None, None, None, None),
            ("place", None, None, None, None),
        ]
        assert [(g["id"], g["label"]) for g in body["groups"]] == [("woman", "Woman"), ("man", "Man")]
