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

    def test_someone_nothing_is_drawn_of_and_never_placed_adds_no_words(self):
        src = expand_people('w = person("w", noun="woman", show=[])\nemit("A photo of Yui Hatano in a cafe.")\n')
        assert "pick(" not in src and src.count("emit(") == 1 and "woman" not in src

    def test_a_persons_noun_narrows_their_age_when_it_is_their_own_word(self):
        boy = expand_people('b = person("boy", noun="boy", show=["age"])\nemit(b)\n')
        assert "where='boy'" in boy
        listed = expand_people('job = pick("job", ["chef", "nurse"], source="list", label="Job", phase=1, line=1)\n'
                               'p = person("p", noun=job, show=["age"])\nemit(p)\n')
        assert "where=" not in next(line for line in listed.splitlines() if "p.age" in line)
        said = expand_people('b = person("boy", noun="boy", show=["age"], said={"age": "10 year old"})\nemit(b)\n')
        assert "where=" not in said

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

    def test_one_pinned_value_is_kept_when_the_choices_options_changed(self):
        """The user pinned it: it is still what they want there, as an option of their own."""
        from prompt_programs.draws import draw
        for seed in range(8):
            assert draw(self.SRC, seed, {"setting": ["a grand throne room"]}).prompt == "A photo in a grand throne room."
        later = ('sky = pick("sky", ["a clear sky", "a gray sky"], label="Sky", source="list", phase=1, line=1)\n'
                 'fit = pick("outfit", about="what she wears", seed=["a linen dress", "a wool coat"], label="Outfit", phase=2, added=True)\n'
                 'emit("Under", sky, ", in", fit, ".")\n')
        got = {draw(later, seed, {"outfit": ["a crochet camisole and wide-leg linen pants"]}).prompt for seed in range(12)}
        assert got and all(p.endswith("in a crochet camisole and wide-leg linen pants.") for p in got)

    def test_a_pinned_value_the_program_cannot_take_is_dropped(self):
        """A pin that isn't an item of the user's own list: the list is their words, exactly, so
        the draw is the unpinned one rather than a failure."""
        from prompt_programs.draws import draw
        src = ('weather = pick("weather", ["rainy", "bright"], label="Weather", source="list", phase=1, line=1)\n'
               'coat = {"rainy": "a trench coat", "bright": "a linen shirt"}[weather]\n'
               'emit("A woman wearing", coat)\n')
        for seed in range(8):
            assert draw(src, seed, {"weather": ["snowy"]}).prompt == draw(src, seed).prompt

    def test_a_stale_pin_beside_a_valid_one_is_found_whichever_is_reported(self):
        from prompt_programs.draws import draw
        src = ('era = pick("era", ["1920s", "1970s"], label="Era", source="list", phase=1, line=1)\n'
               'hair = pick("hair", {"1920s": ["a bob", "finger waves"], "1970s": ["a bob", "an afro"]}, by=era, label="Hair", phase=2, line=1)\n'
               'fit = pick("outfit", {"1920s": ["a beaded dress"], "1970s": ["a wide-collared suit"]}, by=era, label="Outfit", phase=2, line=1)\n'
               'emit("A", era, "woman with", hair, "in", fit, ".")\n')
        for seed in range(8):
            p = draw(src, seed, {"hair": ["a bob"], "outfit": ["an old outfit"]}).prompt
            assert "with a bob" in p

    def test_one_pinned_value_the_choice_offers_but_not_here_is_still_refused(self):
        from prompt_programs.draws import DrawAborted, draw
        src = ('era = pick("era", ["1920s", "1970s"], label="Era", source="list", phase=1, line=1)\n'
               'hair = pick("hair", {"1920s": ["finger waves", "a bob"], "1970s": ["feathered hair", "an afro"]}, by=era, '
               'label="Hair", phase=2, line=1)\nemit("A", era, "woman with", hair, ".")\n')
        seen = set()
        for seed in range(30):
            try:
                p = draw(src, seed, {"hair": ["a bob"], "era": ["1970s"]}).prompt
                seen.add(p)
            except DrawAborted as e:
                assert e.reason == "pin" and e.choice_id == "hair"
                seen.add("refused")
        assert seen == {"refused"}

    ERAS = ('era = pick("era", ["1920s", "1970s"], label="Era", source="list", phase=1, line=1)\n'
            'hair = pick("hair", {"1920s": ["finger waves", "a bob"], "1970s": ["feathered hair", "an afro"]}, by=era, '
            'label="Hair", phase=2, line=1)\nemit("A", era, "woman with", hair, ".")\n')

    def test_a_kept_pin_on_a_choice_that_follows_another_is_drawn(self):
        from prompt_programs.draws import draw
        got = {draw(self.ERAS, seed, {"hair": ["a mohawk"]}).prompt for seed in range(20)}
        assert got == {"A 1920s woman with a mohawk.", "A 1970s woman with a mohawk."}

    def test_a_stale_pin_above_a_valid_one_leaves_the_valid_one_holding(self):
        from prompt_programs.draws import draw
        for seed in range(12):
            assert draw(self.ERAS, seed, {"era": ["1800s"], "hair": ["a bob"]}).prompt == "A 1920s woman with a bob."

    def test_a_draw_made_with_stale_ticks_replays_from_its_kept_values(self):
        from prompt_programs.draws import draw
        stale = {"setting": ["a grand throne room", "a dark throne room"]}
        for seed in range(8):
            first = draw(self.SRC, seed, stale)
            kept = {d.id: d.value for d in first.draws}
            assert draw(self.SRC, seed + 100, stale, fixed=kept).prompt == first.prompt
            assert first.prompt == draw(self.SRC, seed).prompt   # exactly the unticked draw



