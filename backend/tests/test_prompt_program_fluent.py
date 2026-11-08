"""Fluent draws, step 2: generated options, the option cache and filler, judges,
the bad-pool check, the runtime wiring in realize(), and the evaluation hook."""

import asyncio
import json
import threading

import pytest

from prompt_programs import prepare as prep
from prompt_programs.draws import DrawResult, NullJudge, PickSpec, Question, draw, fixed_text
from prompt_programs.evaluate import draw_many, fill_options
from prompt_programs.fluent import CHECK_PROPOSALS, Runtime, pool_checker, program_context, runtime_for, start_options
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
        return [f"{job.spec.id} {ctx} option {job.round}.{i}".replace("  ", " ") for i in range(self.per_call)], "fake"


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
        assert store.options(a.key)[0] == "a option 0.0"

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
        assert any("option 0." in d.value for d in r.draws)
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
