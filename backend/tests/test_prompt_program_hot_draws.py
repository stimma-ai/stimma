"""Fluent hot draws: forever mode keeps finished draws (drawn and judged) ready, so a
submit never waits on the fix judge. Several draws share each judge pass, and a pass
asked for while one runs joins the next."""

import asyncio
import threading
import time

import pytest

from prompt_programs import program as prep
from prompt_programs.fix import (
    Item, OnnxJudge, fix_draw, prompt_view, realize_and_fix, realize_and_fix_many,
)
from prompt_programs.judge import FluentSettings
from tests.test_prompt_program_fix import USER, Scorer, entry_for, redraw_for, tiny_model, values

def moon_rule(it):
    return 0.97 if it.value in ("moonlight", "a black habit") else 0.02


@pytest.fixture(autouse=True)
def no_profile(monkeypatch):
    import prompt_programs.fluent as fl
    monkeypatch.setattr(fl, "_profile_store", lambda pid: None)
    monkeypatch.setattr(fl, "filler_for", lambda pid: (_ for _ in ()).throw(RuntimeError("no filler in tests")))


def strip_ms(rec):
    return {k: v for k, v in (rec or {}).items() if k != "ms"}


CFG = FluentSettings(generate_options=False, fix_model="stub")


# --------------------------------------------------------------------------- batched fix loops

class TestBatched:
    SEEDS = list(range(40))

    def test_batched_equals_one_at_a_time(self):
        entry = entry_for()
        alone = [realize_and_fix(entry, seed=s, cfg=CFG, judge=Scorer(moon_rule)) for s in self.SEEDS]
        judge = Scorer(moon_rule)
        many = realize_and_fix_many(entry, seeds=self.SEEDS, cfg=CFG, judge=judge)
        assert [r.prompt for r, _ in many] == [r.prompt for r, _ in alone]
        assert [strip_ms(f) for _, f in many] == [strip_ms(f) for _, f in alone]
        assert any(f["rerolls"] for _, f in many)          # the case under test: rerolls happened
        # one judge pass per round, for every draw still going: far fewer than one per draw per round
        assert len(judge.batches) == 1 + max(f["rerolls"] for _, f in many)

    def test_batched_onnx_scores_match_one_at_a_time(self, tmp_path):
        entry = entry_for()
        j = OnnxJudge(tiny_model(tmp_path))
        cfg = FluentSettings(generate_options=False, fix_model=str(tmp_path))
        many = realize_and_fix_many(entry, seeds=self.SEEDS, cfg=cfg, judge=j)
        for s, (r, f) in zip(self.SEEDS, many):
            j._cache.clear()  # score it alone, not from the batch's cache
            r1, f1 = realize_and_fix(entry, seed=s, cfg=cfg, judge=j)
            assert r1.prompt == r.prompt and f1["chosen"] == f["chosen"]
            for a, b in zip(f["rounds"], f1["rounds"]):
                assert a.keys() == b.keys() and a.get("rerolled") == b.get("rerolled")
                for cid, p in a["scores"].items():
                    assert p == pytest.approx(b["scores"][cid], abs=1e-4)

    def test_a_draw_that_fails_doesnt_cost_the_others(self):
        entry = entry_for()
        # an outfit this choice offers, but not for a nun: refused at the choice, for every seed
        out = realize_and_fix_many(entry, seeds=[1, 2, 3], pins={"job": ["nun"], "outfit": ["green scrubs"]}, cfg=CFG,
                                   judge=Scorer(moon_rule))
        assert all(isinstance(o, prep.ProgramError) for o in out)
        out = realize_and_fix_many(entry, seeds=[1, 2], cfg=CFG, judge=Scorer(moon_rule))
        assert all(isinstance(o, tuple) for o in out)

    def test_a_judge_failing_keeps_every_draw_as_made(self):
        class Broken:
            version, cut = "broken", 0.5

            def p_wrong(self, items):
                raise RuntimeError("boom")
        entry = entry_for()
        out = realize_and_fix_many(entry, seeds=[5, 6], cfg=CFG, judge=Broken())
        assert [r.prompt for r, _ in out] == [prep.realize(entry, seed=s).prompt for s in (5, 6)]
        assert all("boom" in f["error"] for _, f in out)


