"""Fluent draws, step 2: generated options, the option cache and filler, and the
runtime wiring in realize()."""

import asyncio
import json
import threading

import pytest

from prompt_programs import prepare as prep
from prompt_programs.draws import DrawResult, PickSpec, fixed_text
from prompt_programs.runtime import ProgramError
from prompt_programs.fluent import program_context, runtime_for, start_options
from prompt_programs.judge import FluentSettings, settings
from prompt_programs.options import (
    MAX_ROUNDS, THIN, GeneratedOptions, OptionFiller, OptionJob, OptionStore, ProgramContext, gen_key,
    generation_messages,
)

PORTRAIT = '''
era = pick("era", ["1920s", "1970s", "1990s"], label="Era", source="list", phase=1, line=1)
role = pick("role", about="the woman's job", phase=1, seed=["jazz singer", "nurse"])
hair = pick("hair", label="Hairstyle", about="her hairstyle", phase=2, seed=["finger waves"])
light = pick("light", about="the lighting", phase=2, seed=["soft window light"])
emit("A portrait of a", role, "in the", era, "with", hair, ",", light)
'''

# hair depends on era (its about mentions it), so its pools are per era.
DEPENDENT = '''
era = pick("era", ["1920s", "1970s"], label="Era", source="list", phase=1)
hair = pick("hair", label="Hairstyle", about=f"a {era} hairstyle", phase=2, seed=["a bob"])
emit("A woman in the", era, "with", hair)
'''

ON = FluentSettings(generate_options=True, fix_model="off")
OFF = FluentSettings(generate_options=False, fix_model="off")


def entry_for(program, **kw):
    return {"key": kw.pop("key", "prog1"), "program": program, "loras": [], "params": {}, "mode": "prose", **kw}


class FakeGen:
    """Writes numbered options per pool; counts calls."""

    def __init__(self, per_call=12, table=None):
        self.calls = []
        self.per_call, self.table = per_call, table or {}

    async def __call__(self, job):
        self.calls.append(job)
        if job.spec.id in self.table:
            return list(self.table[job.spec.id]), "fake"
        ctx = ",".join(f"{v}" for v in job.context.values())
        return [f"{job.spec.id} {ctx} variant {job.round}.{i}".replace("  ", " ") for i in range(self.per_call)], "fake"


def spec(id="hair", about="her hairstyle", source="text", seeds=("finger waves",), literal=(), label="Hairstyle", kind="pick"):
    return PickSpec(id, label, about, 2, source, kind, list(seeds), list(literal))


def program(signature="", template="A portrait of a [Role] with [Hairstyle]", key="prog1"):
    return ProgramContext(key, signature or template, template, "prose", True)


# --------------------------------------------------------------------------- the cache

class TestOptionStore:
    def test_append_only_and_first_occurrence_wins(self, tmp_path):
        s = OptionStore(tmp_path)
        s.append("ab12", {"round": 0, "options": ["A bob", "finger waves"]})
        s.append("ab12", {"round": 1, "options": ["a BOB", "an updo"]})
        assert s.options("ab12") == ["A bob", "finger waves", "an updo"]
        assert s.rounds("ab12") == 2 and s.has_round("ab12", 1) and not s.has_round("ab12", 2)
        assert len((tmp_path / "ab" / "ab12.jsonl").read_text().splitlines()) == 2

    def test_a_half_written_line_is_skipped(self, tmp_path):
        s = OptionStore(tmp_path)
        s.append("cd34", {"round": 0, "options": ["x"]})
        with open(tmp_path / "cd" / "cd34.jsonl", "a") as f:
            f.write('{"round": 1, "opt')
        assert OptionStore(tmp_path).options("cd34") == ["x"]

    def test_another_process_appending_is_seen(self, tmp_path):
        a, b = OptionStore(tmp_path), OptionStore(tmp_path)
        a.append("ef56", {"round": 0, "options": ["x"]})
        assert b.options("ef56") == ["x"]
        a.append("ef56", {"round": 1, "options": ["y"]})
        assert b.options("ef56") == ["x", "y"]

    def test_pool_identity(self):
        s = spec()
        base = gen_key(s, {}, "a 1920s portrait", "prose", True)
        assert base == gen_key(spec(id="people[2].hair", about="Her  Hairstyle", seeds=["other"]), {}, "a 1920s portrait", "prose", True)
        assert base != gen_key(s, {"era": "1920s"}, "a 1920s portrait", "prose", True)
        assert base != gen_key(s, {}, "a 1970s portrait", "prose", True)
        assert base != gen_key(s, {}, "a 1920s portrait", "keyword", True)
        assert base != gen_key(s, {}, "a 1920s portrait", "prose", False)


