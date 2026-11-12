"""Fluent draws: pick specs, the static dependency rule, the options interface, the
phased draw loop, and parity of the path for programs without specs."""

import hashlib
import json

from prompt_programs.runtime import LoraInfo, discover, run

# --------------------------------------------------------------------------- parity fixtures
# Programs written before pick specs existed. Their draws must stay byte-identical:
# the hashes below were taken from run()/discover() before the draw path was added.

PARITY_TRAIN = '''
weather = pick("weather", ["rainy", "foggy", "bright"], label="Weather", source="list", line=1)
umbrella = None
if weather == "rainy":
    umbrella = pick("umbrella", ["holding a clear umbrella", "holding a black umbrella"], label="Umbrella", added=True)
hair = pick_lora("hairstyle", ["Curtain bangs", "Wolf cut"], label="Hairstyle", line=3)
clothing = pick("clothing", by=weather, label="Clothing", line=2, options={
    "rainy": ["a trench coat", "a rain jacket"], "foggy": ["a wool coat"], "bright": ["a linen shirt"]})
param("guidance", 3.5, 5.5, line=4)
param("steps", 20, 30)
emit("A woman waiting for a train on a", weather, "morning, wearing", clothing, ",", umbrella, ". [Shot on Portra 400]")
'''

PARITY_LOOP = '''
ages = []
for i in range(group("people", 3, label="People")):
    a = pick(f"people[{i+1}].age", ["20s", "40s", "70s", "teens"], exclude=ages)
    ages.append(a)
    pick(f"people[{i+1}].shirt", ["red", "blue", "green", "white", "black"], hidden=(i == 2))
emit("Friends:", ", ".join(ages))
'''

PARITY_PLATFORM = '''
weather = pick("weather", ["rainy", "bright"], label="Weather", source="list", line=1)
expression = pick("expression", [
    "a faint private smile on her face as she glances down the tracks",
    "her brow slightly furrowed as she checks the time on her phone",
    "laughing quietly at a message on her phone",
    "eyes half-closed, tired, her head tilted against a pillar",
], label="Expression", line=2)
coat = {"rainy": "a belted olive trench coat", "bright": "a light camel trench coat"}[weather]
ground = {"rainy": "Puddles reflect the station lights.", "bright": "Low sun casts long shadows."}[weather]
emit("A candid photograph of a woman on a", weather, "morning. She wears", coat, ",", expression, ".", ground)
'''

PARITY_LORAS = [LoraInfo("Curtain bangs", "loras/cb.safetensors", 0.8, "cbangs"),
                LoraInfo("Wolf cut", "loras/wc.safetensors", 0.9, "wolfcut")]
PARITY_PARAMS = {"guidance", "steps"}

PARITY_VARIANTS = {
    "train": (PARITY_TRAIN, [
        {},
        {"pins": {"weather": ["rainy"], "hairstyle": ["Wolf cut"]}},
        {"pins": {"weather": ["snowy"]}},
        {"pins": {"clothing": ["a wool coat", "a linen shirt"]}},
        {"edits": {"weather": {"add": ["sleet"]}, "umbrella": {"off": True}, "clothing": {"remove": ["a trench coat"]}}},
        {"edits": {"weather": {"remove": ["rainy", "foggy", "bright"]}}},
        {"fixed": {"weather": "foggy", "clothing": "a wool coat", "param.guidance": 4.2}},
    ]),
    "loop": (PARITY_LOOP, [
        {},
        {"pins": {"people[2].age": ["70s"]}},
        {"edits": {"people[1].age": {"remove": ["20s"], "add": ["80s"]}}},
    ]),
    "platform": (PARITY_PLATFORM, [
        {},
        {"pins": {"expression": ["laughing quietly at a message on her phone"]}},
    ]),
}


