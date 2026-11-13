"""Fluent's fix pass: a small local judge scores each finished draw (one pick masked at
a time, the user's prompt included) and rerolls flagged picks. Slots draw from pools of
variants written straight into the profile's store; nothing here calls a model."""

import json

import pytest

from prompt_programs import program as prep
from prompt_programs import variant_pools as P
from prompt_programs.fix import (
    FixJudgeUnavailable, OnnxJudge, fix_draw, fix_judge, judged_picks, mask, realize_and_fix, score_draw,
)
from prompt_programs.judge import FluentSettings
from prompt_programs.variant_pools import Choice

PROFILE = "p"
USER = "A {nun|lifeguard|surgeon} wearing <outfit> under <light>"
OUTFIT = {"n": 1, "kind": "free", "label": "Outfit", "lead": " wearing", "category": "",
          "free": {"about": "what she wears", "kinds": [], "instead": [], "lists": []}}
LIGHT = {"n": 2, "kind": "free", "label": "Light", "lead": " under", "category": "",
         "free": {"about": "the light", "kinds": [], "instead": [], "lists": []}}
# Each slot's pool, by its words.
POOLS = {"outfit": ["a black habit", "a gray habit", "a red swimsuit", "green scrubs", "blue scrubs"],
         "light": ["dawn light", "noon sun", "moonlight", "candlelight"]}


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    """A profile whose variant store lives under tmp_path."""
    import app_dirs
    monkeypatch.setattr(app_dirs, "get_profile_dir", lambda pid="default": tmp_path / str(pid))
    monkeypatch.setattr(P, "_stores", {})
    monkeypatch.setattr(P, "_writers", {})
    return PROFILE


def entry_for(prompt=USER, readings=(OUTFIT, LIGHT), pools=POOLS, **kw):
    """A prepared entry: each read slot has a pool of `pools[words]`, written into the store as
    one first batch, and the user's first list is named "job"."""
    from prompt_programs.slots import compose, parse
    e = compose(parse(prompt), {r["n"]: r for r in readings}, {1: "Job"})
    for x in (*e["picks"], *e["choices"], *e["lists"]):
        if x["id"] == "list1":
            x["id"] = "job"
    store = P.store_for(PROFILE)
    for s in e["slots"]:
        if s["state"] != "ready":
            continue
        s["pool"] = P.pool_key("fake-model", s["words"], prompt, [])
        if not store.has(s["pool"]):
            store.append(s["pool"], {"batch": 0, "role": "first",
                                     "variants": [{"text": t, "seeds": {}} for t in pools[s["words"]]]})
    return {**e, "key": "fix1", **kw}


class Scorer:
    """A stubbed judge: P(wrong) by rule over (state, value); records every batch."""
    version = "stub-1"
    cut = 0.5

    def __init__(self, rule):
        self.rule = rule
        self.batches = []

    def p_wrong(self, items):
        self.batches.append(list(items))
        return [float(self.rule(it)) for it in items]


def draw(entry, seed, fixed=None, edits=None, pins=None, chosen=None):
    return prep.realize(entry, seed=seed, fixed=fixed, edits=edits, pins=pins, chosen=chosen, profile_id=PROFILE)


def judged(entry, seed, **kw):
    return realize_and_fix(entry, seed=seed, profile_id=PROFILE, **kw)


def redraw_for(entry, pins=None):
    return lambda s, fx, ed: draw(entry, s, fx, ed, pins)


def values(result):
    return {d.id: d.value for d in result.draws}


def seed_where(entry, pred, start=0):
    for s in range(start, start + 500):
        r = draw(entry, s)
        if pred(values(r)):
            return s, r
    raise AssertionError("no seed found")


# --------------------------------------------------------------------------- masking and batching