# --------------------------------------------------------------------------- pools

class TestGeneratedOptions:
    def test_user_lists_are_exact_and_never_expanded(self, tmp_path):
        store, filler = OptionStore(tmp_path), OptionFiller(OptionStore(tmp_path), FakeGen())
        opts = GeneratedOptions(store, program(), filler=filler)
        s = spec(id="era", about="the decade", source="list", seeds=(), literal=("1920s", "1970s"))
        pool = opts.get(s, {})
        assert pool.items == ["1920s", "1970s"] and pool.weights == [1.0, 1.0] and not pool.more_coming
        opts.request_more(s, {}, "high")
        assert not filler.busy(gen_key(s, {}, program().signature, "prose", True)) and opts.queued == []

    def test_seeds_then_generated_in_rank_order(self, tmp_path):
        store = OptionStore(tmp_path)
        s = spec(seeds=("finger waves", "a bob"))
        key = gen_key(s, {}, program().signature, "prose", True)
        store.append(key, {"round": 0, "options": ["A BOB", "an updo", "pin curls"]})
        pool = GeneratedOptions(store, program()).get(s, {})
        assert pool.items == ["finger waves", "a bob", "an updo", "pin curls"]
        assert pool.weights == sorted(pool.weights, reverse=True) and pool.weights[0] == 1.0
        assert pool.key == "hair: her hairstyle"

    def test_edits_remove_and_add(self, tmp_path):
        store = OptionStore(tmp_path)
        s = spec()
        store.append(gen_key(s, {}, program().signature, "prose", True), {"round": 0, "options": ["an updo", "pin curls"]})
        edits = {"hair": {"remove": ["finger waves"], "add": ["a beehive"]}}
        assert GeneratedOptions(store, program(), edits=edits).get(s, {}).items == ["a beehive", "an updo", "pin curls"]

    def test_a_new_pool_queues_low_and_says_more_coming(self, tmp_path):
        store = OptionStore(tmp_path)
        filler = OptionFiller(store, FakeGen())
        opts = GeneratedOptions(store, program(), filler=filler)
        pool = opts.get(spec(), {})
        assert pool.items == ["finger waves"] and pool.more_coming
        assert filler._jobs[opts.queued[0]][0] == 1  # low

    def test_a_thin_pool_asks_high(self, tmp_path):
        store = OptionStore(tmp_path)
        s = spec()
        key = gen_key(s, {}, program().signature, "prose", True)
        store.append(key, {"round": 0, "options": ["an updo"]})
        filler = OptionFiller(store, FakeGen())
        GeneratedOptions(store, program(), filler=filler).get(s, {})
        assert filler._jobs[key][0] == 0 and filler._jobs[key][1].round == 1  # high, next round

    def test_a_full_pool_asks_nothing(self, tmp_path):
        store = OptionStore(tmp_path)
        s = spec()
        store.append(gen_key(s, {}, program().signature, "prose", True), {"round": 0, "options": [f"o{i}" for i in range(THIN + 2)]})
        filler = OptionFiller(store, FakeGen())
        pool = GeneratedOptions(store, program(), filler=filler).get(s, {})
        assert not filler._jobs and not pool.more_coming

    def test_rounds_are_capped(self, tmp_path):
        store = OptionStore(tmp_path)
        s = spec()
        key = gen_key(s, {}, program().signature, "prose", True)
        for r in range(MAX_ROUNDS):
            store.append(key, {"round": r, "options": []})
        filler = OptionFiller(store, FakeGen())
        opts = GeneratedOptions(store, program(), filler=filler)
        opts.get(s, {})
        opts.request_more(s, {}, "high")
        assert not filler._jobs

    def test_a_pool_is_read_once_per_draw(self, tmp_path):
        store = OptionStore(tmp_path)
        s = spec()
        opts = GeneratedOptions(store, program())
        first = opts.get(s, {})
        store.append(gen_key(s, {}, program().signature, "prose", True), {"round": 0, "options": ["an updo"]})
        assert opts.get(s, {}) is first
        assert GeneratedOptions(store, program()).get(s, {}).items == ["finger waves", "an updo"]

    def test_limits_replay_a_revision(self, tmp_path):
        store = OptionStore(tmp_path)
        s = spec()
        key = gen_key(s, {}, program().signature, "prose", True)
        store.append(key, {"round": 0, "options": ["an updo", "pin curls"]})
        store.append(key, {"round": 1, "options": ["a beehive"]})
        filler = OptionFiller(store, FakeGen())
        pool = GeneratedOptions(store, program(), filler=filler, limits={"hair: her hairstyle": 2}).get(s, {})
        assert pool.items == ["finger waves", "an updo"] and not filler._jobs

    def test_no_generation_when_off(self, tmp_path):
        store = OptionStore(tmp_path)
        filler = OptionFiller(store, FakeGen())
        GeneratedOptions(store, program(), filler=filler, generate=False).get(spec(), {})
        assert not filler._jobs

