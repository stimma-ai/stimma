"""Prompt programs: the runtime, discovery, prepare (with a stubbed model) and the
per-job application of a run."""

import pytest

from prompt_programs import prepare as prep
from prompt_programs.runtime import LoraInfo, ProgramError, discover, run
from prompt_programs.store import ProgramStore

TRAIN = '''
weather = pick("weather", ["rainy", "foggy", "bright"], label="Weather", source="list", line=1)
umbrella = None
if weather == "rainy":
    umbrella = pick("umbrella", ["holding a clear umbrella", "holding a black umbrella"], label="Umbrella", added=True)
hair = pick_lora("hairstyle", ["Curtain bangs", "Wolf cut"], label="Hairstyle", line=3)
clothing = pick("clothing", by=weather, label="Clothing", line=2, options={
    "rainy": ["a trench coat", "a rain jacket"], "foggy": ["a wool coat"], "bright": ["a linen shirt"]})
param("guidance", 3.5, 5.5, line=4)
emit("A woman waiting for a train on a", weather, "morning, wearing", clothing, ",", umbrella, ". [Shot on Portra 400]")
'''
LORAS = [LoraInfo("Curtain bangs", "loras/cb.safetensors", 0.8, "cbangs"), LoraInfo("Wolf cut", "loras/wc.safetensors", 0.9, "wolfcut")]
PARAMS = {"guidance", "steps"}


class TestRuntime:
    def test_same_seed_same_result(self):
        a = run(TRAIN, 42, None, LORAS, PARAMS)
        b = run(TRAIN, 42, None, LORAS, PARAMS)
        assert a.prompt == b.prompt and [d.value for d in a.draws] == [d.value for d in b.draws]

    def test_seeds_vary(self):
        prompts = {run(TRAIN, s, None, LORAS, PARAMS).prompt for s in range(30)}
        assert len(prompts) > 5

    def test_pins_narrow_the_draw(self):
        for s in range(20):
            r = run(TRAIN, s, {"weather": ["rainy"], "hairstyle": ["Wolf cut"]}, LORAS, PARAMS)
            assert "rainy" in r.prompt and r.loras[0].name == "Wolf cut"
            assert any(d.id == "umbrella" for d in r.draws)

    def test_a_pin_outside_the_options_is_ignored(self):
        r = run(TRAIN, 1, {"weather": ["snowy"]}, LORAS, PARAMS)
        assert any(d.id == "weather" and d.value in ("rainy", "foggy", "bright") for d in r.draws)

    def test_fixed_replays_draws(self):
        first = run(TRAIN, 3, None, LORAS, PARAMS)
        fixed = {d.id: d.value for d in first.draws}
        again = run(TRAIN, 999, None, LORAS, PARAMS, fixed)
        assert again.prompt == first.prompt

    def test_user_edits(self):
        for s in range(20):
            r = run(TRAIN, s, {"weather": ["sleet"]}, LORAS, PARAMS, None,
                    {"weather": {"add": ["sleet"]}, "umbrella": {"off": True}, "clothing": {"remove": ["a trench coat"]}})
            assert "sleet" in r.prompt and not any(d.id == "umbrella" for d in r.draws)
            assert "trench coat" not in r.prompt

    def test_lora_trigger_and_weight(self):
        r = run(TRAIN, 5, {"hairstyle": ["Curtain bangs"]}, LORAS, PARAMS)
        assert r.prompt.startswith("cbangs,")
        assert r.loras[0].path == "loras/cb.safetensors" and r.loras[0].weight == 0.8

    def test_param_range(self):
        vals = {run(TRAIN, s, None, LORAS, PARAMS).params["guidance"] for s in range(40)}
        assert all(3.5 <= v <= 5.5 for v in vals) and len(vals) > 3

    def test_param_must_exist_and_not_be_added(self):
        with pytest.raises(ProgramError, match="no parameter"):
            run('param("cfg", 1, 2)\nemit("x")', 1, None, [], PARAMS)
        with pytest.raises(ProgramError, match="only vary when the user asks"):
            run('param("guidance", 1, 2, source="added")\nemit("x")', 1, None, [], PARAMS)

    def test_loop_with_distinct_values(self):
        src = '''
ages = []
for i in range(group("people", 3, label="People")):
    a = pick(f"people[{i+1}].age", ["20s", "40s", "70s"], exclude=ages)
    ages.append(a)
emit("Three friends:", ", ".join(ages))
'''
        for s in range(15):
            r = run(src, s)
            assert sorted(d.value for d in r.draws) == ["20s", "40s", "70s"]
            assert r.groups["people"]["count"] == 3

    @pytest.mark.parametrize("bad, msg", [
        ("import os\n", "Import is not allowed"),
        ("x = ().__class__\n", "is not allowed"),
        ("while True:\n    pass\n", "While is not allowed"),
        ("emit(open('x'))\n", "NameError"),
        ("for i in range(1000000000):\n    pass\nemit('x')\n", "ran too long"),
        ("pick('a', ['x'])\npick('a', ['y'])\nemit('z')\n", "used twice"),
        ("pick('a', ['x'])\n", "emitted no prompt"),
    ])
    def test_rejections(self, bad, msg):
        with pytest.raises(ProgramError, match=msg):
            run(bad, 1)