class TestKeptPinsInTheApp:
    """The same holds through the app's own options service, and for stale pins found one after another."""

    def service(self, tmp_path, src, prompt="a woman"):
        from prompt_programs import prepare as prep
        from prompt_programs.fluent import runtime_for
        from prompt_programs.options import OptionStore
        info = prep.validate(src, prompt, [], set(), "", True)["info"]
        entry = {"key": "kp", "program": src, "choices": info["choices"], "prompt": prompt, "mode": "prose"}
        return entry, lambda: runtime_for(entry, store=OptionStore(tmp_path), cfg=FluentSettings(generate_options=False))

    def test_a_pinned_value_is_kept_for_a_pick_with_options_of_its_own(self, tmp_path):
        from prompt_programs import prepare as prep
        src = ('fit = pick("outfit", ["a wool coat", "a linen dress"], label="Outfit", phase=1, line=1)\n'
               'emit("A woman in", fit, ".")\n')
        entry, runtime = self.service(tmp_path, src)
        for seed in range(6):
            r = prep.realize(entry, seed=seed, pins={"outfit": ["a pinned camisole"]}, runtime=runtime())
            assert r.prompt == "A woman in a pinned camisole."
        assert "camisole" not in prep.realize(entry, seed=1, runtime=runtime()).prompt   # nothing is left behind

    def test_stale_pins_found_one_after_another_are_each_handled(self):
        from prompt_programs.draws import draw
        src = ('weather = pick("weather", ["rainy", "bright"], label="Weather", source="list", phase=1, line=1)\n'
               'coat = {"rainy": "a trench coat", "bright": "a linen shirt"}[weather]\n'
               'fit = pick("outfit", about="what else she wears", seed=["a wool scarf", "a straw hat"], label="Outfit", phase=2, added=True)\n'
               'emit("A woman wearing", coat, "and", fit, ".")\n')
        for seed in range(8):
            p = draw(src, seed, {"weather": ["snowy"], "outfit": ["a pinned camisole"]}).prompt
            assert p.endswith("and a pinned camisole.") and ("trench coat" in p or "linen shirt" in p)


class TestPinnedNote:
    """The writer is told what the user has pinned, so a change keeps those choices and values."""

    def test_only_single_pinned_values_are_told_and_templates_read_plainly(self):
        from prompt_programs.prepare import pinned_note
        note = pinned_note({"woman.outfit": ["a {main} crochet camisole and {neutral} wide-leg linen pants"],
                            "setting": ["a throne room", "a dark throne room"], "light": []})
        assert 'woman.outfit: "a crochet camisole and wide-leg linen pants"' in note
        assert "setting" not in note and "light" not in note and "{" not in note
        assert pinned_note({}) == "" and pinned_note(None) == "" and pinned_note({"setting": ["a", "b"]}) == ""

    def test_the_note_reaches_the_writers_message_only_inside_the_prepare_that_set_it(self):
        from prompt_programs import prepare as prep
        told = prep._PINNED.set(prep.pinned_note({"woman.outfit": ["a red coat"]}))
        try:
            user = prep.writer_messages("a woman", "", [], None, "prose", {}, [], {}, True)[1]["content"]
        finally:
            prep._PINNED.reset(told)
        assert 'woman.outfit: "a red coat"' in user and "Keep each of them as a pick with that same id" in user
        assert "pinned" not in prep.writer_messages("a woman", "", [], None, "prose", {}, [], {}, True)[1]["content"]