class TestGenerationMessages:
    def test_messages_carry_spec_context_style_and_avoid(self):
        job = OptionJob("k", spec(seeds=("finger waves",)), {"era": "1920s"}, program(signature="a jazz portrait"),
                        "a jazz portrait", 0, existing=["a bob"], avoid=["a mohawk"])
        system, user = (m["content"] for m in generation_messages(job))
        assert '"Hairstyle" (her hairstyle)' in system and "era = 1920s" in system and "unusual but real" in system
        assert "[Hairstyle]" in user and "a jazz portrait" in user and "- finger waves" in user
        assert "- a bob" in user and "- a mohawk" in user

    def test_the_users_lists_it_does_not_depend_on_are_shown(self):
        entry = entry_for('job = pick("job", ["nun", "lifeguard"], label="Job", source="list", phase=1)\n'
                          'w = pick("w", ["rain", "sun"], label="Weather", source="list", phase=1)\n'
                          'o = pick("o", about=f"what a {job} wears", seed=["a coat"], label="Outfit", phase=2)\n'
                          'emit(job, w, o)\n',
                          choices=[{"id": "job", "label": "Job", "source": "list", "kind": "pick", "options": ["nun", "lifeguard"]},
                                   {"id": "w", "label": "Weather", "source": "list", "kind": "pick", "options": ["rain", "sun"]},
                                   {"id": "o", "label": "Outfit", "source": "text", "kind": "pick", "options": ["a coat"]}])
        prog = ProgramContext.of(entry)
        s = spec(id="o", about="what a nun wears", label="Outfit")
        user = generation_messages(OptionJob("k", s, {"job": "nun"}, prog, prog.signature, 0))[1]["content"]
        assert "- [Weather]: rain, sun" in user and "[Job]:" not in user
        # the lists it is shown are part of the pool's identity
        assert gen_key(s, {"job": "nun"}, "t", "prose", True, prog.lists) != gen_key(s, {"job": "nun"}, "t", "prose", True)
        assert gen_key(s, {}, "t", "prose", True, (("o", "Outfit", ("x",)),)) == gen_key(s, {}, "t", "prose", True)

    def test_keyword_style(self):
        prog = ProgramContext("k", "t", "t", "keyword", True)
        assert "tags" in generation_messages(OptionJob("k", spec(), {}, prog, "t", 0))[0]["content"]


# --------------------------------------------------------------------------- the filler

