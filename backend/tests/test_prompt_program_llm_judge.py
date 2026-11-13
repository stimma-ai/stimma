"""The judge: the Tool View model answers no / rare / yes for each choice of a finished draw."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from prompt_programs import llm_judge
from prompt_programs.fix import Item, fix_mode, judge_identity, realize_and_fix
from prompt_programs.judge import FluentSettings

from test_prompt_program_fix import PROFILE, entry_for, profile  # noqa: F401  (profile: the store fixture)

SKY = {"n": 1, "kind": "free", "label": "Sky", "lead": " under", "category": "",
       "free": {"about": "the sky", "kinds": [], "instead": [], "lists": []}}
CROP = {"n": 1, "kind": "free", "label": "Crop", "lead": " of", "category": "",
        "free": {"about": "what grows", "kinds": [], "instead": [], "lists": []}}


def items(*values):
    return [Item(f"A photo of a man with [Eyes] eyes, asleep ({v}).", "Eyes", "his eye color", v, "a man asleep") for v in values]


class Loop:
    """An event loop on its own thread, as the app has, with the model call replaced."""

    def __init__(self, monkeypatch, answer):
        self.loop = asyncio.new_event_loop()
        self.asked = []
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

        async def call(judge, head, chunk):
            self.asked.append(chunk)
            return {i + 1: a for i, k in enumerate(chunk) if (a := answer(k)) is not None}
        monkeypatch.setattr(llm_judge.LlmJudge, "_call", call)
        self.judge = llm_judge.LlmJudge(self.loop, SimpleNamespace(model="m"))

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


@pytest.fixture
def loop(monkeypatch):
    made = []

    def make(answer):
        made.append(Loop(monkeypatch, answer))
        return made[-1]
    yield make
    for m in made:
        m.close()


def test_no_is_rerolled_yes_is_kept_and_an_unanswered_choice_stands(loop):
    lp = loop(lambda k: {"hazel": "no", "brown": "yes"}.get(k[4]))
    got = lp.judge.p_wrong(items("hazel", "brown", "gray"))
    assert got[0] > lp.judge.cut and got[1] == 0.0 and got[2] == 0.0
    assert lp.judge.version == "llm:m" and lp.judge.reroll_all


def test_rare_is_kept_about_one_time_in_four_and_the_same_every_time(loop):
    lp = loop(lambda k: "rare")
    its = items(*[f"value {i}" for i in range(400)])
    got = lp.judge.p_wrong(its)
    kept = sum(p < lp.judge.cut for p in got)
    assert 60 < kept < 140
    assert lp.judge.p_wrong(its) == got


def test_a_draws_choices_go_in_one_call_and_an_answer_is_asked_once(loop):
    lp = loop(lambda k: "yes")
    one = [Item("A [Age] man with [Hair] hair on a [Sofa].".replace(f"[{lab}]", "X", 0), lab, "", val, "a man")
           for lab, val in (("Age", "old"), ("Hair", "gray"), ("Sofa", "red sofa"))]
    # the same finished prompt, each with its own choice masked
    full = "A old man with gray hair on a red sofa."
    one = [Item(full.replace(val, f"[{lab}]", 1), lab, "", val, "a man") for lab, val in (("Age", "old"), ("Hair", "gray"), ("Sofa", "red sofa"))]
    other = [Item("A [Age] woman.", "Age", "", "young", "a woman")]
    lp.judge.p_wrong(one + other)
    assert sorted(len(c) for c in lp.asked) == [1, 3]
    lp.judge.p_wrong(one + other)
    assert len(lp.asked) == 2


def test_a_failed_call_judges_nothing(monkeypatch, loop):
    lp = loop(lambda k: "no")

    async def boom(judge, head, chunk):
        raise RuntimeError("model down")
    monkeypatch.setattr(llm_judge.LlmJudge, "_call", boom)
    assert lp.judge.p_wrong(items("hazel")) == [0.0]


def test_the_reply_is_read_line_by_line():
    text = '{"id": 1, "answer": "no"}\n{"id": 2, "answer": "rare"}\nnoise\n{"id": 3, "answer": "yes"}'
    assert {int(m.group(1)): m.group(2) for m in llm_judge._ANSWER.finditer(text)} == {1: "no", 2: "rare", 3: "yes"}


def test_default_means_the_tool_view_model_and_without_it_a_draw_ships_unjudged():
    llm_judge.reset()
    cfg = FluentSettings()
    assert fix_mode(cfg.fix_model) == "default" and judge_identity(cfg) == "llm"
    entry = entry_for("A field under <sky>.", (SKY,), {"sky": ["a clear sky", "a stormy sky"]}, key="k")
    r, rec = realize_and_fix(entry, seed=3, cfg=cfg, profile_id=PROFILE)
    assert r.prompt in ("A field under a clear sky.", "A field under a stormy sky.")
    assert rec == {"judge": "llm", "skipped": "unavailable"}


def test_everything_refused_in_a_round_is_rerolled_together(monkeypatch, loop):
    lp = loop(lambda k: "no" if k[4] in ("a stormy sky", "wheat") else "yes")
    monkeypatch.setitem(llm_judge._judges, None, lp.judge)
    entry = entry_for("A field of <crop> under <sky>.", (CROP, {**SKY, "n": 2}),
                      {"sky": ["a stormy sky", "a clear sky", "a pale sky"], "crop": ["wheat", "barley", "rye"]}, key="k2")
    cfg = FluentSettings()
    seen = 0
    for seed in range(40):
        r, rec = realize_and_fix(entry, seed=seed, cfg=cfg, profile_id=PROFILE)
        assert "stormy" not in r.prompt and "wheat" not in r.prompt and not rec["unresolved"]
        first = rec["rounds"][0]
        if len([p for p in first["scores"].values() if p and p > 0.5]) == 2:
            seen += 1
            assert rec["rerolls"] == 1 and len(first["rerolled"]["with"]) == 1
    assert seen


def test_a_call_that_takes_too_long_is_given_up_not_left_running(monkeypatch, loop):
    lp = loop(lambda k: "no")
    state = {"canceled": False}

    async def slow(judge, head, chunk):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            state["canceled"] = True
            raise
    monkeypatch.setattr(llm_judge.LlmJudge, "_call", slow)
    monkeypatch.setattr(llm_judge, "TIMEOUT", 0.2)
    with pytest.raises(Exception):
        lp.judge.p_wrong(items("hazel"))
    for _ in range(50):
        if state["canceled"]:
            break
        threading.Event().wait(0.02)
    assert state["canceled"]


class TestReady:
    def cfg(self, **kw):
        return SimpleNamespace(**{"model": "m", "url": "http://a/v1", "provider_kind": "openai", **kw})

    def run(self, monkeypatch, answers):
        import llm_resolver
        seen = []

        async def effective(role, project_id=None):
            seen.append((role, project_id))
            got = answers[project_id]
            if isinstance(got, Exception):
                raise got
            return got
        monkeypatch.setattr(llm_resolver, "get_effective_llm_config", effective)
        return seen

    def test_each_project_has_the_judge_of_its_own_tool_view_model(self, monkeypatch):
        llm_judge.reset()
        answers = {None: self.cfg(), 7: self.cfg(model="other")}
        seen = self.run(monkeypatch, answers)

        async def go():
            return await llm_judge.ready(), await llm_judge.ready(7)
        a, b = asyncio.run(go())
        assert seen == [("tool_assistant", None), ("tool_assistant", 7)]
        assert a is not b and a.version != b.version and llm_judge.current(7) is b and llm_judge.current() is a

    def test_another_endpoint_with_the_same_model_name_is_another_judge(self, monkeypatch):
        llm_judge.reset()
        answers = {None: self.cfg()}
        self.run(monkeypatch, answers)

        async def go():
            first = await llm_judge.ready()
            again = await llm_judge.ready()
            answers[None] = self.cfg(url="http://b/v1")
            return first, again, await llm_judge.ready()
        first, again, moved = asyncio.run(go())
        assert again is first and moved is not first and moved.version != first.version

    def test_a_model_that_can_no_longer_be_resolved_leaves_no_judge(self, monkeypatch):
        llm_judge.reset()
        answers = {None: self.cfg()}
        self.run(monkeypatch, answers)

        async def go():
            first = await llm_judge.ready()
            answers[None] = RuntimeError("no provider")
            return first, await llm_judge.ready()
        first, after = asyncio.run(go())
        assert first is not None and after is None and llm_judge.current() is None