def parity_digest(name: str) -> str:
    source, variants = PARITY_VARIANTS[name]
    out = []
    for v in variants:
        for seed in range(40):
            r = run(source, seed, v.get("pins"), PARITY_LORAS, PARITY_PARAMS, v.get("fixed"), v.get("edits"))
            out.append([r.to_dict(), r.groups, [d.options for d in r.draws], [d.pinned for d in r.draws]])
    out.append(discover(source, PARITY_LORAS, PARITY_PARAMS))
    blob = json.dumps(out, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


PARITY_HASHES = {
    "train": "9faca3cb9b75fffa94e437a753df9d5db2a07883f1088a4356dbe93b7f66e365",
    "loop": "3866b1b1a5f1ba75caa538ab331c3f4df23cb060cb43c63a941e94af9f71d52c",
    "platform": "915161ea3b9cd3738e5bc5854aa7a37fb190395ac5e9f7137d372c82370bb6ee",
}


class TestCompatibilityParity:
    def test_runs_and_discovery_are_unchanged(self):
        for name, want in PARITY_HASHES.items():
            assert parity_digest(name) == want, name


# --------------------------------------------------------------------------- the draw path

import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402

from prompt_programs import prepare as prep  # noqa: E402
from prompt_programs.draws import (  # noqa: E402
    DrawAborted, DrawResult, LiteralOptions, analyze, draw, fixed_text, uses_draws,
)
from prompt_programs.runtime import ProgramError  # noqa: E402

PORTRAIT = '''
era = pick("era", ["1920s", "1970s", "1990s"], label="Era", source="list", phase=1, line=1)
role = pick("role", about="the woman's job", phase=1, seed=["jazz singer", "nurse", "pilot"])
hair = pick("hair", by=era, label="Hairstyle", about="her hairstyle", phase=2, options={
    "1920s": ["finger waves", "a sleek bob"], "1970s": ["feathered hair", "an afro"], "1990s": ["a pixie cut", "a messy bun"]})
light = pick("light", about="the lighting", phase=2, seed=["soft window light", "neon light"])
ground = {"1920s": "a smoky club", "1970s": "a disco", "1990s": "a grunge bar"}[era]
emit("A portrait of a", role, "in the", era, "with", hair, ",", light, ", in", ground)
'''

RAIN = '''
weather = pick("weather", ["rainy", "foggy", "bright"], label="Weather", source="list", phase=1)
umbrella = None
if weather == "rainy":
    umbrella = pick("umbrella", ["a clear umbrella", "a black umbrella"], label="Umbrella", phase=2)
emit("A woman on a", weather, "morning", umbrella)
'''

FRIENDS = '''
ages = []
for i in range(group("people", 3, label="People")):
    a = pick(f"people[{i+1}].age", ["20s", "40s", "70s", "teens"], label="Age", phase=1, exclude=ages)
    ages.append(a)
emit("Friends:", ", ".join(ages))
'''

HAIRS = HAIR_ERAS = {"1920s": {"finger waves", "a sleek bob"}, "1970s": {"feathered hair", "an afro"},
                     "1990s": {"a pixie cut", "a messy bun"}}




def by_id(result):
    return {d.id: d for d in result.draws}


class TestSpecsAndDiscovery:
    def test_only_programs_with_specs_take_the_draw_path(self):
        assert uses_draws(PORTRAIT) and uses_draws(RAIN)
        assert not uses_draws(PARITY_TRAIN) and not uses_draws(PARITY_LOOP) and not uses_draws("emit(")

    def test_discovery_registers_specs_and_static_deps(self):
        info = discover(PORTRAIT)
        c = {x["id"]: x for x in info["choices"]}
        assert c["role"]["phase"] == 1 and c["role"]["about"] == "the woman's job"
        assert c["role"]["options"] == ["jazz singer", "nurse", "pilot"]  # seeds stand in for options
        assert c["hair"]["phase"] == 2 and c["hair"]["deps"] == ["era"] and c["hair"]["follows"] == "era"
        assert "deps" not in c["era"]

    def test_a_pick_with_no_pool_is_still_a_choice(self):
        src = 'mood = pick("mood", about="her mood", phase=1)\nemit("A woman", mood)\n'
        c = {x["id"]: x for x in discover(src)["choices"]}
        assert c["mood"]["options"] == [] and c["mood"]["about"] == "her mood"

    def test_older_programs_record_no_spec_fields(self):
        r = run(PARITY_TRAIN, 3, None, PARITY_LORAS, PARITY_PARAMS)
        assert all("phase" not in d and "about" not in d for d in r.to_dict()["draws"])


class TestDependencyRule:
    @pytest.mark.parametrize("src", [
        PORTRAIT, RAIN, FRIENDS,
        # derived text through a subscript only reaches the prompt: no pick depends on it
        'w = pick("w", ["rain", "sun"], phase=1)\nground = {"rain": "wet", "sun": "dry"}[w]\nemit(ground, w)\n',
        # a lookup that feeds a later phase's options
        'w = pick("w", ["rain", "sun"], phase=1)\nL = {"rain": ["gray"], "sun": ["gold"]}\n'
        'light = pick("light", L[w], phase=2)\nemit(w, light)\n',
        # a count from an earlier phase
        'n = pick("n", ["1", "2"], phase=1)\nfor i in range(group("p", int(n))):\n'
        '    pick(f"p[{i+1}].hat", ["a cap", "a hat"], phase=2)\nemit("x", n)\n',
    ])
    def test_accepts(self, src):
        assert analyze(src).phased

    @pytest.mark.parametrize("src, msg", [
        ('e = pick("era", ["a", "b"], phase=1)\nh = pick("hair", by=e, options={"a": ["x"], "b": ["y"]}, phase=1)\nemit(e, h)\n',
         'uses pick\\("era"\\) \\(phase 1\\) in its by='),
        ('w = pick("weather", ["rain", "sun"], phase=2)\nif w == "rain":\n    u = pick("umbrella", ["a", "b"], phase=2)\nemit(w)\n',
         "in an if test above it"),
        ('w = pick("weather", ["rain", "sun"], phase=1)\nL = {"rain": ["gray"], "sun": ["gold"]}\n'
         'light = pick("light", L[w], phase=1)\nemit(w, light)\n', "in its options"),
        ('n = pick("n", ["1", "2"], phase=1)\nfor i in range(group("p", int(n))):\n'
         '    pick(f"p[{i+1}].hat", ["a cap", "a hat"], phase=1)\nemit("x", n)\n', "the loop around it"),
        ('a = pick("a", ["x", "y"], phase=1)\nb = pick("b", [a, "z"], phase=1)\nemit(a, b)\n', "in its options"),
        ('a = pick("a", ["x", "y"], phase=2)\nb = pick("b", ["x", "y"], phase=1, exclude=[a])\nemit(a, b)\n',
         "excludes values of"),
        ('ages = []\nfor i in range(3):\n    a = pick(f"p[{i}]", [x for x in ["1", "2", "3"] if x not in ages], phase=1)\n'
         '    ages.append(a)\nemit(ages)\n', "uses its own earlier values"),
        ('p = pick\nemit(p("a", ["x"], phase=1))\n', "call pick"),
        ('n = 1\nemit(pick("a", ["x"], phase=n))\n', "phase= must be a whole number"),
        ('emit(pick("a", ["x"], phase=1), pick("b", ["y"]))\n', 'pick\\("b"\\) needs phase='),
        ('emit(pick("a", about="her mood", phase=1))\n', "has no options"),
        ('emit(pick("a", ["x"], phase=1, color=1))\n', 'no argument "color"'),
    ])
    def test_rejects(self, src, msg):
        with pytest.raises(ProgramError, match=msg):
            analyze(src)

    def test_the_message_says_how_to_fix_it(self):
        src = PORTRAIT.replace('phase=2, options', 'phase=1, options')
        with pytest.raises(ProgramError) as e:
            analyze(src)
        assert 'give "era" a lower phase than "hair"' in str(e.value)

    def test_validate_accepts_a_phased_program(self):
        checked = prep.validate(PORTRAIT, "A portrait of a woman", [], set())
        assert {c["id"] for c in checked["info"]["choices"]} == {"era", "role", "hair", "light"}

    def test_validate_sends_it_back(self):
        src = PORTRAIT.replace('phase=2, options', 'phase=1, options')
        with pytest.raises(ProgramError, match="lower phase"):
            prep.validate(src, "A portrait", [], set())


class TestDispatch:
    def _entry(self, program, **kw):
        return {"key": "k", "program": program, "loras": [], "params": {}, **kw}

    def test_older_programs_run_exactly_as_before(self):
        entry = self._entry(PARITY_TRAIN, loras=[vars(lo) for lo in PARITY_LORAS], params={"guidance": {}, "steps": {}})
        for seed in range(10):
            got = prep.realize(entry, seed=seed, pins={"weather": "rainy"})
            want = run(PARITY_TRAIN, seed, {"weather": ["rainy"]}, PARITY_LORAS, {"guidance", "steps"})
            assert type(got) is not DrawResult and got.to_dict() == want.to_dict()

    def test_programs_with_specs_take_the_draw_path(self):
        got = prep.realize(self._entry(PORTRAIT), seed=4)
        assert isinstance(got, DrawResult) and got.to_dict()["draw_revision"]["engine"] == "draws-2"


class TestDrawLoop:
    def test_draws_come_from_the_pools(self):
        prompts = set()
        for seed in range(40):
            r = draw(PORTRAIT, seed)
            d = by_id(r)
            assert d["hair"].value in HAIR_ERAS[d["era"].value]
            assert d["hair"].phase == 2 and d["role"].about == "the woman's job"
            prompts.add(r.prompt)
        assert len(prompts) > 8

    def test_same_revision_seed_and_pins_give_the_same_prompt(self):
        a = draw(PORTRAIT, 9, pins={"light": ["neon light"]})
        b = draw(PORTRAIT, 9, pins={"light": ["neon light"]})
        assert a.to_dict() == b.to_dict()
        rev = a.revision
        assert rev["engine"] and rev["program"] and "judge" not in rev and "rarity" not in rev
        assert rev["pools"]["role: the woman's job"] == 3
        edited = draw(PORTRAIT, 9, pins={"light": ["neon light"]}, edits={"role": {"add": ["a chemist"]}})
        assert edited.revision["id"] != rev["id"] and edited.revision["pools"]["role: the woman's job"] == 4

    def test_draws_do_not_depend_on_hash_order(self):
        code = ("import json\nfrom prompt_programs.draws import draw\nimport tests.test_prompt_program_draws as t\n"
                "print(json.dumps([draw(t.PORTRAIT, s, pins={'light': ['neon light']}).to_dict()"
                " for s in range(6)] + [draw(t.FRIENDS, s).to_dict() for s in range(6)], sort_keys=True))")
        outs = set()
        for hs in ("1", "2"):
            env = {**os.environ, "PYTHONHASHSEED": hs}
            outs.add(subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                                    check=True, cwd=os.path.dirname(os.path.dirname(__file__))).stdout)
        assert len(outs) == 1