class TestRollRecord:
    def test_each_roll_records_its_prompt_spans_and_values(self):
        entry = entry_for()
        s = next(s for s in range(500) if values(prep.realize(entry, seed=s))["light"] == "moonlight")
        r0 = prep.realize(entry, seed=s)
        out, rec = fix_draw(r0, judge=Scorer(moon_rule), redraw=redraw_for(entry), seed=s, user_prompt=USER, cut=0.5)
        first, last = rec["rounds"][0], rec["rounds"][rec["chosen"]]
        assert first["values"]["light"] == "moonlight" and last["values"]["light"] != "moonlight"
        assert last["text"] == prep.realized_text(out.prompt)
        for roll in rec["rounds"]:
            for a, b, cid in roll["spans"]:
                assert roll["text"][a:b].lower() == roll["values"][cid].lower()
            starts = [sp[0] for sp in roll["spans"]]
            assert starts == sorted(starts)

    def test_spans_never_overlap_and_prefer_the_longer_value(self):
        class D:
            def __init__(self, id, value, source="text"):
                self.id, self.value, self.kind, self.hidden, self.source = id, value, "pick", False, source

        class R:
            prompt = "A red dress under red light"
            draws = [D("color", "red"), D("dress", "red dress")]
        v = prompt_view(R())
        assert v["spans"] == [[2, 11, "dress"]] and v["values"] == {"color": "red", "dress": "red dress"}


# --------------------------------------------------------------------------- one pass for concurrent callers

class TestCoalescing:
    def test_concurrent_callers_share_passes_and_get_their_own_scores(self, tmp_path):
        j = OnnxJudge(tiny_model(tmp_path))
        real_run = j._run
        sizes = []

        def slow_run(pairs):
            sizes.append(len(pairs))
            time.sleep(0.05)
            return real_run(pairs)
        j._run = slow_run
        values_ = ["moonlight", "dawn light", "noon sun", "candlelight"]
        asks = [[Item(f"A nun {i} under [Light]", "Light", "", v, USER) for v in values_] for i in range(6)]
        got = [None] * len(asks)

        def ask(i):
            got[i] = j.p_wrong(asks[i])
        threads = [threading.Thread(target=ask, args=(i,)) for i in range(len(asks))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert j.passes < len(asks) and max(sizes) > 4  # callers waiting on a pass ran together
        for g in got:
            assert g[0] > 0.99 and all(p < 0.3 for p in g[1:])

    def test_an_error_reaches_every_caller_in_the_pass_and_the_next_pass_runs(self, tmp_path):
        j = OnnxJudge(tiny_model(tmp_path))
        real_run = j._run
        calls = []

        def flaky(pairs):
            calls.append(len(pairs))
            if len(calls) == 1:
                raise RuntimeError("boom")
            return real_run(pairs)
        j._run = flaky
        with pytest.raises(RuntimeError):
            j.p_wrong([Item("s", "Light", "", "moonlight", "u")])
        assert j.p_wrong([Item("s", "Light", "", "moonlight", "u")])[0] > 0.99


# --------------------------------------------------------------------------- the pool

@pytest.fixture
def queue(monkeypatch):
    from generation_queue import GenerationQueue
    monkeypatch.setenv("STIMMA_FLUENT_GENERATE", "0")
    monkeypatch.setenv("STIMMA_FLUENT_FIX_MODEL", "stub")
    judge = Scorer(moon_rule)
    monkeypatch.setattr("prompt_programs.fix.fix_judge", lambda model, threads=0: judge)
    q = GenerationQueue()
    q._forever_mode_clients = {"backend-a": {"gen-1": 3}}
    q.judge = judge
    return q


def spec_for(entry, pins=None):
    return lambda: {"entry": entry, "pins": pins, "fixed": None, "edits": None, "triggers": True,
                    "profile_id": None, "project_id": None}


async def settle(q, gid):
    for _ in range(200):
        tasks = list(q._prompt_warm_tasks.get(gid, ()))
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)
    raise AssertionError("refill never settled")