class TestKin:
    SRC = ('a = person("sister[1]", noun="sister", presentation="feminine", kin="family", show=["age", "descent", "hair"])\n'
           'b = person("sister[2]", noun="sister", presentation="feminine", kin="family", show=["age", "descent", "hair"])\n'
           'emit("Two sisters:", a, "and", b, ".")\n')

    def test_blood_relatives_share_one_descent_and_keep_their_own_other_details(self):
        from prompt_programs.draws import draw
        src = expand_people(self.SRC)
        assert src.count("pick('family.descent'") == 1 and "shared=True" in src
        assert "sister[1].descent" not in src and "sister[2].descent" not in src
        assert "sister[1].age" in src and "sister[2].hair" in src
        for seed in range(12):
            r = draw(src, seed)
            descent = next(d.value for d in r.draws if d.id == "family.descent")
            assert r.prompt.count(str(descent)) == 2

    def test_the_shared_descent_passes_validation_with_several_subjects(self):
        from prompt_programs import prepare as prep
        src = expand_people(self.SRC)
        got = prep.validate(src, "two sisters", [], set(), "", True)
        assert not [p for p in got["problems"] if "descent" in p]

    def test_a_stated_descent_stays_that_persons_and_no_kin_means_no_sharing(self):
        src = expand_people('a = person("mother", noun="mother", kin="family", said={"descent": "Irish"}, show=["age"])\n'
                            'b = person("son", noun="son", kin="family", show=["age", "descent"])\nemit(a, "and", b)\n')
        assert "mother.descent" in src and "said='Irish'" in src and src.count("family.descent") == 1
        plain = expand_people('a = person("a", noun="man", show=["descent"])\nemit(a)\n')
        assert "kin_" not in plain and "a.descent" in plain

    def test_a_family_nobody_shows_the_descent_of_makes_no_pick(self):
        src = expand_people('a = person("a", noun="sister", kin="family", show=["age"])\nemit(a)\n')
        assert "family.descent" not in src

    def test_the_shared_descent_is_judged_and_shown_though_it_reads_twice(self, tmp_path):
        from prompt_programs import prepare as prep
        from prompt_programs.fix import _questions, prompt_view
        from prompt_programs.fluent import runtime_for
        from prompt_programs.options import OptionStore
        src = expand_people(self.SRC)
        info = prep.validate(src, "two sisters", [], set(), "", True)["info"]
        entry = {"key": "kin", "program": src, "choices": info["choices"], "prompt": "two sisters", "mode": "prose"}
        r = prep.realize(entry, seed=3, runtime=runtime_for(entry, store=OptionStore(tmp_path), cfg=FluentSettings(generate_options=False)))
        items, ids, out = _questions(r, "two sisters")
        assert "family.descent" in ids and out.get("family.descent", 0) is not None
        assert any(span[2] == "family.descent" for span in prompt_view(r)["spans"])

    def test_a_descent_pick_the_program_wrote_is_the_familys(self):
        from prompt_programs.draws import draw
        src = expand_people('d = pick("woman.descent", cls="person.ethnicity", about="her descent", seed=["Irish"], label="Ethnicity", phase=1, added=True)\n'
                            'w = person("woman", noun="woman", kin="family", show=["age"])\n'
                            'g = person("girl", noun="girl", kin="family", show=["age", "descent"])\n'
                            'emit("A", d, w, "and", g, ".")\n')
        assert "family.descent" not in src and "girl.descent" not in src
        for seed in range(8):
            r = draw(src, seed)
            assert r.prompt.count(str(next(x.value for x in r.draws if x.id == "woman.descent"))) == 2

    def test_an_adopted_descent_is_marked_shared_and_one_out_of_reach_is_not_adopted(self):
        top = expand_people('d = pick("woman.descent", cls="person.ethnicity", about="her descent", seed=["Irish"], label="Ethnicity", phase=1, added=True)\n'
                            'w = person("woman", noun="woman", kin="family", show=["age"])\n'
                            'g = person("girl", noun="girl", kin="family", show=["age", "descent"])\nemit("A", d, w, "and", g, ".")\n')
        assert "shared=True" in next(line for line in top.splitlines() if "woman.descent" in line)
        from prompt_programs.draws import draw
        late = expand_people('g = person("girl", noun="girl", kin="family", show=["age", "descent"])\n'
                             'w = person("woman", noun="woman", kin="family", show=["age"])\n'
                             'd = pick("woman.descent", cls="person.ethnicity", about="her descent", seed=["Irish"], label="Ethnicity", phase=1, added=True)\n'
                             'emit("A", d, w, "and", g, ".")\n')
        assert draw(late, 1).prompt   # the girl has the family's own pick; nothing reads a name not yet made
        branch = expand_people('s = pick("scene", ["home", "away"], source="list", label="Scene", phase=1, line=1)\n'
                               'if s == "home":\n    d = pick("woman.descent", cls="person.ethnicity", about="her descent", seed=["Irish"], label="Ethnicity", phase=2, added=True)\n'
                               '    emit(d)\n'
                               'g = person("girl", noun="girl", kin="family", show=["age", "descent"])\nw = person("woman", noun="woman", kin="family", show=["age"])\n'
                               'emit(s, w, "and", g, ".")\n')
        for seed in range(6):
            assert draw(branch, seed).prompt

    def test_a_family_first_met_in_a_branch_inside_a_loop_is_not_hoisted(self):
        from prompt_programs.draws import draw
        src = expand_people('n = group("people", 2, label="People", line=1)\nemit("Two people:")\n'
                            'for i in range(n):\n'
                            '    if False:\n'
                            '        s = person(f"people[{i+1}]", noun="sister", kin="family", show=["age", "descent"])\n'
                            '        emit(s, ";")\n'
                            '    else:\n'
                            '        emit("someone;")\n')
        assert "family.descent" not in src
        assert not [d for d in draw(src, 1).draws if "descent" in d.id]

    def test_a_family_in_a_branch_not_taken_draws_nothing(self):
        from prompt_programs import prepare as prep
        from prompt_programs.draws import draw
        src = expand_people('scene = pick("scene", ["an empty room", "two sisters"], label="Scene", source="list", phase=1, line=1)\n'
                            'if scene == "two sisters":\n'
                            '    a = person("sister[1]", noun="sister", kin="family", show=["age", "descent"])\n'
                            '    b = person("sister[2]", noun="sister", kin="family", show=["age", "descent"])\n'
                            '    emit("Two sisters:", a, "and", b, ".")\n'
                            'else:\n'
                            '    emit("An empty room.")\n')
        src, _ = prep.fix_written(src, "{an empty room|two sisters}", [])
        got = prep.validate(src, "{an empty room|two sisters}", [], set(), "", True)
        assert not [p for p in got["problems"] if "descent" in p]
        empty = draw(src, 1, {"scene": ["an empty room"]})
        assert empty.prompt == "An empty room." and not [d for d in empty.draws if d.id == "family.descent"]
        both = draw(src, 1, {"scene": ["two sisters"]})
        assert both.prompt.count(str(next(d.value for d in both.draws if d.id == "family.descent"))) == 2

    def test_a_family_made_in_a_loop_has_one_pick_above_it(self):
        from prompt_programs.draws import draw
        src = expand_people('n = group("sisters", 3, label="Sisters", line=1)\nemit("Three sisters:")\n'
                            'for i in range(n):\n'
                            '    s = person(f"sisters[{i+1}]", noun="sister", kin="family", show=["age", "descent"])\n'
                            '    emit(s, ";")\n')
        assert src.count("pick('family.descent'") == 1 and src.index("family.descent") < src.index("for i in range")
        r = draw(src, 2)
        assert r.prompt.count(str(next(d.value for d in r.draws if d.id == "family.descent"))) == 3