class TestMasking:
    """fixed_text(): the program's text with every pick masked, for the option writer."""

    def test_every_pick_and_the_text_derived_from_it_is_masked(self):
        text = fixed_text(PORTRAIT)
        assert "[Era]" in text and "[Role]" in text and "[Hairstyle]" in text
        for era, ground in (("1920s", "smoky club"), ("1970s", "disco"), ("1990s", "grunge bar")):
            assert era not in text and ground not in text  # derived text is masked with its source

    def test_a_pick_inside_an_f_string_is_masked_in_place(self):
        src = ('a = pick("animal", ["cat", "dog"], phase=1)\nc = pick("color", ["red", "blue"], phase=2)\n'
               'emit(f"A {c} collar on a sleeping {a}.")\n')
        assert fixed_text(src) == "A [Color] collar on a sleeping [Animal]."

    def test_a_list_passed_to_emit_is_masked_once(self):
        src = ('a = pick("animal", ["cat", "dog"], phase=1)\nc = pick("color", ["red", "blue"], phase=2)\n'
               'emit("A", [a, c], "collar.")\n')
        text = fixed_text(src)  # no candidate leaks; the list is masked conservatively
        assert all(v not in text for v in ("cat", "dog", "red", "blue")) and text.startswith("A [Animal]")