class TestOptionFiller:
    def _job(self, store, id, about, priority_round=0):
        s = spec(id=id, about=about)
        return OptionJob(gen_key(s, {}, "sig", "prose", True), s, {}, program(), "sig", priority_round)

    async def test_high_priority_first_and_one_job_per_pool(self, tmp_path):
        store = OptionStore(tmp_path)
        gen = FakeGen()
        f = OptionFiller(store, gen)
        a, b, c = self._job(store, "a", "thing a"), self._job(store, "b", "thing b"), self._job(store, "c", "thing c")
        assert f.submit(a, "low") and f.submit(b, "low") and f.submit(c, "high")
        assert not f.submit(self._job(store, "a", "thing a"), "low")      # already queued
        assert f.submit(self._job(store, "b", "thing b"), "high")         # promoted
        await f.drain()
        assert [j.spec.id for j in gen.calls] == ["c", "b", "a"]
        assert store.options(a.key)[0] == "a variant 0.0"

    async def test_a_finished_round_never_releases_the_next(self, tmp_path):
        store = OptionStore(tmp_path)
        f = OptionFiller(store, FakeGen())
        first = self._job(store, "a", "thing a")
        f.submit(first)
        assert f._next() is first
        with f._lock:  # its round is stored; a check queues the next round
            f._release(first)
        second = self._job(store, "a", "thing a", 1)
        assert f.submit(second) and f._next() is second
        with f._lock:  # the first worker's cleanup runs late
            f._release(first)
        assert f.busy(second.key)

    async def test_a_round_on_disk_is_never_asked_again(self, tmp_path):
        store = OptionStore(tmp_path)
        gen = FakeGen()
        job = self._job(store, "a", "thing a")
        store.append(job.key, {"round": 0, "options": ["cached"]})
        f = OptionFiller(store, gen)
        f.submit(job)
        await f.drain()
        assert gen.calls == [] and store.options(job.key) == ["cached"]

    async def test_repeats_and_existing_options_are_dropped(self, tmp_path):
        store = OptionStore(tmp_path)
        job = self._job(store, "a", "thing a")
        job.existing = ["Old one"]
        f = OptionFiller(store, FakeGen(table={"a": ["old one", "new", "new", " "]}))
        f.submit(job)
        await f.drain()
        rec = store.records(job.key)[0]
        assert rec["options"] == ["new"] and rec["inputs"]["about"] == "thing a" and rec["model"] == "fake"

    async def test_a_failing_generator_does_not_stop_the_queue(self, tmp_path):
        store = OptionStore(tmp_path)

        async def gen(job):
            if job.spec.id == "a":
                raise RuntimeError("boom")
            return ["ok"], "fake"
        f = OptionFiller(store, gen)
        f.submit(self._job(store, "a", "thing a"))
        f.submit(self._job(store, "b", "thing b"))
        await f.drain()
        assert f.failures == 1 and store.options(self._job(store, "b", "thing b").key) == ["ok"]

    async def test_the_background_worker_takes_jobs_from_other_threads(self, tmp_path):
        store = OptionStore(tmp_path)
        done = asyncio.Event()
        loop = asyncio.get_running_loop()

        async def gen(job):
            loop.call_soon(done.set)
            return ["bg"], "fake"
        f = OptionFiller(store, gen)
        f.attach()
        job = self._job(store, "a", "thing a")
        t = threading.Thread(target=f.submit, args=(job, "high"))
        t.start()
        t.join()
        await asyncio.wait_for(done.wait(), 5)
        for _ in range(50):
            if store.options(job.key):
                break
            await asyncio.sleep(0.01)
        assert store.options(job.key) == ["bg"] and not f.busy(job.key)
        for task in f._tasks:
            task.cancel()

    async def test_it_gives_way_while_a_prepare_is_in_flight(self, tmp_path, monkeypatch):
        import prompt_programs.options as opts
        monkeypatch.setattr(opts, "YIELD_POLL", 0.01)
        store, gen, preparing = OptionStore(tmp_path), FakeGen(), {"on": True}
        f = OptionFiller(store, gen, paused=lambda: preparing["on"])
        f.attach()
        job = self._job(store, "a", "thing a")
        f.submit(job, "high")
        await asyncio.sleep(0.1)
        assert not gen.calls and f.busy(job.key)  # queued, not started
        preparing["on"] = False
        for _ in range(100):
            if store.options(job.key):
                break
            await asyncio.sleep(0.01)
        assert store.options(job.key) and len(gen.calls) == 1
        for task in f._tasks:
            task.cancel()

    async def test_queued_low_work_for_an_edited_away_prompt_is_dropped(self, tmp_path):
        store, gen = OptionStore(tmp_path), FakeGen()
        f = OptionFiller(store, gen, current=lambda job: job.spec.id != "old")
        old, new, thin = self._job(store, "old", "thing a"), self._job(store, "b", "thing b"), self._job(store, "old", "thing c")
        f.submit(old, "low")
        f.submit(new, "low")
        f.submit(thin, "high")  # a draw asked for it now: kept
        await f.drain()
        assert sorted(j.spec.about for j in gen.calls) == ["thing b", "thing c"] and f.dropped == 1
        assert not f.busy(old.key)

    def test_prepare_tracks_the_latest_program_per_context(self, monkeypatch):
        monkeypatch.setattr(prep, "_latest", {})
        assert prep.is_current("k1", "ctx") and prep.is_current("k1", "")
        prep._latest["ctx"] = "k2"
        assert not prep.is_current("k1", "ctx") and prep.is_current("k2", "ctx")
        assert ProgramContext.of({"key": "k1", "program": 'emit("x")', "context_key": "ctx"}).context_key == "ctx"


# --------------------------------------------------------------------------- realize

