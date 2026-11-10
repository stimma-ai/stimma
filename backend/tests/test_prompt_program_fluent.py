"""Fluent draws, step 2: generated options, the option cache and filler, judges,
the bad-pool check, the runtime wiring in realize(), and the evaluation hook."""

import asyncio
import json
import threading

import pytest

from prompt_programs import prepare as prep
from prompt_programs.draws import DEFAULT_RARITY, WRONG_CUT, DrawResult, NullJudge, PickSpec, Question, draw, fixed_text
from prompt_programs.runtime import ProgramError
from prompt_programs.evaluate import draw_many, fill_options
from prompt_programs.fluent import (
    CHECK_PROPOSALS, Runtime, pool_checker, prefill_judgments, program_context, runtime_for, start_options,
)
from prompt_programs.judge import (
    CachedJudge, FluentSettings, HttpJudge, JudgeUnavailable, build_judge, configured_judge, make_server,
    score_question, settings, tiers_from_answer,
)
from prompt_programs.options import (
    MAX_ROUNDS, THIN, GeneratedOptions, OptionFiller, OptionJob, OptionStore, ProgramContext, gen_key,
    generation_messages,
)
from prompt_programs.resolver import NoVocabulary

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

ON = FluentSettings(generate_options=True)
OFF = FluentSettings(generate_options=False)


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


class FakeJudge:
    version = "fake-1"
    null = False

    def __init__(self, wrong=()):
        self.wrong = set(wrong)
        self.calls = []

    def judge(self, state, questions):
        self.calls.append((state, list(questions)))
        return [{"wrong": 1.0} if (q.value in self.wrong or q.pick_id in self.wrong) else {"typical": 1.0} for q in questions]


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

    def test_the_resolver_resolves_nothing(self):
        assert NoVocabulary().resolve(spec()) is None and NoVocabulary.version == "none"


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


# --------------------------------------------------------------------------- judges

class TestJudges:
    def test_the_score_question_and_its_answer(self):
        q = score_question(Question("hair", "Hairstyle", "her hairstyle", "grey hair"))
        assert q["type"] == "score" and len(q["criteria"]) == 4 and q["criteria"][0].startswith("wrong")
        assert '[Hairstyle] (her hairstyle) is filled with "grey hair"' in q["instructions"]
        t = tiers_from_answer({"probabilities": {"0": 0.1, "1": 0.2, "2": 0.3, "3": 0.4}})
        assert t == {"typical": 0.4, "plausible": 0.3, "unusual": 0.2, "wrong": 0.1}

    def test_judgments_are_cached_across_draws_and_on_disk(self, tmp_path):
        inner = FakeJudge(wrong={"grey hair"})
        j = CachedJudge(inner, tmp_path / "j.sqlite")
        qs = [Question("hair", "Hairstyle", "her hairstyle", v) for v in ("grey hair", "a bob")]
        a = j.judge("A girl with [Hairstyle]", qs)
        b = j.judge("A girl with [Hairstyle]", list(reversed(qs)))
        assert a[0]["wrong"] == 1.0 and b[1]["wrong"] == 1.0 and len(inner.calls) == 1
        j.judge("A woman with [Hairstyle]", qs[:1])  # a new state is a new judgment
        assert len(inner.calls) == 2 and j.stats()["passes"] == 2 and j.stats()["hits"] == 2
        again = CachedJudge(FakeJudge(), tmp_path / "j.sqlite")  # a new process: from disk
        assert again.judge("A girl with [Hairstyle]", qs[:1])[0]["wrong"] == 1.0 and again.passes == 0

    def test_a_new_judge_version_is_a_new_judgment(self, tmp_path):
        a = CachedJudge(FakeJudge(wrong={"x"}), tmp_path / "j.sqlite")
        a.judge("s", [Question("p", "P", "", "x")])
        other = FakeJudge()
        other.version = "fake-2"
        b = CachedJudge(other, tmp_path / "j.sqlite")
        assert b.judge("s", [Question("p", "P", "", "x")])[0] == {"typical": 1.0} and b.passes == 1

    def test_the_http_judge_talks_to_the_server(self):
        server = make_server(FakeJudge(wrong={"grey hair"}), "127.0.0.1", 0)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            j = HttpJudge(f"http://127.0.0.1:{server.server_address[1]}")
            assert j.version == "fake-1"
            got = j.judge("A girl with [Hairstyle]", [Question("hair", "Hairstyle", "", "grey hair"),
                                                      Question("hair", "Hairstyle", "", "a bob")])
            assert got[0]["wrong"] == 1.0 and got[1]["typical"] == 1.0
        finally:
            server.shutdown()

    def test_an_absent_server_is_unavailable(self):
        with pytest.raises(JudgeUnavailable):
            HttpJudge("http://127.0.0.1:9", timeout=0.5)

    def test_configuration_defaults_to_the_null_judge(self, monkeypatch):
        assert configured_judge(FluentSettings()).version == "null"
        assert build_judge(FluentSettings(judge="none")).version == "null"
        with pytest.raises(JudgeUnavailable):
            build_judge(FluentSettings(judge="http"))
        # a judge that can't load stays null, and the product keeps drawing
        broken = FluentSettings(judge="http", judge_url="http://127.0.0.1:9")
        assert configured_judge(broken, wait=True).version == "null"
        assert configured_judge(broken).version == "null"

    def test_settings_read_the_environment(self, monkeypatch):
        monkeypatch.setenv("STIMMA_FLUENT_JUDGE", "HTTP")
        monkeypatch.setenv("STIMMA_FLUENT_JUDGE_URL", "http://judge:8790")
        monkeypatch.setenv("STIMMA_FLUENT_RARITY", "0.1")
        monkeypatch.setenv("STIMMA_FLUENT_GENERATE", "0")
        s = settings()
        assert (s.judge, s.judge_url, s.rarity, s.wrong_cut, s.generate_options) == ("http", "http://judge:8790", 0.1, 0.5, False)