class TestScoring:
    def test_mask_matches_the_eval(self):
        assert mask("A nun under moonlight", "moonlight", "Light") == "A nun under [Light]"
        assert mask("a surgeon wearing scrubs, a focused surgeon", "surgeon", "Job") is None
        assert mask("a surgeon wearing scrubs, a focused surgeon", "surgeon", "Job", first=True) == \
            "a [Job] wearing scrubs, a focused surgeon"
        assert mask("aged 10, 100 candles", "10", "Age") == "aged [Age], 100 candles"

    def test_each_pick_is_masked_alone_in_one_batch_with_the_user_prompt(self):
        entry = entry_for()
        r = draw(entry, 1)
        sc = Scorer(lambda it: 0.0)
        scores = score_draw(sc, r, USER)
        assert set(scores) == {"job", "outfit", "light"} and len(sc.batches) == 1
        v = values(r)
        for it in sc.batches[0]:
            assert it.user_prompt == USER
            assert f"[{it.label}]" in it.state and it.value not in it.state
            others = [str(x) for k, x in v.items() if str(x) != it.value]
            assert all(o in it.state for o in others)
        assert {it.about for it in sc.batches[0] if it.label == "Outfit"} == {"outfit"}   # the slot's own words

    def test_pinned_kept_own_and_single_option_picks_are_not_judged(self):
        entry = entry_for()
        r = draw(entry, 2, pins={"job": ["nun"]})
        assert {d.id for d in judged_picks(r)} == {"outfit", "light"}
        assert {d.id for d in judged_picks(r, skip=["light"])} == {"outfit"}
        r = draw(entry, 2, chosen={"light": Choice(values=("moonlight", "noon sun"))})
        assert values(r)["light"] in ("moonlight", "noon sun") and {d.id for d in judged_picks(r)} == {"job", "outfit"}
        mine = {"outfit": Choice(add=("a yellow raincoat",))}
        s = next(s for s in range(50) if values(draw(entry, s, chosen=mine))["outfit"] == "a yellow raincoat")
        assert {d.id for d in judged_picks(draw(entry, s, chosen=mine))} == {"job", "light"}   # the user's own stands
        one = entry_for("a {only|only}", readings=())
        assert judged_picks(draw(one, 1)) == []

    def test_the_judge_and_the_highlight_find_a_value_as_the_tidy_writes_it(self):
        from prompt_programs.fix import prompt_view
        from prompt_programs.program import realized_text
        coat = "a olive trench coat over a cream sweater"   # the tidy writes "an olive ..."
        r = draw(entry_for("A woman wearing <outfit>.", readings=(OUTFIT,), pools={"outfit": [coat]}), 1)
        text = realized_text(r.prompt)
        assert text == "A woman wearing an olive trench coat over a cream sweater."
        assert mask(text, coat, "Outfit") == "A woman wearing [Outfit]."
        (s, e, cid), = prompt_view(r)["spans"]
        assert cid == "outfit" and text[s:e] == "an olive trench coat over a cream sweater"

    def test_onnx_style_input_pair(self, tmp_path):
        j = OnnxJudge(tiny_model(tmp_path))
        from prompt_programs.fix import Item
        a, b = j.texts(Item("A nun under [Light]", "Light", "", "moonlight", USER))
        assert a == f"The user wrote: {USER}\n\nPrompt: A nun under [Light]" and b == "Light: moonlight"
        a, b = j.texts(Item("A [Outfit]", "Outfit", "what she wears", "a habit", ""))
        assert a == "A [Outfit]" and b == "Outfit (what she wears): a habit"


# --------------------------------------------------------------------------- the loop

