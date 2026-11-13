"""Fluent's written options: the option cache and filler, the options service, and how
realize() draws from them."""

import asyncio
import json
import threading

import pytest

from prompt_programs import program as prep
from prompt_programs.fill import DrawResult, PickSpec
from prompt_programs.fill import ProgramError
from prompt_programs.fluent import program_context, runtime_for, start_options
from prompt_programs.judge import FluentSettings, settings
from prompt_programs.options import (
    MAX_ROUNDS, THIN, GeneratedOptions, OptionFiller, OptionJob, OptionStore, ProgramContext, gen_key,
    generation_messages,
)

PORTRAIT = "A portrait of a <role> in the {1920s|1970s|1990s} with <hair>, <light>"


def _free(n, label, about, kinds):
    return {"n": n, "kind": "free", "label": label, "lead": "", "free": {"about": about, "kinds": kinds, "instead": []}}


READINGS = (_free(1, "Role", "the woman's job", ["jazz singer", "nurse"]),
            _free(2, "Hairstyle", "her hairstyle", ["finger waves"]),
            _free(3, "Light", "the lighting", ["soft window light"]))


ON = FluentSettings(generate_options=True, fix_model="off")
OFF = FluentSettings(generate_options=False, fix_model="off")


def entry_for(prompt=PORTRAIT, readings=READINGS, **kw):
    """A prepared entry for a prompt and its readings; its picks are named as these tests name
    them: the list is "era", each slot its words."""
    from prompt_programs.slots import compose, parse
    e = compose(parse(prompt), {r["n"]: r for r in readings}, {1: "Era"})
    for x in (*e["picks"], *e["choices"], *e["lists"]):
        if x["id"] == "list1":
            x["id"] = "era"
    e["template"] = e["template"].replace("[List 1]", "[Era]")
    return {**e, "key": kw.pop("key", "prog1"), **kw}


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
        entry = entry_for("a {nun|lifeguard} in {rain|sun}, <o>", readings=(),
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


# --------------------------------------------------------------------------- realize

class TestRealize:
    def _runtime(self, tmp_path, entry, filler=None, cfg=OFF, revision=None):
        store = OptionStore(tmp_path)
        return store, runtime_for(entry, store=store, filler=filler, cfg=cfg, revision=revision)

    def _key(self, tmp_path, entry, cid):
        """Where a pick's written options are stored, as the options service names it."""
        store, rt = self._runtime(tmp_path, entry)
        prep.realize(entry, seed=0, runtime=rt)
        return next(rt.options._where(sp, ctx)[1] for sp, ctx in rt.options.seen_specs() if sp.id == cid)

    def test_the_template_masks_every_pick(self):
        assert entry_for()["template"] == "A portrait of a [Role] in the [Era] with [Hairstyle], [Light]"
        ctx = program_context(entry_for(PORTRAIT, context="a 1920s portrait"))
        assert ctx.signature == "a 1920s portrait" and ctx.template.startswith("A portrait of a [Role]")

    def test_generated_options_reach_the_prompt(self, tmp_path):
        entry = entry_for(PORTRAIT)
        store = OptionStore(tmp_path)
        for cid, opts in (("hair", ["a sleek bob", "pin curls"]), ("light", ["neon glow"])):
            store.append(self._key(tmp_path, entry, cid), {"round": 0, "options": opts})
        seen = set()
        for seed in range(60):
            store_, rt = self._runtime(tmp_path, entry)
            r = prep.realize(entry, seed=seed, runtime=rt)
            seen |= {d.value for d in r.draws}
        assert {"a sleek bob", "pin curls", "neon glow"} <= seen
        assert r.revision["pools"]["hair: her hairstyle | kinds"] == 4 and "judge" not in r.revision

    def test_the_same_revision_replays_after_pools_grow(self, tmp_path):
        entry = entry_for(PORTRAIT)
        store = OptionStore(tmp_path)
        key = self._key(tmp_path, entry, "hair")
        store.append(key, {"round": 0, "options": ["a sleek bob", "pin curls"]})
        first = [prep.realize(entry, seed=s, runtime=self._runtime(tmp_path, entry)[1]) for s in range(12)]
        store.append(key, {"round": 1, "options": ["a beehive", "an afro", "braids"]})
        for s, r in enumerate(first):
            again = prep.realize(entry, seed=s, revision=r.revision, runtime=self._runtime(tmp_path, entry, revision=r.revision)[1])
            assert again.prompt == r.prompt and again.revision["id"] == r.revision["id"]
        grown = prep.realize(entry, seed=0, runtime=self._runtime(tmp_path, entry)[1])
        assert grown.revision["pools"]["hair: her hairstyle | kinds"] == 7

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

    def test_the_prepare_hook_ignores_entries_with_nothing_to_draw_and_never_raises(self, tmp_path):
        assert start_options({"picks": []}, store=OptionStore(tmp_path), cfg=ON) == []
        assert start_options({"picks": [{"id": "x"}], "key": "k"}, store=OptionStore(tmp_path), cfg=ON) == []

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
        from prompt_programs.fill import PickSpec
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

    async def test_a_torn_tool_call_is_asked_again_as_a_plain_list(self, monkeypatch):
        from prompt_programs import options as opts
        # a quantized model's tool call as its parser returns it: delimiters left in, a list split at commas
        torn = json.dumps({"options": ["fear: [\n  \"a weary look with heavy eyelids and a faint", "tired frown\"",
                                       "a maroon red door<|\"|>", "a burgundy red door</li>,"]})
        calls = self.fake(monkeypatch, [("", torn), ('["pin curls"]', None)])
        monkeypatch.setattr(opts, "_TORN", {})
        assert await opts.write_options(self.job()) == ["pin curls"]
        assert [t for _, t in calls] == [True, False]
        assert ("e", "m") not in opts._TEXT_ONLY            # once is not a habit
        calls = self.fake(monkeypatch, [("", torn), ('["finger waves"]', None)])
        assert await opts.write_options(self.job()) == ["finger waves"]
        assert ("e", "m") in opts._TEXT_ONLY                # twice: the text form from now on

    def test_a_torn_string_is_never_an_option(self):
        from prompt_programs.options import clean_option, torn
        assert clean_option('"her chestnut hair"') == "her chestnut hair"       # a quoted option is its text
        assert clean_option('a sign that says "OPEN"') == 'a sign that says "OPEN"'
        assert clean_option('a 12" vinyl record') == 'a 12" vinyl record'
        for bad in ('tired frown"', 'a maroon red door<|"|>', "a burgundy red door</li>,", "standing tall**\n,",
                    'fear: [\n  "a weary look'):
            assert torn(bad) and clean_option(bad) is None

    async def test_an_endpoint_without_tools_falls_back_to_text(self, monkeypatch):
        from prompt_programs import program as prep
        from prompt_programs.options import write_options
        err = RuntimeError('400 Bad Request: "auto" tool choice requires --enable-auto-tool-choice')
        calls = self.fake(monkeypatch, [err, ('["pin curls"]', None)])
        monkeypatch.setattr(prep, "PROTOCOL", {})
        assert await write_options(self.job()) == ["pin curls"]
        assert prep.PROTOCOL[("e", "m")] == "text" and calls[-1][1] is False

    async def test_nothing_readable_twice_is_no_options(self, monkeypatch):
        from prompt_programs.options import write_options
        self.fake(monkeypatch, [("pin curls", None), ("still not a list", None)], tool=False)
        assert await write_options(self.job()) == []




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