# --------------------------------------------------------------------------- the bad-pool check

class TestBadPoolCheck:
    def _setup(self, tmp_path, signature, wrong):
        store = OptionStore(tmp_path)
        filler = OptionFiller(store, FakeGen(table={"hair": [f"bad {i}" for i in range(12)]}))
        prog = program(signature=signature)
        judge = FakeJudge(wrong=wrong)
        opts = GeneratedOptions(store, prog, filler=filler, checker=pool_checker(judge, 0.5))
        return store, filler, opts, judge

    async def test_a_pool_that_fits_passes(self, tmp_path):
        store, filler, opts, judge = self._setup(tmp_path, "a jazz portrait", wrong=())
        opts.get(spec(), {})
        await filler.drain()
        assert filler.checks[0]["ok"] == CHECK_PROPOSALS and not filler._jobs
        assert judge.calls[0][0] == "A portrait of a [Role] with [Hairstyle]"  # the fixed text

    async def test_a_shared_pool_that_does_not_fit_switches_to_this_prompt(self, tmp_path):
        bad = {f"bad {i}" for i in range(12)} | {"finger waves"}
        store, filler, opts, judge = self._setup(tmp_path, "a jazz portrait", wrong=bad)

        async def gen(job):  # the shared pool is off; options written for the prompt fit
            good = job.signature == program().template
            return [f"{'good' if good else 'bad'} {i}" for i in range(12)], "fake"
        filler.generator = gen
        opts.get(spec(), {})
        await filler.drain()
        assert filler.checks[0]["ok"] < 5
        assert store.specific("prog1") == ["hair"]
        fresh = GeneratedOptions(store, program(signature="a jazz portrait"))
        pool = fresh.get(spec(), {})
        assert pool.key == "hair: her hairstyle | written for this prompt"
        recs = store.records(gen_key(spec(), {}, program().template, "prose", True))
        assert len(recs) == 1 and recs[0]["options"][0] == "good 0" and filler.checks[1]["ok"] >= 5

    async def test_a_prompt_keyed_pool_that_does_not_fit_gets_a_round_told_what_failed(self, tmp_path):
        bad = {f"bad {i}" for i in range(12)} | {"finger waves"}
        store, filler, opts, judge = self._setup(tmp_path, "", wrong=bad)
        opts.get(spec(), {})
        await filler.drain()
        key = gen_key(spec(), {}, program().template, "prose", True)
        recs = store.records(key)
        avoid = recs[1]["inputs"]["avoid"] if len(recs) == 2 else []
        assert len(recs) == 2 and recs[1]["round"] == 1 and avoid and set(avoid) <= bad


# --------------------------------------------------------------------------- the runtime in realize()