class TestRealize:
    def _runtime(self, tmp_path, entry, filler=None, cfg=OFF, revision=None):
        store = OptionStore(tmp_path)
        return store, runtime_for(entry, store=store, filler=filler, cfg=cfg, revision=revision)

    def test_the_fixed_text_masks_every_pick(self):
        assert fixed_text(PORTRAIT) == "A portrait of a [Role] in the [Era] with [Hairstyle], [Light]"
        ctx = program_context(entry_for(PORTRAIT, context="a 1920s portrait"))
        assert ctx.signature == "a 1920s portrait" and ctx.template.startswith("A portrait of a [Role]")

    def test_generated_options_reach_the_prompt(self, tmp_path):
        entry = entry_for(PORTRAIT)
        store, rt = self._runtime(tmp_path, entry)
        ctx = program_context(entry)
        for s, opts in ((spec(), ["a sleek bob", "pin curls"]), (spec(id="light", about="the lighting", seeds=("soft window light",), label="Light"), ["neon glow"])):
            store.append(gen_key(s, {}, ctx.signature, "prose", True), {"round": 0, "options": opts})
        seen = set()
        for seed in range(60):
            store_, rt = self._runtime(tmp_path, entry)
            r = prep.realize(entry, seed=seed, runtime=rt)
            seen |= {d.value for d in r.draws}
        assert {"a sleek bob", "pin curls", "neon glow"} <= seen
        assert r.revision["pools"]["hair: her hairstyle"] == 3 and "judge" not in r.revision

    def test_the_same_revision_replays_after_pools_grow(self, tmp_path):
        entry = entry_for(PORTRAIT)
        store, rt = self._runtime(tmp_path, entry)
        key = gen_key(spec(), {}, program_context(entry).signature, "prose", True)
        store.append(key, {"round": 0, "options": ["a sleek bob", "pin curls"]})
        first = [prep.realize(entry, seed=s, runtime=self._runtime(tmp_path, entry)[1]) for s in range(12)]
        store.append(key, {"round": 1, "options": ["a beehive", "an afro", "braids"]})
        for s, r in enumerate(first):
            again = prep.realize(entry, seed=s, revision=r.revision, runtime=self._runtime(tmp_path, entry, revision=r.revision)[1])
            assert again.prompt == r.prompt and again.revision["id"] == r.revision["id"]
        grown = prep.realize(entry, seed=0, runtime=self._runtime(tmp_path, entry)[1])
        assert grown.revision["pools"]["hair: her hairstyle"] == 6

    def test_a_revision_replays_from_the_options_version_it_drew(self, tmp_path):
        import dataclasses
        from prompt_programs.options import GeneratedOptions
        entry = entry_for(PORTRAIT)
        store, rt = self._runtime(tmp_path, entry)
        sig = program_context(entry).signature
        store.append(gen_key(spec(), {}, sig, "prose", True, version="opts-1"),
                     {"round": 0, "options": ["braids", "pin curls", "an updo"]})
        store.append(gen_key(spec(), {}, sig, "prose", True), {"round": 0, "options": ["x1", "x2", "x3"]})
        # Revisions drawn before the version was recorded drew opts-1 pools and record no version.
        old = dataclasses.replace(rt, options=GeneratedOptions(store, program_context(entry), version="opts-1"))
        first = [prep.realize(entry, seed=s, runtime=old) for s in range(12) if not old.options.reset()]
        assert all("options" not in r.revision for r in first) and any("braids" in r.prompt for r in first)
        for s, r in enumerate(first):
            again = prep.realize(entry, seed=s, revision=r.revision,
                                 runtime=self._runtime(tmp_path, entry, revision=r.revision)[1])
            assert again.prompt == r.prompt and again.revision["id"] == r.revision["id"]
        new = prep.realize(entry, seed=0, runtime=self._runtime(tmp_path, entry)[1])
        assert new.revision["options"] == "opts-2"
        with pytest.raises(ProgramError, match="options version opts-9"):
            self._runtime(tmp_path, entry, revision={**new.revision, "options": "opts-9"})

    def test_dependent_pools_are_per_upstream_value(self, tmp_path):
        entry = entry_for(DEPENDENT)
        store = OptionStore(tmp_path)
        filler = OptionFiller(store, FakeGen())
        queued = start_options(entry, store=store, filler=filler, cfg=ON)
        contexts = {tuple(j.context.items()) for _, j in filler._jobs.values()}
        assert contexts == {(("era", "1920s"),), (("era", "1970s"),)} and len(queued) == 2

    async def test_prepare_hook_fills_in_the_background(self, tmp_path):
        entry = entry_for(PORTRAIT)
        store = OptionStore(tmp_path)
        gen = FakeGen()
        filler = OptionFiller(store, gen)
        queued = start_options(entry, store=store, filler=filler, cfg=ON)
        assert len(queued) == 3 and gen.calls == []  # role, hair, light; never the user's era list; no call yet
        await filler.drain()
        assert len(gen.calls) == 3
        r = prep.realize(entry, seed=1, runtime=runtime_for(entry, store=store, cfg=OFF))
        assert any("variant 0." in d.value for d in r.draws)
        assert start_options(entry, store=store, filler=filler, cfg=ON) == []  # already filled

    def test_the_prepare_hook_ignores_older_programs_and_never_raises(self, tmp_path):
        assert start_options({"program": 'emit("x")'}, store=OptionStore(tmp_path), cfg=ON) == []
        assert start_options({"program": "pick(", "key": "k"}, store=OptionStore(tmp_path), cfg=ON) == []

    def test_more_coming_is_reported(self, tmp_path):
        entry = entry_for(PORTRAIT)
        store = OptionStore(tmp_path)
        filler = OptionFiller(store, FakeGen())
        r = prep.realize(entry, seed=1, runtime=runtime_for(entry, store=store, filler=filler, cfg=ON))
        assert isinstance(r, DrawResult) and set(r.more_coming) == {"role", "hair", "light"}
        assert set(r.to_dict()["more_coming"]) == {"role", "hair", "light"}

    def test_default_realize_works_without_a_profile(self, monkeypatch):
        import prompt_programs.fluent as fl
        monkeypatch.setattr(fl, "_profile_store", lambda pid: None)
        r = prep.realize(entry_for(PORTRAIT), seed=2)
        assert r.revision["engine"] and "finger waves" in r.prompt

    def test_revisions_recorded_with_the_null_judge_still_replay(self, tmp_path):
        # Revisions from before the in-draw judge was removed record judge "null" and its
        # knobs: drawing judged nothing then either, so they replay exactly.
        entry = entry_for(PORTRAIT)
        r = prep.realize(entry, seed=3, runtime=self._runtime(tmp_path, entry)[1])
        old = {**r.revision, "judge": "null", "rarity": 0.3, "keep": "tiers", "wrong_cut": 0.9}
        rt = self._runtime(tmp_path, entry, revision=old)[1]
        assert prep.realize(entry, seed=3, revision=old, runtime=rt).prompt == r.prompt

    def test_a_replay_drawn_with_another_judge_says_so(self, tmp_path):
        entry = entry_for(PORTRAIT)
        r = prep.realize(entry, seed=1, runtime=self._runtime(tmp_path, entry)[1])
        with pytest.raises(ProgramError, match="judge d3-edge"):
            self._runtime(tmp_path, entry, revision={**r.revision, "judge": "d3-edge@abc/q1"})
        with pytest.raises(ProgramError, match="can't be replayed exactly"):
            prep.realize(entry, seed=1, revision={**r.revision, "judge": "fake-1"})

