"""The judge: the Tool View model answers no / rare / yes for each choice of a finished draw."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from prompt_programs import llm_judge
from prompt_programs.fix import Item, fix_mode, judge_identity, realize_and_fix
from prompt_programs.judge import FluentSettings
from prompt_programs.people import expand_people


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


def test_default_means_the_tool_view_model_and_without_it_a_draw_ships_unjudged(tmp_path):
    llm_judge.reset()
    cfg = FluentSettings(generate_options=False)
    assert fix_mode(cfg.fix_model) == "default" and judge_identity(cfg) == "llm"
    src = ('sky = pick("sky", about="the sky", seed=["a clear sky", "a stormy sky"], label="Sky", phase=1, added=True)\n'
           'emit("A field under", sky, ".")\n')
    from prompt_programs import prepare as prep
    info = prep.validate(src, "a field", [], set(), "", True)["info"]
    entry = {"key": "k", "program": src, "choices": info["choices"], "prompt": "a field", "mode": "prose"}
    r, rec = realize_and_fix(entry, seed=3, cfg=cfg)
    assert "A field under" in r.prompt and rec == {"judge": "llm", "skipped": "unavailable"}


def test_everything_refused_in_a_round_is_rerolled_together(monkeypatch, loop, tmp_path):
    lp = loop(lambda k: "no" if k[4] in ("a stormy sky", "wheat") else "yes")
    monkeypatch.setitem(llm_judge._judges, None, lp.judge)
    src = ('sky = pick("sky", about="the sky", seed=["a stormy sky", "a clear sky", "a pale sky"], label="Sky", phase=1, added=True)\n'
           'crop = pick("crop", about="what grows", seed=["wheat", "barley", "rye"], label="Crop", phase=1, added=True)\n'
           'emit("A field of", crop, "under", sky, ".")\n')
    from prompt_programs import prepare as prep
    info = prep.validate(src, "a field", [], set(), "", True)["info"]
    entry = {"key": "k2", "program": src, "choices": info["choices"], "prompt": "a field", "mode": "prose"}
    cfg = FluentSettings(generate_options=False)
    seen = 0
    for seed in range(40):
        r, rec = realize_and_fix(entry, seed=seed, cfg=cfg)
        assert "stormy" not in r.prompt and "wheat" not in r.prompt and not rec["unresolved"]
        first = rec["rounds"][0]
        if len([p for p in first["scores"].values() if p and p > 0.5]) == 2:
            seen += 1
            assert rec["rerolls"] == 1 and len(first["rerolled"]["with"]) == 1
    assert seen


def test_a_call_that_takes_too_long_is_given_up_not_left_running(monkeypatch, loop):
    lp = loop(lambda k: "no")
    state = {"cancelled": False}

    async def slow(judge, head, chunk):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
    monkeypatch.setattr(llm_judge.LlmJudge, "_call", slow)
    monkeypatch.setattr(llm_judge, "TIMEOUT", 0.2)
    with pytest.raises(Exception):
        lp.judge.p_wrong(items("hazel"))
    for _ in range(50):
        if state["cancelled"]:
            break
        threading.Event().wait(0.02)
    assert state["cancelled"]


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


class TestShow:
    def details(self, call):
        src = expand_people(f'w = {call}\nemit("A photo of", w, ".")\n')
        return {line.split(" = ")[0].split("_", 1)[1] for line in src.splitlines() if " = pick(" in line}

    def test_only_what_the_picture_shows_is_drawn(self):
        assert self.details('person("w", noun="man", show=["age", "build", "hair"])') == {"age", "build", "hair"}
        assert "eyes" not in self.details('person("w", noun="man", show=["age", "descent", "face"])')

    def test_what_the_user_stated_is_kept_whatever_is_shown(self):
        assert self.details('person("w", noun="woman", show=["age"], said={"eyes": "emerald"})') == {"age", "eyes"}

    def test_facial_hair_is_a_mans(self):
        assert "facial_hair" not in self.details('person("w", noun="woman", show=["facial_hair", "age"])')
        assert "facial_hair" in self.details('person("w", noun="man", presentation="masculine", show=["facial_hair", "age"])')

    def test_without_show_the_short_set_is_drawn_and_full_gives_everything(self):
        assert self.details('person("w", noun="woman")') == {"age", "descent", "hair", "hair_color", "face"}
        assert {"eyes", "skin", "build"} <= self.details('person("w", noun="woman", detail="full")')

    def test_the_writers_words_narrow_a_detail_and_draw_it(self):
        src = expand_people('s = person("son", noun="son", presentation="masculine", show=["hair"], where={"age": "a young boy"})\n'
                            'emit("A father and", s, ".")\n')
        age = next(line for line in src.splitlines() if line.startswith("s_age = pick("))
        assert "where='a young boy'" in age and "s_hair = pick(" in src

    def test_an_empty_show_draws_nothing_and_names_them(self):
        src = expand_people('w = person("w", noun="woman", show=[])\nemit("A photo of", w, ", from behind.")\n')
        assert "pick(" not in src and "woman" in src


class TestSceneAge:
    """An age the writer gave for the scene holds beside what the prompt says of that person."""

    def choice(self, **kw):
        from prompt_programs.narrow import AGE_LIST
        return {"id": "son.age", "cls": AGE_LIST, **kw}

    def test_both_narrow_the_age(self):
        from prompt_programs.narrow import phrase_of
        assert phrase_of(self.choice(where="a young boy"), {"son.age": "son"}) == "son, a young boy"
        assert phrase_of(self.choice(where="a young boy")) == "a young boy"
        assert phrase_of(self.choice(), {"son.age": "son"}) == "son"

    def test_words_that_already_say_it_are_not_repeated(self):
        from prompt_programs.narrow import phrase_of
        assert phrase_of(self.choice(where="in her thirties"), {"son.age": "a woman in her thirties"}) == "a woman in her thirties"
        assert phrase_of(self.choice(where="son, a young boy"), {"son.age": "son"}) == "son, a young boy"

    def test_another_lists_words_are_still_the_prompts(self):
        from prompt_programs.narrow import phrase_of
        assert phrase_of({"id": "w.hair", "cls": "person.hair_color", "where": "dark"}, {"w.hair": "red-haired"}) == "red-haired"


class TestStaleTicks:
    """Ticks left from an earlier program's options for the same choice never stop a draw."""
    SRC = ('room = pick("setting", about="the room", seed=["a messy bedroom", "a dim bathroom", "a sunny balcony"], '
           'label="Setting", phase=1, added=True)\nemit("A photo in", room, ".")\n')

    def test_ticks_the_pool_no_longer_holds_are_ignored(self):
        from prompt_programs.draws import draw
        stale = {"setting": ["a grand throne room", "a dark throne room"]}
        got = {draw(self.SRC, seed, stale).prompt for seed in range(20)}
        assert len(got) > 1 and all("throne" not in p for p in got)

    def test_ticks_the_pool_holds_still_narrow_it(self):
        from prompt_programs.draws import draw
        some = {"setting": ["a dim bathroom", "a sunny balcony", "a grand throne room"]}
        got = {draw(self.SRC, seed, some).prompt for seed in range(20)}
        assert got == {"A photo in a dim bathroom.", "A photo in a sunny balcony."}

    def test_ticks_for_another_value_of_what_the_choice_follows_are_not_stale(self):
        from prompt_programs.draws import DrawAborted, draw
        src = ('era = pick("era", ["1920s", "1970s"], label="Era", source="list", phase=1, line=1)\n'
               'hair = pick("hair", {"1920s": ["finger waves", "a bob"], "1970s": ["feathered hair", "an afro"]}, by=era, '
               'label="Hair", phase=2, line=1)\nemit("A", era, "woman with", hair, ".")\n')
        ticks = {"hair": ["finger waves", "a bob"]}
        seen = set()
        for seed in range(30):
            try:
                seen.add(draw(src, seed, ticks).prompt)
            except DrawAborted as e:
                assert e.choice_id == "hair"
                seen.add("refused")
        assert "refused" in seen and not any("feathered" in p or "afro" in p for p in seen)

    def test_ticks_wait_for_computed_options_to_settle(self):
        """Options computed from an earlier pick are placeholders until that pick is drawn: ticks
        for the value it draws later hold, whatever an earlier run of the program saw."""
        from prompt_programs.draws import draw
        src = ('styles = {"1920s": ["finger waves", "a bob", "long straight hair"], "1970s": ["feathered hair", "an afro", "long straight hair"]}\n'
               'sky = pick("sky", ["a clear sky", "a gray sky"], label="Sky", source="list", phase=1, line=1)\n'
               'era = pick("era", ["1920s", "1970s"], label="Era", source="list", phase=2, line=1)\n'
               'hair = pick("hair", styles[era], by=era, label="Hair", phase=3, line=1)\n'
               'emit("Under", sky, ", a", era, "woman with", hair, ".")\n')
        ticks = {"hair": ["feathered hair", "an afro"], "era": ["1970s"]}
        got = {draw(src, seed, ticks).prompt for seed in range(30)}
        assert got and all("1970s" in p and ("feathered hair" in p or "an afro" in p) for p in got)

    def test_ticked_values_that_are_all_excluded_are_not_stale(self):
        from prompt_programs.draws import DrawAborted, draw
        src = ('a = pick("a", ["red", "green"], label="A", source="list", phase=1, line=1)\n'
               'b = pick("b", ["red", "green", "white"], label="B", source="list", phase=2, line=1, exclude=[a])\n'
               'emit(a, "and", b)\n')
        for seed in range(20):
            try:
                assert "white" not in draw(src, seed, {"b": ["red", "green"], "a": ["red", "green"]}).prompt
            except DrawAborted:
                pass

    def test_stale_ticks_leave_the_users_stated_value_held(self):
        from prompt_programs.draws import draw
        src = ('car = pick("car", said="yellow ferrari", about="the car", seed=["red lamborghini", "blue beetle"], label="Car", phase=1)\n'
               'emit("A photo of a", car, ".")\n')
        for seed in range(12):
            assert draw(src, seed, {"car": ["a gray van", "a white truck"]}).prompt == "A photo of a yellow ferrari."

    def test_one_pinned_value_the_pool_lacks_is_still_refused_at_its_choice(self):
        from prompt_programs.draws import DrawAborted, draw
        with pytest.raises(DrawAborted) as e:
            draw(self.SRC, 3, {"setting": ["a grand throne room"]})
        assert e.value.reason == "pin" and e.value.choice_id == "setting"