class TestRealize:
    def _runtime(self, tmp_path, entry, judge=None, filler=None, cfg=OFF, revision=None):
        store = OptionStore(tmp_path)
        return store, runtime_for(entry, store=store, filler=filler, judge=judge or NullJudge(), cfg=cfg, revision=revision)

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
        assert r.revision["pools"]["hair: her hairstyle"] == 3 and r.revision["judge"] == "null"

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
        r = prep.realize(entry, seed=1, runtime=runtime_for(entry, store=store, judge=NullJudge(), cfg=OFF))
        assert any("variant 0." in d.value for d in r.draws)
        assert start_options(entry, store=store, filler=filler, cfg=ON) == []  # already filled

    def test_the_prepare_hook_ignores_older_programs_and_never_raises(self, tmp_path):
        assert start_options({"program": 'emit("x")'}, store=OptionStore(tmp_path), cfg=ON) == []
        assert start_options({"program": "pick(", "key": "k"}, store=OptionStore(tmp_path), cfg=ON) == []

    def test_a_pick_with_nothing_accepted_asks_for_more_at_high_priority(self, tmp_path):
        entry = entry_for(PORTRAIT)
        store = OptionStore(tmp_path)
        ctx = program_context(entry)
        hair = spec()
        key = gen_key(hair, {}, ctx.signature, "prose", True)
        store.append(key, {"round": 0, "options": [f"style {i}" for i in range(10)]})
        filler = OptionFiller(store, FakeGen())
        judge = FakeJudge(wrong={"hair"})
        rt = runtime_for(entry, store=store, filler=filler, judge=judge, cfg=ON)
        r = prep.realize(entry, seed=3, runtime=rt)
        assert r.unresolved[0]["id"] == "hair"
        assert filler._jobs[key][0] == 0  # high

    def test_more_coming_is_reported(self, tmp_path):
        entry = entry_for(PORTRAIT)
        store = OptionStore(tmp_path)
        filler = OptionFiller(store, FakeGen())
        r = prep.realize(entry, seed=1, runtime=runtime_for(entry, store=store, filler=filler, judge=NullJudge(), cfg=ON))
        assert isinstance(r, DrawResult) and set(r.more_coming) == {"role", "hair", "light"}
        assert set(r.to_dict()["more_coming"]) == {"role", "hair", "light"}

    def test_default_realize_works_without_a_profile_or_judge(self, monkeypatch):
        import prompt_programs.fluent as fl
        monkeypatch.setattr(fl, "_profile_store", lambda pid: None)
        r = prep.realize(entry_for(PORTRAIT), seed=2)
        assert r.revision["judge"] == "null" and "finger waves" in r.prompt

    def test_the_revision_carries_knob_and_cut(self, tmp_path):
        entry = entry_for(PORTRAIT)
        rt = runtime_for(entry, store=OptionStore(tmp_path), judge=FakeJudge(), cfg=FluentSettings(rarity=0.2, wrong_cut=0.4,
                                                                                                      generate_options=False))
        r = prep.realize(entry, seed=1, runtime=rt)
        assert r.revision["rarity"] == 0.2 and r.revision["wrong_cut"] == 0.4 and r.revision["judge"] == "fake-1"
        replay = runtime_for(entry, store=OptionStore(tmp_path), judge=FakeJudge(), cfg=OFF, revision=r.revision)
        assert (replay.rarity, replay.wrong_cut) == (0.2, 0.4)

    def test_a_replay_uses_the_recorded_judge_and_the_old_defaults(self, tmp_path):
        entry = entry_for(PORTRAIT)
        r = prep.realize(entry, seed=3, runtime=runtime_for(entry, store=OptionStore(tmp_path), judge=NullJudge(), cfg=OFF))
        today = FluentSettings(wrong_cut=0.9, rarity=0.9, generate_options=False)
        rt = runtime_for(entry, store=OptionStore(tmp_path), judge=FakeJudge(wrong={"role", "hair", "light"}), cfg=today,
                         revision=r.revision)
        assert isinstance(rt.judge, NullJudge)
        assert prep.realize(entry, seed=3, revision=r.revision, runtime=rt).prompt == r.prompt
        old = {k: v for k, v in r.revision.items() if k not in ("rarity", "wrong_cut")}
        rt = runtime_for(entry, store=OptionStore(tmp_path), judge=NullJudge(), cfg=today, revision=old)
        assert (rt.rarity, rt.wrong_cut) == (DEFAULT_RARITY, WRONG_CUT)

    def test_a_replay_whose_judge_is_gone_says_so(self, tmp_path):
        entry = entry_for(PORTRAIT)
        r = prep.realize(entry, seed=1, runtime=runtime_for(entry, store=OptionStore(tmp_path), judge=FakeJudge(), cfg=OFF))
        with pytest.raises(ProgramError):
            runtime_for(entry, store=OptionStore(tmp_path), judge=NullJudge(), cfg=OFF, revision=r.revision)

    def test_a_judge_that_stops_answering_falls_back_to_none(self, monkeypatch):
        import prompt_programs.fluent as fl

        class Dropping(FakeJudge):
            def judge(self, state, questions):
                raise JudgeUnavailable("gone")
        monkeypatch.setattr(fl, "_profile_store", lambda pid: None)
        monkeypatch.setattr(fl, "configured_judge", lambda cfg=None: Dropping())
        r = prep.realize(entry_for(PORTRAIT), seed=2)
        assert r.revision["judge"] == "null"
        with pytest.raises(ProgramError):  # an exact replay never falls back
            prep.realize(entry_for(PORTRAIT), seed=2, revision={**r.revision, "judge": "fake-1"})