class TestPool:
    async def test_fills_to_the_slots_and_serves_current_draws(self, queue):
        entry = entry_for()
        assert queue.take_fluent_draw("gen-1", "sig-a", spec_for(entry)) is None  # cold: draw inline
        await settle(queue, "gen-1")
        assert len(queue._prompt_warm_ready["gen-1"]) == 3
        hot = queue.take_fluent_draw("gen-1", "sig-a", spec_for(entry))
        assert hot is not None and hot["fix"]["rounds"] and hot["result"].prompt
        await settle(queue, "gen-1")
        assert len(queue._prompt_warm_ready["gen-1"]) == 3  # topped back up

    async def test_three_draws_fill_in_one_judge_pass(self, queue):
        queue.judge.rule = lambda it: 0.01  # nothing rerolls: one round
        entry = entry_for()
        queue.take_fluent_draw("gen-1", "sig-a", spec_for(entry))
        await settle(queue, "gen-1")
        assert len(queue._prompt_warm_ready["gen-1"]) == 3 and len(queue.judge.batches) == 1

    async def test_a_new_signature_tosses_the_pool(self, queue):
        entry = entry_for()
        queue.take_fluent_draw("gen-1", "sig-a", spec_for(entry))
        await settle(queue, "gen-1")
        assert queue.take_fluent_draw("gen-1", "sig-b", spec_for(entry, pins={"job": ["nun"]})) is None
        await settle(queue, "gen-1")
        ready = queue._prompt_warm_ready["gen-1"]
        assert len(ready) == 3 and all(values(h["result"])["job"] == "nun" for h in ready)

    async def test_a_refill_in_flight_for_an_old_signature_never_lands(self, queue, monkeypatch):
        import prompt_programs.fix as fx
        gate = threading.Event()
        real = fx.realize_and_fix_many

        def held(*a, **k):
            gate.wait(5)
            return real(*a, **k)
        monkeypatch.setattr(fx, "realize_and_fix_many", held)
        entry = entry_for()
        queue.take_fluent_draw("gen-1", "sig-a", spec_for(entry))
        await asyncio.sleep(0.01)
        monkeypatch.setattr(fx, "realize_and_fix_many", real)
        queue.take_fluent_draw("gen-1", "sig-b", spec_for(entry, pins={"job": ["surgeon"]}))
        gate.set()
        await settle(queue, "gen-1")
        await asyncio.sleep(0.1)  # the old refill's thread finishes after its task was cancelled
        ready = queue._prompt_warm_ready["gen-1"]
        assert len(ready) == 3 and all(values(h["result"])["job"] == "surgeon" for h in ready)

    async def test_concurrent_takes_never_share_a_draw(self, queue):
        entry = entry_for()
        queue.take_fluent_draw("gen-1", "sig-a", spec_for(entry))
        seen = []
        for _ in range(8):
            await settle(queue, "gen-1")
            taken = [queue.take_fluent_draw("gen-1", "sig-a", spec_for(entry)) for _ in range(3)]
            assert all(t is not None for t in taken)
            seen.extend(t["seed"] for t in taken)
            assert len(queue._prompt_warm_ready["gen-1"]) <= 3
        assert len(seen) == 24 and len(set(seen)) == 24  # every draw served once, fresh seeds

    async def test_only_forever_registrations_get_a_pool(self, queue):
        assert queue.take_fluent_draw("gen-2", "sig-a", spec_for(entry_for())) is None
        assert "gen-2" not in queue._prompt_warm_intent

    async def test_stopping_forever_tears_it_down(self, queue):
        queue.take_fluent_draw("gen-1", "sig-a", spec_for(entry_for()))
        await settle(queue, "gen-1")
        await queue.unregister_forever_mode("gen-1", "backend-a")
        assert "gen-1" not in queue._prompt_warm_intent and "gen-1" not in queue._prompt_warm_ready

    async def test_the_enhance_pool_leaves_it_alone(self, queue):
        queue.take_fluent_draw("gen-1", "sig-a", spec_for(entry_for()))
        await settle(queue, "gen-1")
        # the client clears enhance warming on its heartbeat while Fluent runs
        await queue.update_prompt_warm_pool(
            "gen-1", tool_id="t", prompt="p", instructions=None, model=None, is_video=False, is_audio=False,
            input_image_count=0, audio_conditioned=False, prompt_sources_signature="", concurrency=0,
            profile_id="p")
        assert len(queue._prompt_warm_ready["gen-1"]) == 3
        assert queue.consume_prompt_warm_pool("gen-1") is None  # never handed out as an enhanced prompt
        assert len(queue._prompt_warm_ready["gen-1"]) == 3

    async def test_a_hot_draw_replays_like_a_live_one(self, queue):
        entry = entry_for()
        queue.take_fluent_draw("gen-1", "sig-a", spec_for(entry))
        await settle(queue, "gen-1")
        for _ in range(3):
            hot = queue.take_fluent_draw("gen-1", "sig-a", spec_for(entry))
            r, f = hot["result"], hot["fix"]
            # the seed it was drawn from gives the same draw and the same fix, as a live draw would
            again, f2 = realize_and_fix(entry, seed=hot["seed"], cfg=CFG, judge=Scorer(moon_rule))
            assert again.prompt == r.prompt and strip_ms(f2) == strip_ms(f)
            # "Same draws, new seed" fixes every drawn value
            assert prep.realize(entry, seed=12345, fixed=values(r)).prompt == r.prompt