class TestOptionListCheck:
    """A written option list is read once against the prompt: wrong options leave, stretches go last."""

    def job(self):
        from prompt_programs.draws import PickSpec
        from prompt_programs.options import OptionJob, ProgramContext
        spec = PickSpec("hairstyle", "Hairstyle", "dark hair hairstyle", 1, "text", "pick", ["a sleek black bob"], [], "")
        program = ProgramContext.of({"key": "k", "program": 'emit("x")', "prompt": "portrait of a woman with {{dark hair hairstyle}}",
                                     "choices": [], "mode": "prose"})
        return OptionJob(key="k", spec=spec, context={}, program=program, signature="portrait of a woman", round=0)

    def run(self, monkeypatch, reply):
        import asyncio
        from prompt_programs import options, program as prep
        seen = []

        async def ask(messages, project_id, max_tokens=4096):
            seen.append(messages)
            if isinstance(reply, Exception):
                raise reply
            return reply
        monkeypatch.setattr(prep, "ask_model", ask)
        got = asyncio.run(options.check_options(self.job(), ["a black bob", "an ash brown shag", "jet-black braids", "a dark pixie cut"]))
        return got, seen

    def test_a_no_leaves_and_a_rare_goes_last(self, monkeypatch):
        got, seen = self.run(monkeypatch, '{"id": 1, "answer": "yes"}\n{"id": 2, "answer": "no"}\n{"id": 3, "answer": "rare"}\n{"id": 4, "answer": "yes"}')
        assert got == ["a black bob", "a dark pixie cut", "jet-black braids"]
        assert "dark hair hairstyle" in seen[0][1]["content"] and "2. an ash brown shag" in seen[0][1]["content"]

    def test_a_failed_or_thin_answer_keeps_the_list_as_written(self, monkeypatch):
        whole = ["a black bob", "an ash brown shag", "jet-black braids", "a dark pixie cut"]
        assert self.run(monkeypatch, RuntimeError("down"))[0] == whole
        assert self.run(monkeypatch, '{"id": 2, "answer": "no"}')[0] == whole
        assert self.run(monkeypatch, "\n".join('{"id": %d, "answer": "no"}' % i for i in range(1, 5)))[0] == whole