class TestPins:
    def test_pins_come_first_and_upstream_keeps_them_satisfiable(self):
        for seed in range(30):
            d = by_id(draw(PORTRAIT, seed, pins={"hair": ["an afro"]}))
            assert d["era"].value == "1970s" and d["hair"].value == "an afro" and d["hair"].pinned

    def test_upstream_keeps_a_pinned_branch_switched_on(self):
        for seed in range(20):
            d = by_id(draw(RAIN, seed, pins={"umbrella": ["a black umbrella"]}))
            assert d["weather"].value == "rainy" and d["umbrella"].value == "a black umbrella"

    def test_an_unsatisfiable_pin_aborts_and_reports_it(self):
        # a hairstyle the choice offers, but for no era the pinned eras allow
        with pytest.raises(DrawAborted) as e:
            draw(PORTRAIT, 1, pins={"hair": ["an afro"], "era": ["1920s", "1990s"]})
        assert e.value.reason == "pin" and e.value.choice_id == "hair" and "Hairstyle" in str(e.value)

    def test_a_pin_the_choice_offers_nowhere_is_ignored(self):
        # made on an earlier program's options for this choice: the draw is the unticked one
        assert draw(PORTRAIT, 1, pins={"hair": ["a mohawk"]}).prompt == draw(PORTRAIT, 1).prompt

    def test_a_pinned_value_is_not_taken_by_a_looped_peer(self):
        for seed in range(30):
            d = by_id(draw(FRIENDS, seed, pins={"people[3].age": ["70s"]}))
            assert d["people[3].age"].value == "70s"
            assert sorted(x.value for x in d.values()) == sorted(set(x.value for x in d.values()))

    def test_a_pin_on_a_choice_turned_off_is_dropped(self):
        d = by_id(draw(PORTRAIT, 1, pins={"light": ["neon light"]}, edits={"light": {"off": True}}))
        assert "light" not in d

    def test_a_subset_pin_narrows_the_pool(self):
        for seed in range(20):
            assert by_id(draw(PORTRAIT, seed, pins={"era": ["1920s", "1990s"]}))["era"].value in ("1920s", "1990s")