class TestDiscover:
    def test_structure(self):
        info = discover(TRAIN, LORAS, PARAMS)
        by = {c["id"]: c for c in info["choices"]}
        assert by["weather"]["source"] == "list" and by["weather"]["options"] == ["rainy", "foggy", "bright"]
        assert by["umbrella"]["parent"] == "weather" and by["umbrella"]["when"] == ["rainy"]
        assert by["umbrella"]["source"] == "added"
        assert by["clothing"]["follows"] == "weather"
        assert set(by["clothing"]["options"]) == {"a trench coat", "a rain jacket", "a wool coat", "a linen shirt"}
        assert by["hairstyle"]["kind"] == "lora"
        assert by["param.guidance"]["options"] == ["3.5", "5.5"]
        assert info["params"] == ["guidance"]


PROMPT = "A woman waiting for a train on a {rainy|foggy|bright} morning. [Shot on Portra 400]\n# Vary her clothing.\n# Hairstyle: use the curtain bangs or wolf cut LoRA.\n# Vary guidance between 3.5 and 5.5."


@pytest.fixture
def stub(monkeypatch, tmp_path):
    calls = []

    async def fake_ask(messages, project_id):
        calls.append(messages)
        return replies.pop(0)

    async def fake_candidates(tool_id, items, profile_id):
        return list(LORAS), {}

    replies = []
    monkeypatch.setattr(prep, "_ask_model", fake_ask)
    monkeypatch.setattr(prep, "lora_candidates", fake_candidates)
    monkeypatch.setattr(prep, "_store", lambda profile_id: ProgramStore(tmp_path))
    monkeypatch.setattr("prompt_pipeline._profile_wildcards_and_segments", lambda profile_id: ([], []))
    return calls, replies


SCHEMA = {"guidance": {"type": "number", "minimum": 1, "maximum": 10}, "seed": {"type": "integer"}, "prompt": {"type": "string"}}


class TestPrepare:
    async def _ensure(self):
        return await prep.ensure_program(prompt=PROMPT, tool_id="t", model_name="m", schema_props=SCHEMA,
                                         lora_items=[], project_id=None, profile_id="p")

    async def test_prepares_once_then_caches(self, stub):
        calls, replies = stub
        replies.append(f"```python\n{TRAIN}```")
        entry = await self._ensure()
        assert entry["params"] == {"guidance": {"type": "number", "minimum": 1, "maximum": 10}}
        assert {c["id"] for c in entry["choices"]} >= {"weather", "umbrella", "clothing", "hairstyle"}
        assert "[" not in entry["example"]
        again = await self._ensure()
        assert again["key"] == entry["key"] and len(calls) == 1

    async def test_retries_with_the_problem(self, stub):
        calls, replies = stub
        replies.append('```python\nemit("A woman on a platform")\n```')  # drops the user list + protected text
        replies.append(f"```python\n{TRAIN}```")
        entry = await self._ensure()
        assert entry["attempts"] == 2 and not entry["warnings"]
        feedback = calls[1][-1]["content"]
        assert "Shot on Portra 400" in feedback and "{rainy|foggy|bright}" in feedback

    async def test_a_pick_that_never_reaches_the_prompt_is_sent_back(self, stub):
        calls, replies = stub
        replies.append("```python\n" + TRAIN.replace('"morning, wearing", clothing,', '"morning,"') + "```")
        replies.append(f"```python\n{TRAIN}```")
        entry = await self._ensure()
        assert entry["attempts"] == 2
        assert 'pick("clothing")' in calls[1][-1]["content"]

    async def test_marks_asked_for_choices_as_from_text(self, stub):
        _, replies = stub
        replies.append("```python\n" + TRAIN.replace('label="Clothing", line=2', 'label="Clothing", added=True') + "```")
        entry = await self._ensure()
        clothing = next(c for c in entry["choices"] if c["id"] == "clothing")
        assert clothing["source"] == "text" and clothing["line"] == 2

    def test_lora_lookup_only_named(self):
        cands = LORAS + [LoraInfo("Anime lineart", "x", 1.0, "")]
        assert [lo.name for lo in prep.match_loras(PROMPT, cands)] == ["Curtain bangs", "Wolf cut"]
        assert prep.match_loras("a cat on a mat", cands) == []
        assert len(prep.match_loras("use one of my LoRAs", cands)) == 3

    def test_named_wildcards_become_lists(self):
        out = prep.expand_named_lists("a {{color}} car, {{style}}", [{"name": "color", "values": ["red", "blue"]}],
                                      [{"name": "style", "content": "film photo"}])
        assert out == "a {red|blue} car, film photo"


class TestApplyRun:
    def test_adds_loras_params_and_record(self):
        from routes.generation import _apply_program_run
        updated = {"prompt": "x", "loras": [{"lora": "loras/user.safetensors", "weight": 1.0}]}
        record = {"key": "k", "loras": [{"path": "loras/cb.safetensors", "weight": 0.8}], "params": {"guidance": 12.0, "steps": 3.7}}
        _apply_program_run(updated, record, {"guidance": {"type": "number", "maximum": 10}, "steps": {"type": "integer"}})
        assert updated["loras"][1] == {"lora": "loras/cb.safetensors", "weight": 0.8}
        assert updated["guidance"] == 10 and updated["steps"] == 3
        assert updated["prompt_program"]["key"] == "k"