# --------------------------------------------------------------------------- the evaluation hook

class TestEvaluate:
    async def test_fill_then_draw_many(self, tmp_path):
        entry = entry_for(PORTRAIT)
        store = OptionStore(tmp_path)
        gen = FakeGen()
        filled = await fill_options(entry, store, generator=gen, rounds=2)
        assert filled["calls"] == 6 and filled["failures"] == 0
        again = await fill_options(entry, store, generator=gen)
        assert again["calls"] == 0  # pack-rat: every round is on disk
        judge = CachedJudge(FakeJudge(wrong={"jazz singer"}))
        out = draw_many(entry, 20, judge=judge, store=store, rarity=0.3)
        assert out["stats"]["draws"] == 20 and out["stats"]["aborted"] == 0
        assert all(r["values"]["role"] != "jazz singer" for r in out["draws"])
        assert out["stats"]["judge"]["version"] == "fake-1" and out["stats"]["judge"]["passes"] > 0
        assert out["stats"]["ms_p50"] is not None and out["draws"][0]["revision"]["judge"] == "fake-1"
        assert len({r["values"]["hair"] for r in out["draws"]}) > 3

    async def test_fill_runs_the_bad_pool_check_with_a_judge(self, tmp_path):
        entry = entry_for(PORTRAIT)
        filled = await fill_options(entry, OptionStore(tmp_path), generator=FakeGen(), judge=FakeJudge())
        assert len(filled["checks"]) == 3 and all(c["ok"] == CHECK_PROPOSALS for c in filled["checks"])

    def test_aborted_draws_are_counted(self, tmp_path):
        entry = entry_for(PORTRAIT)
        out = draw_many(entry, 3, edits={"era": {"remove": ["1920s", "1970s", "1990s"]}}, store=OptionStore(tmp_path))
        assert out["stats"]["aborted"] == 3 and out["draws"][0]["aborted"]["choice_id"] == "era"

    def test_rows_are_json(self, tmp_path):
        out = draw_many(entry_for(PORTRAIT), 2, store=OptionStore(tmp_path))
        json.dumps(out)


# --------------------------------------------------------------------------- parsing and the lookup-key rule