class TestFixLoop:
    def test_a_clean_draw_ships_as_is(self):
        entry = entry_for()
        r = draw(entry, 3)
        out, rec = fix_draw(r, judge=Scorer(lambda it: 0.1), redraw=redraw_for(entry), seed=3, user_prompt=USER, cut=0.5)
        assert out is r and rec["rerolls"] == 0 and not rec["unresolved"] and len(rec["rounds"]) == 1
        assert rec["judge"] == "stub-1" and set(rec["rounds"][0]["scores"]) == {"job", "outfit", "light"}

    def test_the_worst_flagged_pick_is_rerolled_and_the_rest_kept(self):
        entry = entry_for()
        s, r = seed_where(entry, lambda v: v["light"] == "moonlight")
        sc = Scorer(lambda it: 0.9 if it.value == "moonlight" else 0.6 if it.value == "noon sun" else 0.0)
        out, rec = fix_draw(r, judge=sc, redraw=redraw_for(entry), seed=s, user_prompt=USER, cut=0.5)
        v0, v1 = values(r), values(out)
        assert v1["light"] not in ("moonlight", "noon sun")
        assert v1["job"] == v0["job"] and v1["outfit"] == v0["outfit"]
        assert rec["rounds"][0]["rerolled"] == {"id": "light", "label": "Light", "value": "moonlight"}
        assert not rec["unresolved"] and all(len(b) == 3 for b in sc.batches)  # every round is one batch

    def test_rerolls_are_bounded_and_the_best_draw_ships(self):
        entry = entry_for()
        s, r = seed_where(entry, lambda v: v["light"] == "moonlight")
        bad = {"moonlight": 0.95, "dawn light": 0.9, "noon sun": 0.7, "candlelight": 0.8}
        out, rec = fix_draw(r, judge=Scorer(lambda it: bad.get(it.value, 0.0)), redraw=redraw_for(entry), seed=s,
                            user_prompt=USER, cut=0.5, rounds=2)
        assert rec["rerolls"] <= 2 and rec["unresolved"]
        seen = [h["scores"]["light"] for h in rec["rounds"]]
        assert values(out)["light"] == min(bad, key=lambda k: bad[k] if bad[k] in seen else 9)
        assert rec["rounds"][rec["chosen"]]["scores"]["light"] == min(seen)

    def test_a_list_with_nothing_left_stops_and_keeps_the_best(self):
        entry = entry_for()
        s, r = seed_where(entry, lambda v: v["job"] == "nun")
        out, rec = fix_draw(r, judge=Scorer(lambda it: 0.9 if it.label == "Job" else 0.0), redraw=redraw_for(entry),
                            seed=s, user_prompt=USER, cut=0.5, rounds=10)
        assert rec["unresolved"] and rec["rerolls"] == 2 and "stopped" in rec  # three jobs, all removed in turn
        assert values(out)["job"] == "nun"

    def test_a_slot_with_every_variant_refused_goes_in_as_its_words(self):
        entry = entry_for()
        s, r = seed_where(entry, lambda v: v["light"] == "moonlight")
        out, rec = fix_draw(r, judge=Scorer(lambda it: 0.9 if it.label == "Light" else 0.0), redraw=redraw_for(entry),
                            seed=s, user_prompt=USER, cut=0.5, rounds=6)
        tried = [h["rerolled"]["value"] for h in rec["rounds"] if "rerolled" in h]
        assert sorted(tried[:4]) == sorted(POOLS["light"]) and tried[4:] == ["light", "light"]   # each variant once
        assert rec["unresolved"] and rec["rerolls"] == 6 and "stopped" not in rec
        assert rec["rounds"][-1]["values"]["light"] == "light"
        assert values(out)["light"] == "moonlight"   # the first of the equally bad draws ships

    def test_values_the_user_kept_are_never_rerolled(self):
        entry = entry_for()
        s, r0 = seed_where(entry, lambda v: v["light"] == "moonlight")
        kept = {"light": "moonlight"}
        r = draw(entry, s, fixed=kept)
        out, rec = fix_draw(r, judge=Scorer(lambda it: 0.9 if it.value == "moonlight" else 0.0), redraw=redraw_for(entry),
                            seed=s, user_prompt=USER, cut=0.5, fixed=kept)
        assert values(out)["light"] == "moonlight" and rec["rerolls"] == 0 and "light" not in rec["rounds"][0]["scores"]

    def test_user_edits_survive_rerolls(self):
        entry = entry_for()
        edits = {"light": {"remove": ["candlelight"]}}
        s, r = seed_where(entry, lambda v: v["light"] == "moonlight")
        r = draw(entry, s, edits=edits)
        out, _ = fix_draw(r, judge=Scorer(lambda it: 0.9 if it.value in ("moonlight", "noon sun") else 0.0),
                          redraw=redraw_for(entry), seed=s, user_prompt=USER, cut=0.5, edits=edits)
        assert values(out)["light"] in ("dawn light", "moonlight", "noon sun")
        assert values(out)["light"] != "candlelight"

    def test_deterministic_by_seed(self):
        entry = entry_for()
        rule = lambda it: 0.9 if it.value in ("moonlight", "lifeguard") else 0.0  # noqa: E731
        outs = []
        for _ in range(2):
            r = draw(entry, 11)
            out, rec = fix_draw(r, judge=Scorer(rule), redraw=redraw_for(entry), seed=11, user_prompt=USER, cut=0.5)
            rec.pop("ms")
            outs.append((out.prompt, out.seed, json.dumps(rec, sort_keys=True)))
        assert outs[0] == outs[1]