# --------------------------------------------------------------------------- the submit path

class TestSignature:
    def _sig(self, entry=None, pins=None, edits=None, zones=None):
        from routes.generation import hot_draw_signature
        return hot_draw_signature(entry or entry_for(), pins=pins or {}, edits=edits or {}, zones=zones or {},
                                  profile_id="p", project_id=None)

    def test_same_inputs_same_signature(self):
        assert self._sig(pins={"job": ["nun"]}) == self._sig(pins={"job": ["nun"]})

    def test_anything_a_draw_is_made_from_changes_it(self, monkeypatch):
        base = self._sig()
        assert self._sig(pins={"job": ["nun"]}) != base
        assert self._sig(zones={"light": ["instead"]}) != base
        assert self._sig(edits={"light": {"remove": ["moonlight"]}}) != base
        assert self._sig(entry_for(created_at=2)) != base  # a new prepare committed
        monkeypatch.setenv("STIMMA_FLUENT_FIX_CUT", "0.3")
        assert self._sig() != base


class TestSubmit:
    async def test_a_forever_submit_takes_a_hot_draw(self, queue, monkeypatch):
        import routes.generation as gen
        entry = entry_for()

        async def ensure(prompt, **kw):
            return dict(entry)
        monkeypatch.setattr("prompt_programs.slots.ensure", ensure)
        monkeypatch.setattr("generation_queue.get_generation_queue", lambda: queue)

        async def submit(**opts):
            record, _, _ = await gen._run_slots(
                USER, {"enabled": True, **opts}, project_id=None, profile_id=None, hot_draws_for="gen-1")
            return record
        cold = await submit()
        await settle(queue, "gen-1")
        ready_seeds = [h["result"].seed for h in queue._prompt_warm_ready["gen-1"]]
        hot = await submit()
        assert hot["draw_seed"] == ready_seeds[0] != cold["draw_seed"]
        assert hot["fix"]["rounds"] and "view" not in hot
        # an explicit draw seed (Same draws, new seed) never takes from the pool
        await settle(queue, "gen-1")
        before = len(queue._prompt_warm_ready["gen-1"])
        seeded = await submit(draw_seed=7)
        assert seeded["draw_seed"] == 7 and len(queue._prompt_warm_ready["gen-1"]) == before