class TestParseOptions:
    def test_the_first_json_list_wins(self):
        from prompt_programs.options import parse_options
        reply = 'Sure:\n```json\n["a sleek bob", "pin curls (expected)", "finger waves"]\n```\n["ignored"]'
        assert parse_options(reply) == ["a sleek bob", "pin curls", "finger waves"]

    def test_leaked_reasoning_is_not_an_option(self):
        from prompt_programs.options import parse_options
        reply = ("[\nof South Asian descent\nof Hispanic descent\n]\n```\nWait, the instructions say \"Write 12 options\".\n"
                 "of East Asian descent (Default/Expected)\nActually, the prompt asks for 12 *different* options.\n"
                 "Here is the corrected list:\nLet's try a real list.\n- of West African descent")
        assert parse_options(reply) == ["of South Asian descent", "of Hispanic descent", "of East Asian descent",
                                        "of West African descent"]


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

    def test_a_program_prepared_before_the_rule_draws_as_it_did(self, tmp_path):
        # pp-20 programs could name a generated pick in about=; they still draw, keyed by its value.
        src = ('job = pick("job", about="her job", seed=["nun", "lifeguard"], phase=1)\n'
               'outfit = pick("outfit", about=f"what a {job} wears", seed=["a coat"], phase=2)\nemit(job, outfit)\n')
        entry = entry_for(src, version="pp-20")
        rt = runtime_for(entry, store=OptionStore(tmp_path), judge=NullJudge(), cfg=OFF)
        for seed in range(8):
            prep.realize(entry, seed=seed, runtime=rt)
            rt.options.reset()
        specs = {(spec.id, tuple(sorted(ctx.items()))) for spec, ctx in rt.options.seen_specs()}
        assert ("outfit", (("job", "nun"),)) in specs and ("outfit", (("job", "lifeguard"),)) in specs
        rt = runtime_for(entry_for(src, version="pp-21"), store=OptionStore(tmp_path), judge=NullJudge(), cfg=OFF)
        prep.realize(entry_for(src, version="pp-21"), seed=1, runtime=rt)
        assert [ctx for spec, ctx in rt.options.seen_specs() if spec.id == "outfit"] == [{}]  # today's rule

    def test_a_list_named_in_about_keys_the_pool_and_a_generated_pick_does_not(self, tmp_path):
        src = ('job = pick("job", ["nun", "lifeguard"], label="Job", source="list", phase=1, line=1)\n'
               'mood = pick("mood", about="her mood", seed=["calm"], phase=1)\n'
               'outfit = pick("outfit", about=f"what a {job} wears", seed=["a coat"], phase=2)\n'
               'if mood == "calm":\n    hat = pick("hat", about="her hat", seed=["a cap"], phase=2)\n'
               'emit(job, mood, outfit)\n')
        entry = entry_for(src)
        rt = runtime_for(entry, store=OptionStore(tmp_path), judge=NullJudge(), cfg=OFF)
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
    rt = runtime_for(entry, store=OptionStore(tmp_path), judge=NullJudge(), cfg=OFF,
                     revision={"pools": ["x"], "rarity": "lots", "wrong_cut": None})
    assert (rt.rarity, rt.wrong_cut, rt.options.limits) == (0.3, 0.5, {})
    assert prep.realize(entry, seed=1, revision="nonsense", runtime=None).prompt


# --------------------------------------------------------------------------- keep mode, prefill, adapters

class CountingJudge(FakeJudge):
    """Scores from a table by value; counts the questions it is asked."""

    def __init__(self, table=None):
        super().__init__()
        self.table = table or {}
        self.asked = 0

    def judge(self, state, questions):
        self.calls.append((state, list(questions)))
        self.asked += len(questions)
        return [self.table.get(q.value, {"typical": 1.0}) for q in questions]


class TestKeepMode:
    SRC = 'hair = pick("hair", ["brown hair", "grey hair", "blue hair"], source="list", phase=1)\nemit("A woman with", hair)\n'

    def test_cut_mode_keeps_every_value_that_isnt_wrong(self):
        judge = CountingJudge({"grey hair": {"unusual": 1.0}, "blue hair": {"wrong": 0.9, "typical": 0.1}})
        got = [{d.id: d.value for d in draw(self.SRC, s, judge=judge, keep="cut", rarity=0.0).draws}["hair"] for s in range(300)]
        assert "blue hair" not in got and 0.35 < got.count("grey hair") / 300 < 0.65  # unusual isn't scaled down
        tiers = [{d.id: d.value for d in draw(self.SRC, s, judge=judge, keep="tiers", rarity=0.0).draws}["hair"] for s in range(100)]
        assert set(tiers) == {"brown hair"}

    def test_the_runtime_defaults_to_cut_and_records_it(self, tmp_path):
        assert FluentSettings().keep == "cut" and settings().keep == "cut"
        entry = entry_for(PORTRAIT)
        r = prep.realize(entry, seed=1, runtime=runtime_for(entry, store=OptionStore(tmp_path), judge=FakeJudge(), cfg=OFF))
        assert r.revision["keep"] == "cut"
        old = dict(r.revision)
        old.pop("keep")  # a revision from before keep modes drew with tiers
        assert runtime_for(entry, store=OptionStore(tmp_path), judge=FakeJudge(), cfg=OFF, revision=old).keep == "tiers"

    def test_keep_mode_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("STIMMA_FLUENT_KEEP", "tiers")
        assert settings().keep == "tiers"
        monkeypatch.setenv("STIMMA_FLUENT_KEEP", "nonsense")
        assert settings().keep == "cut"