# --------------------------------------------------------------------------- the real backend

def tiny_model(tmp_path, judge_json=None, io=None, probs=False, typed=True):
    """A cross-encoder-shaped ONNX model: P(wrong) is high when the second text (the
    pick's value) contains "moonlight". Inputs input_ids / attention_mask / token_type_ids,
    output logits [batch, 3]; with a WordLevel fast tokenizer."""
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper
    from tokenizers import Tokenizer, models, pre_tokenizers, processors

    words = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "moonlight", "nun", "light", "dawn", "noon", "sun", "candlelight"]
    vocab = {w: i for i, w in enumerate(words)}
    tok = Tokenizer(models.WordLevel(vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", pair="[CLS] $A [SEP] $B:1 [SEP]:1",
        special_tokens=[("[CLS]", vocab["[CLS]"]), ("[SEP]", vocab["[SEP]"])])
    d = tmp_path / "judge-model"
    d.mkdir(exist_ok=True)
    tok.save(str(d / "tokenizer.json"))
    emb = np.tile(np.array([[1.0, 0.0, 0.0]], dtype=np.float32), (len(words), 1))
    emb[vocab["moonlight"]] = [0.0, 0.0, 10.0]
    out = "probs" if probs else "logits"
    if typed:  # only the second segment (the pick) counts
        nodes = [
            helper.make_node("Gather", ["E", "input_ids"], ["g"]),
            helper.make_node("Cast", ["token_type_ids"], ["tf"], to=TensorProto.FLOAT),
            helper.make_node("Unsqueeze", ["tf", "ax"], ["tu"]),
            helper.make_node("Mul", ["g", "tu"], ["m"]),
            helper.make_node("ReduceMax", ["m"], ["z"], axes=[1], keepdims=0),
        ]
    else:  # a decoder-shaped model: every token counts, no token types
        nodes = [helper.make_node("Gather", ["E", "input_ids"], ["g"]),
                 helper.make_node("ReduceMax", ["g"], ["z"], axes=[1], keepdims=0)]
    nodes.append(helper.make_node("Softmax", ["z"], [out], axis=1) if probs else helper.make_node("Identity", ["z"], [out]))
    inputs = [helper.make_tensor_value_info("input_ids", TensorProto.INT64, ["b", "t"]),
              helper.make_tensor_value_info("attention_mask", TensorProto.INT64, ["b", "t"])]
    if typed:
        inputs.append(helper.make_tensor_value_info("token_type_ids", TensorProto.INT64, ["b", "t"]))
    graph = helper.make_graph(
        nodes, "tiny", inputs,
        [helper.make_tensor_value_info(out, TensorProto.FLOAT, ["b", 3])],
        [numpy_helper.from_array(emb, "E"), numpy_helper.from_array(np.array([2], dtype=np.int64), "ax")])
    m = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    m.ir_version = 8
    onnx.save(m, str(d / "model.onnx"))
    if judge_json is not None:
        (d / "judge.json").write_text(json.dumps(judge_json))
    if io is not None:
        (d / "io.json").write_text(json.dumps(io))
    return d


class TestOnnxJudge:
    def test_scores_a_batch(self, tmp_path):
        from prompt_programs.fix import Item
        j = OnnxJudge(tiny_model(tmp_path))
        p = j.p_wrong([Item("A nun under [Light]", "Light", "", "moonlight", USER),
                       Item("A nun under [Light]", "Light", "", "dawn light", USER),
                       Item("A [Job] under moonlight", "Job", "", "nun", USER)])
        assert p[0] > 0.99 and p[1] < 0.3 and p[2] < 0.3   # the state's moonlight doesn't count
        assert j.passes == 1 and j.questions == 3 and j.version.startswith("onnx:judge-model@")
        j.p_wrong([Item("A nun under [Light]", "Light", "", "moonlight", USER)])
        assert j.passes == 1 and j.hits == 1  # cached

    def test_judge_json_sets_cut_labels_and_templates(self, tmp_path):
        from prompt_programs.fix import Item
        j = OnnxJudge(tiny_model(tmp_path, {"cut": 0.07, "labels": ["wrong", "odd", "fine"], "wrong": "fine",
                                            "second": "{value}", "name": "deb-large"}))
        assert j.cut == 0.07 and j.version.startswith("onnx:deb-large@")
        assert j.texts(Item("s", "Light", "", "moonlight", "u"))[1] == "moonlight"
        assert j.p_wrong([Item("s", "Light", "", "moonlight", "u")])[0] > 0.99  # index 2 is "fine" here

    def test_the_exporters_probs_output_and_io_json(self, tmp_path):
        from prompt_programs.fix import Item
        d = tiny_model(tmp_path, probs=True, io={"kind": "enc", "inputs": ["input_ids", "attention_mask", "token_type_ids"],
                                                 "output": "probs [fine, odd, wrong]", "maxlen": 128, "cut": 0.021})
        (d / "model.onnx").rename(d / "model.int8.onnx")
        j = OnnxJudge(d)
        assert j.probs_out and j.max_length == 128 and j.cut == 0.021
        p = j.p_wrong([Item("s", "Light", "", "moonlight", "u"), Item("s", "Light", "", "dawn light", "u")])
        # no second softmax: softmax([1, 0, 10]) and softmax([1, 0, 0]) as exported
        assert p[0] == pytest.approx(0.99983, abs=1e-4) and p[1] == pytest.approx(0.21194, abs=1e-4)

    def test_a_decoder_reads_one_string_unpadded(self, tmp_path):
        from prompt_programs.fix import Item
        j = OnnxJudge(tiny_model(tmp_path, typed=False, io={"kind": "dec", "maxlen": 512}))
        assert j.kind == "dec"
        p = j.p_wrong([Item("A nun under [Light]", "Light", "", "moonlight", USER),
                       Item("A nun under [Light]", "Light", "", "dawn light", USER)])
        assert p[0] > 0.99 and p[1] < 0.3 and j.questions == 2

    def test_a_missing_or_broken_directory_fails_fast(self, tmp_path):
        with pytest.raises(FixJudgeUnavailable):
            fix_judge(str(tmp_path / "nope"))
        (tmp_path / "empty").mkdir()
        with pytest.raises(FixJudgeUnavailable):
            fix_judge(str(tmp_path / "empty"))

    def test_long_inputs_are_truncated(self, tmp_path):
        from prompt_programs.fix import Item
        j = OnnxJudge(tiny_model(tmp_path, {"max_length": 16}))
        p = j.p_wrong([Item("nun " * 200, "Light", "", "moonlight", "nun " * 50),
                       Item("nun", "Light", "", "moonlight " * 40, "")])
        assert p[0] > 0.99 and p[1] > 0.99


class TestRealizeAndFix:
    def test_through_realize_with_an_onnx_model(self, tmp_path):
        entry = entry_for()
        cfg = FluentSettings(fix_model=str(tiny_model(tmp_path)))
        s, r = seed_where(entry, lambda v: v["light"] == "moonlight")
        out, rec = judged(entry, s, cfg=cfg)
        assert values(out)["light"] != "moonlight" and "moonlight" not in out.prompt
        assert rec["rerolls"] >= 1 and rec["rounds"][0]["rerolled"]["value"] == "moonlight"
        assert rec["rounds"][0]["scores"]["light"] > 0.99 and rec["judge"].startswith("onnx:")
        assert rec["cut"] == 0.5 and not rec["unresolved"]
        again, rec2 = judged(entry, s, cfg=cfg)
        assert again.prompt == out.prompt and rec2["rounds"] == rec["rounds"]

    def test_off_replay_and_broken_model(self, tmp_path):
        entry = entry_for()
        r, rec = judged(entry, 4, cfg=FluentSettings(fix_model="off"))
        assert rec is None and r.prompt == draw(entry, 4).prompt
        cfg = FluentSettings(fix_model=str(tiny_model(tmp_path)))
        r, rec = judged(entry, 4, cfg=cfg, revision=r.revision)
        assert rec is None
        r, rec = judged(entry, 4, cfg=FluentSettings(fix_model=str(tmp_path / "x")))
        assert "error" in rec and r.prompt == draw(entry, 4).prompt

    def test_a_judge_that_fails_mid_pass_keeps_the_draw(self):
        class Broken:
            version = "broken"
            cut = 0.5

            def p_wrong(self, items):
                raise RuntimeError("boom")
        entry = entry_for()
        r, rec = judged(entry, 5, cfg=FluentSettings(), judge=Broken())
        assert r.prompt == draw(entry, 5).prompt and "boom" in rec["error"]

    def test_fix_cut_setting_overrides_the_model(self, tmp_path):
        entry = entry_for()
        cfg = FluentSettings(fix_model=str(tiny_model(tmp_path)), fix_cut=0.999999)
        s, r = seed_where(entry, lambda v: v["light"] == "moonlight")
        out, rec = judged(entry, s, cfg=cfg)
        assert rec["cut"] == 0.999999 and rec["rerolls"] == 0 and values(out)["light"] == "moonlight"


class TestExactTextIsNeverJudged:
    """[exact text] is the user's: the judge, like every model, reads only its token."""
    SECRET = "zq7 velvet harbor"

    def entry(self):
        masked, exact = prep.mask_exact(f"{USER} [{self.SECRET}]")
        assert self.SECRET not in masked and exact == {"EXACT_1": self.SECRET}
        return entry_for(masked, exact=exact)

    def test_no_judged_text_holds_the_exact_span(self):
        entry = self.entry()
        sc = Scorer(lambda it: 0.9 if it.value in ("moonlight", "noon sun") else 0.0)
        s, _ = seed_where(entry, lambda v: v["light"] == "moonlight")
        out, rec = judged(entry, s, cfg=FluentSettings(), judge=sc)
        seen = [f for b in sc.batches for it in b for f in (it.state, it.label, it.about, it.value, it.user_prompt)]
        assert seen and rec["rerolls"] >= 1
        assert not any(self.SECRET in f for f in seen)
        assert any("EXACT_1" in it.state for b in sc.batches for it in b)
        # what ships and what the generation details show have the user's text back
        assert self.SECRET in out.prompt and "EXACT_1" not in out.prompt
        assert all(self.SECRET in r["text"] and "EXACT_1" not in r["text"] for r in rec["rounds"])

    def test_without_a_judge_the_prompt_is_unmasked(self):
        entry = self.entry()
        out, rec = judged(entry, 3, cfg=FluentSettings(fix_model="off"))
        assert rec is None and self.SECRET in out.prompt and "EXACT_1" not in out.prompt


def test_settings_read_the_fix_fields(monkeypatch):
    from prompt_programs.judge import settings
    monkeypatch.setenv("STIMMA_FLUENT_FIX_MODEL", "/models/judge")
    monkeypatch.setenv("STIMMA_FLUENT_FIX_CUT", "0.03")
    monkeypatch.setenv("STIMMA_FLUENT_FIX_ROUNDS", "2")
    s = settings()
    assert (s.fix_model, s.fix_cut, s.fix_rounds) == ("/models/judge", 0.03, 2)


async def test_the_fix_judge_setting_route(tmp_path, monkeypatch):
    import httpx
    from fastapi import FastAPI
    import config
    import config_writer
    from routes import prompt_programs as route

    monkeypatch.delenv("STIMMA_FLUENT_FIX_MODEL", raising=False)  # the config decides here
    runtime = type("S", (), {"fluent": config.FluentConfig(fix_model="")})()  # saved as off
    written = []
    monkeypatch.setattr(config, "get_settings", lambda: runtime)
    monkeypatch.setattr(config_writer, "patch_global_section", lambda section, value: written.append((section, value)))
    app = FastAPI()
    app.include_router(route.router)
    model = str(tiny_model(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/prompt-programs/fix-judge")).json() == {"model": "", "status": "off"}
        r = (await c.put("/api/prompt-programs/fix-judge", json={"model": f"  {model} "})).json()
        assert r["status"] == "ready" and r["model"] == model and r["version"].startswith("onnx:")
        assert written[-1][0] == "fluent" and written[-1][1]["fix_model"] == model and runtime.fluent.fix_model == model
        assert (await c.get("/api/prompt-programs/fix-judge")).json()["status"] == "ready"
        r = (await c.put("/api/prompt-programs/fix-judge", json={"model": str(tmp_path / "missing")})).json()
        assert r["status"] == "error" and "no judge model directory" in r["error"]
        assert (await c.put("/api/prompt-programs/fix-judge", json={"model": ""})).json()["status"] == "off"


class TestTheFixNeverCostsTheImage:
    """Whatever the fix judge does wrong, the draw ships unjudged and generation goes on."""

    @pytest.mark.parametrize("fail", ["first", "second", "garbage", "short"])
    def test_any_judge_failure_ships_the_draw_as_made(self, fail):
        class Flaky:
            version, cut = "flaky", 0.5

            def __init__(self):
                self.passes = 0

            def p_wrong(self, items):
                self.passes += 1
                if fail == "first" or (fail == "second" and self.passes == 2):
                    raise KeyError("bad response")
                if fail == "garbage":
                    return [object() for _ in items]
                if fail == "short":
                    return []
                return [0.99 for _ in items]  # everything flagged: reroll, then the second pass
        entry = entry_for()
        r, rec = judged(entry, 5, cfg=FluentSettings(), judge=Flaky())
        assert r.prompt == draw(entry, 5).prompt or fail == "short"
        if fail != "short":
            assert "the fix pass failed" in rec["error"]

    def test_a_model_that_breaks_on_load_ships_the_draw(self, tmp_path):
        bad = tmp_path / "judge"
        bad.mkdir()
        (bad / "model.onnx").write_bytes(b"not a model")
        (bad / "tokenizer.json").write_text("{}")
        entry = entry_for()
        r, rec = judged(entry, 6, cfg=FluentSettings(fix_model=str(bad)))
        assert r.prompt == draw(entry, 6).prompt and rec["error"]