class TestExclude:
    def test_replayed_values_respect_exclude(self):
        r = draw(FRIENDS, 3, fixed={"people[1].age": "40s", "people[2].age": "40s"})
        d = by_id(r)
        assert d["people[1].age"].value == "40s" and d["people[2].age"].value != "40s"
        assert not d["people[1].age"].pinned  # preserved, not the user's pin


class TestEmptyPool:
    def test_an_emptied_user_list_aborts_before_its_value_is_used(self):
        src = 'era = pick("era", ["1920s", "1970s"], label="Era", source="list", phase=1)\nemit(era.upper())\n'
        with pytest.raises(DrawAborted) as e:
            draw(src, 1, edits={"era": {"remove": ["1920s", "1970s"]}})
        assert str(e.value) == "Nothing left to draw for Era." and e.value.reason == "empty"
        assert e.value.to_dict()["code"] == "nothing_to_draw" and e.value.to_dict()["choice_id"] == "era"

    def test_an_emptied_generated_pick_asks_for_more(self):
        edits = {"role": {"remove": ["jazz singer", "nurse", "pilot"]}}
        opts = LiteralOptions(edits)
        with pytest.raises(DrawAborted, match="Nothing left to draw for Role"):
            draw(PORTRAIT, 1, edits=edits, options=opts)
        assert opts.requests == [("role: the woman's job", "high")]

    def test_exhausted_exclusions_abort(self):
        src = FRIENDS.replace('["20s", "40s", "70s", "teens"]', '["20s", "40s"]')
        with pytest.raises(DrawAborted, match="Nothing left to draw for Age") as e:
            draw(src, 1)
        assert e.value.choice_id == "people[3].age"

    def test_realize_raises_it_for_the_route(self):
        entry = {"key": "k", "program": PORTRAIT, "loras": [], "params": {}}
        with pytest.raises(DrawAborted):
            prep.realize(entry, seed=1, edits={"era": {"remove": ["1920s", "1970s", "1990s"]}})

class TestLorasAndParams:
    def test_loras_and_params_draw_once_and_hold(self):
        src = ('hair = pick_lora("hairstyle", ["Curtain bangs", "Wolf cut"], label="Hairstyle", phase=1)\n'
               'g = param("guidance", 3.5, 5.5)\nmood = pick("mood", about="her mood", phase=2, seed=["calm", "wry"])\n'
               'emit("A woman,", mood)\n')
        for seed in range(10):
            a = draw(src, seed, loras=PARITY_LORAS, tool_params=PARITY_PARAMS)
            b = draw(src, seed, loras=PARITY_LORAS, tool_params=PARITY_PARAMS)
            assert a.to_dict() == b.to_dict()
            assert 3.5 <= a.params["guidance"] <= 5.5
            assert a.prompt.startswith(("cbangs,", "wolfcut,")) and len(a.loras) == 1