class TestPrefill:
    def test_phase_one_is_judged_against_the_fixed_text(self):
        judge = FakeJudge()
        draw(PORTRAIT, 3, judge=judge)
        assert judge.calls[0][0] == fixed_text(PORTRAIT)

    def test_prefetch_changes_no_draw(self):
        table = {"nurse": {"wrong": 1.0}, "pin curls": {"unusual": 1.0}}
        for seed in range(10):
            a = draw(PORTRAIT, seed, judge=CountingJudge(table))
            b = draw(PORTRAIT, seed, judge=CountingJudge(table), prefetch=48)
            assert a.prompt == b.prompt

    def test_prefilled_judgments_serve_later_draws(self, tmp_path):
        entry = entry_for(PORTRAIT)
        store = OptionStore(tmp_path)
        ctx = program_context(entry)
        for s, opts in ((spec(), ["a sleek bob", "pin curls", "an updo"]),
                        (spec(id="role", about="the woman's job", seeds=("jazz singer", "nurse"), label="Role"), ["a pilot", "a chemist"]),
                        (spec(id="light", about="the lighting", seeds=("soft window light",), label="Light"), ["neon glow"])):
            store.append(gen_key(s, {}, ctx.signature, "prose", True), {"round": 0, "options": opts})
        cold = CountingJudge()
        draw_many(entry, 10, judge=CachedJudge(cold), store=store, seeds=range(100, 110))
        inner = CountingJudge()
        judge = CachedJudge(inner, tmp_path / "j.sqlite")
        stats = prefill_judgments(entry, judge, store=store, draws=12, cfg=OFF)
        assert stats["draws"] == 12 and stats["questions"] > 0
        before = inner.asked
        out = draw_many(entry, 10, judge=judge, store=store, seeds=range(100, 110))
        assert inner.asked - before < cold.asked / 3  # most of what the draws asked was already judged
        assert out["stats"]["aborted"] == 0
        again = CachedJudge(CountingJudge(), tmp_path / "j.sqlite")  # and it survives a restart
        assert again.judge(fixed_text(PORTRAIT), [Question("role", "Role", "the woman's job", "a pilot")]) and again.passes == 0

    def test_the_null_judge_prefills_nothing(self, tmp_path):
        assert prefill_judgments(entry_for(PORTRAIT), NullJudge(), store=OptionStore(tmp_path)) == {"draws": 0}

    async def test_prefill_runs_in_the_background_after_the_fills(self, tmp_path):
        from prompt_programs.fluent import schedule_prefill
        entry = entry_for(PORTRAIT)
        store = OptionStore(tmp_path)
        filler = OptionFiller(store, FakeGen())
        judge = CachedJudge(CountingJudge())
        queued = start_options(entry, store=store, filler=filler, cfg=ON, prefill=False)
        task = schedule_prefill(entry, judge, filler, queued, store=store, wait_seconds=10)
        await filler.drain()
        stats = await asyncio.wait_for(task, 30)
        assert stats["draws"] > 0 and stats["questions"] > 0
        assert schedule_prefill(entry, NullJudge(), filler, queued, store=store) is None


class TestAdapterAndBatching:
    def test_the_adapter_judge_wraps_an_eval_adapter(self, monkeypatch):
        import sys
        import types
        from prompt_programs.judge import AdapterJudge
        mod = types.ModuleType("fake_adapters")

        class Obj:
            revision = "abcdef123456"

            def judge(self, state, picks, form="score"):
                return [{"wrong": 1.0 if v == "grey hair" else 0.0, "typical": 0.0 if v == "grey hair" else 1.0}
                        for _, _, v in picks]
        mod.load = lambda name, device="cuda": Obj()
        monkeypatch.setitem(sys.modules, "fake_adapters", mod)
        j = AdapterJudge("fake_adapters", "d3-mini", "cuda")
        assert j.version == "d3-mini@abcdef12/adapter-score"
        got = j.judge("s", [Question("hair", "Hair", "", "grey hair"), Question("hair", "Hair", "", "a bob")])
        assert got[0]["wrong"] == 1.0 and got[1] == {"typical": 1.0, "plausible": 0.0, "unusual": 0.0, "wrong": 0.0}

    def test_big_passes_are_split(self):
        inner = CountingJudge()
        j = CachedJudge(inner, batch=8)
        j.judge("s", [Question("p", "P", "", f"v{i}") for i in range(20)])
        assert [len(qs) for _, qs in inner.calls] == [8, 8, 4] and j.passes == 3