class TestStructuredOptions:
    def test_a_reply_that_is_exactly_a_json_list_is_read(self):
        from prompt_programs.options import parse_options, read_options
        assert read_options('```json\n["a sleek bob", "pin curls"]\n```') == ["a sleek bob", "pin curls"]
        assert read_options('{"options": ["finger waves"]}') == ["finger waves"]
        assert parse_options('  ["a sleek bob", "", "[x]", "pin curls"] ') == ["a sleek bob", "pin curls"]

    def test_anything_around_or_inside_the_list_is_not_mined_for_options(self):
        from prompt_programs.options import read_options
        assert read_options('Sure:\n["a sleek bob"]') is None              # text around the list
        assert read_options('["a sleek bob"]\nWait, the instructions say 12.') is None
        assert read_options("- a sleek bob\n- pin curls") is None            # lines are not a list
        assert read_options('["a sleek bob", 3]') is None                   # strings only

    @staticmethod
    def job():
        from prompt_programs.draws import PickSpec
        from prompt_programs.options import OptionJob, ProgramContext
        spec = PickSpec("hair", "Hairstyle", "her hairstyle", 1, "text", "pick", ["a sleek bob"], [])
        return OptionJob("k", spec, {}, ProgramContext(template="a woman with [Hairstyle]"), "a woman", 0)

    def fake(self, monkeypatch, replies, tool=True):
        from prompt_programs import options as opts
        calls = []

        async def endpoint(_pid):
            return ("e", "m"), tool and ("e", "m") not in opts._TEXT_ONLY

        async def ask(messages, project_id, tool):
            calls.append((messages, tool))
            got = replies.pop(0)
            if isinstance(got, Exception):
                raise got
            return got

        monkeypatch.setattr(opts, "_endpoint", endpoint)
        monkeypatch.setattr(opts, "_ask_options", ask)
        monkeypatch.setattr(opts, "_TEXT_ONLY", set())
        return calls

    async def test_the_tool_call_carries_the_options(self, monkeypatch):
        from prompt_programs.options import write_options
        calls = self.fake(monkeypatch, [("", '{"options": ["pin curls", "finger waves"]}')])
        assert await write_options(self.job()) == ["pin curls", "finger waves"]
        assert calls[0][1] is True and "write_options tool" in calls[0][0][0]["content"]

    async def test_an_unreadable_reply_is_asked_again_and_told_why(self, monkeypatch):
        from prompt_programs.options import write_options
        calls = self.fake(monkeypatch, [('Let me think. ["pin curls"]', None), ('["pin curls"]', None)], tool=False)
        assert await write_options(self.job()) == ["pin curls"]
        assert len(calls) == 2 and "wasn't a JSON list of strings" in calls[1][0][-1]["content"]

    async def test_a_model_that_skips_the_tool_gets_the_text_form(self, monkeypatch):
        from prompt_programs import options as opts
        calls = self.fake(monkeypatch, [("Here you go: pin curls", None), ('["pin curls"]', None)])
        assert await opts.write_options(self.job()) == ["pin curls"]
        assert [t for _, t in calls] == [True, False] and "JSON list of strings" in calls[1][0][0]["content"]
        assert ("e", "m") in opts._TEXT_ONLY

    async def test_a_broken_tool_call_is_asked_again_as_a_plain_list(self, monkeypatch):
        from prompt_programs.options import write_options
        # a tool-call parser that nests the list: never mined, asked again in the text form
        calls = self.fake(monkeypatch, [("", '{"options": [{"options": ["\\"pin curls\\""]}]}'), ('["pin curls"]', None)])
        assert await write_options(self.job()) == ["pin curls"]
        assert [t for _, t in calls] == [True, False]

    async def test_an_endpoint_without_tools_falls_back_to_text(self, monkeypatch):
        from prompt_programs import prepare as prep
        from prompt_programs.options import write_options
        err = RuntimeError('400 Bad Request: "auto" tool choice requires --enable-auto-tool-choice')
        calls = self.fake(monkeypatch, [err, ('["pin curls"]', None)])
        monkeypatch.setattr(prep, "_PROTOCOL", {})
        assert await write_options(self.job()) == ["pin curls"]
        assert prep._PROTOCOL[("e", "m")] == "text" and calls[-1][1] is False

    async def test_nothing_readable_twice_is_no_options(self, monkeypatch):
        from prompt_programs.options import write_options
        self.fake(monkeypatch, [("pin curls", None), ("still not a list", None)], tool=False)
        assert await write_options(self.job()) == []


class TestLookupKeyRule:
    @pytest.mark.parametrize("src", [
        'e = pick("e", about="her ethnicity", phase=1, seed=["a", "b"])\ntone = {"a": "x", "b": "y"}[e]\nemit(tone, e)\n',
        'e = pick("e", about="her ethnicity", phase=1, seed=["a", "b"])\ntone = {"a": "x"}.get(e, "z")\nemit(tone, e)\n',
        'e = pick("e", about="the era", phase=1, seed=["a", "b"])\n'
        'h = pick("h", by=e, options={"a": ["x"], "b": ["y"]}, phase=2)\nemit(e, h)\n',
    ])
    def test_a_generated_pick_cannot_be_a_lookup_key(self, src):
        from prompt_programs.draws import analyze
        from prompt_programs.runtime import ProgramError
        with pytest.raises(ProgramError, match="can't be a key to look something up"):
            analyze(src)

    def test_a_generated_pick_is_never_named_in_about(self):
        from prompt_programs.draws import analyze
        from prompt_programs.runtime import ProgramError
        src = ('h = pick("h", about="her job", seed=["nun"], phase=1)\n'
               'o = pick("o", about=f"what a {h} wears", seed=["x"], phase=2)\nemit(h, o)\n')
        with pytest.raises(ProgramError, match="Describe \"h\" in words"):
            analyze(src, strict=True)

    def test_a_pick_names_few_enough_lists(self):
        from prompt_programs.draws import analyze
        from prompt_programs.runtime import ProgramError
        six = '["1", "2", "3", "4", "5", "6"]'
        src = (f'a = pick("a", {six}, source="list", phase=1)\nb = pick("b", {six}, source="list", phase=1)\n'
               'o = pick("o", about=f"for {a} and {b}", seed=["x"], phase=2)\nemit(a, b, o)\n')
        with pytest.raises(ProgramError, match="36 combinations"):
            analyze(src, strict=True)
        assert analyze(src.replace(" and {b}", ""), strict=True).phased

    def test_a_list_passed_through_a_name_counts_its_values(self):
        from prompt_programs.draws import analyze
        from prompt_programs.runtime import ProgramError
        values = ", ".join(f'"{i}"' for i in range(33))
        src = (f'options = [{values}]\na = pick("a", options, source="list", phase=1)\n'
               'o = pick("o", about=f"for {a}", seed=["x"], phase=2)\nemit(a, o)\n')
        with pytest.raises(ProgramError, match="33 combinations"):
            analyze(src, strict=True)
        grown = src.replace("\na = pick", '\noptions.append("34")\na = pick')
        with pytest.raises(ProgramError, match="aren't written out"):
            analyze(grown, strict=True)
        aliased = ('options = ["base"]\nalias = options\nalias.extend([' + values + '])\n'
                   'a = pick("a", options, source="list", phase=1)\n'
                   'o = pick("o", about=f"for {a}", seed=["x"], phase=2)\nemit(a, o)\n')
        with pytest.raises(ProgramError, match="aren't written out"):
            analyze(aliased, strict=True)
        shared = aliased.replace('options = ["base"]\nalias = options\n', 'options = alias = ["base"]\n')
        with pytest.raises(ProgramError, match="aren't written out"):
            analyze(shared, strict=True)

    def test_a_generated_pick_named_under_an_if_on_it_is_still_named(self):
        from prompt_programs.draws import analyze
        from prompt_programs.runtime import ProgramError
        src = ('h = pick("h", about="her job", seed=["nun"], phase=1)\n'
               'if h:\n    o = pick("o", about=f"what a {h} wears", seed=["x"], phase=2)\n    emit(o)\nemit(h)\n')
        with pytest.raises(ProgramError, match="Describe \"h\" in words"):
            analyze(src, strict=True)

    def test_a_program_prepared_before_the_rule_still_draws(self, tmp_path):
        # pp-20 programs could name a generated pick in about=; they still draw, by today's
        # rule: a generated pick's value never keys a pool.
        src = ('job = pick("job", about="her job", seed=["nun", "lifeguard"], phase=1)\n'
               'outfit = pick("outfit", about=f"what a {job} wears", seed=["a coat"], phase=2)\nemit(job, outfit)\n')
        for version in ("pp-20", "pp-21"):
            entry = entry_for(src, version=version)
            rt = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF)
            assert prep.realize(entry, seed=1, runtime=rt).prompt
            assert [ctx for spec, ctx in rt.options.seen_specs() if spec.id == "outfit"] == [{}]

    def test_a_list_named_in_about_keys_the_pool_and_a_generated_pick_does_not(self, tmp_path):
        src = ('job = pick("job", ["nun", "lifeguard"], label="Job", source="list", phase=1, line=1)\n'
               'mood = pick("mood", about="her mood", seed=["calm"], phase=1)\n'
               'outfit = pick("outfit", about=f"what a {job} wears", seed=["a coat"], phase=2)\n'
               'if mood == "calm":\n    hat = pick("hat", about="her hat", seed=["a cap"], phase=2)\n'
               'emit(job, mood, outfit)\n')
        entry = entry_for(src)
        rt = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF)
        for seed in range(12):
            prep.realize(entry, seed=seed, runtime=rt)
            rt.options.reset()
        specs = {(spec.id, tuple(sorted(ctx.items()))) for spec, ctx in rt.options.seen_specs()}
        assert ("outfit", (("job", "nun"),)) in specs and ("outfit", (("job", "lifeguard"),)) in specs
        assert ("hat", ()) in specs  # the generated mood steers the branch but keys no pool

    @pytest.mark.parametrize("src", [
        # a user list (or a pick without about=) may be a key; derived text may be looked up too
        'e = pick("e", ["a", "b"], about="the era", source="list", phase=1)\ntone = {"a": "x", "b": "y"}[e]\nemit(tone)\n',
        'e = pick("e", ["a", "b"], phase=1)\ntone = {"a": "x", "b": "y"}[e]\nemit(tone)\n',
        'e = pick("e", about="her mood", phase=1, seed=["calm"])\nwords = {"x": 1}\nn = words[str(len(e) > 3)] if False else 1\nemit(e)\n',
    ])
    def test_fixed_lists_may_be_keys(self, src):
        from prompt_programs.draws import analyze
        assert analyze(src).phased


def test_a_malformed_revision_is_ignored(tmp_path):
    entry = entry_for(PORTRAIT)
    rt = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF,
                     revision={"pools": ["x"], "rarity": "lots", "wrong_cut": None})
    assert rt.options.limits == {}
    assert prep.realize(entry, seed=1, revision="nonsense", runtime=None).prompt


def test_settings_read_the_environment(monkeypatch):
    monkeypatch.setenv("STIMMA_FLUENT_GENERATE", "0")
    monkeypatch.setenv("STIMMA_FLUENT_JUDGE", "http")  # gone: ignored
    s = settings()
    assert s.generate_options is False and not hasattr(s, "judge")
