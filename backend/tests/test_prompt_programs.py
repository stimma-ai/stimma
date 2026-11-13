"""Fluent's shared pieces: masking, saved wildcards, which tools vary their prompts, option
writing on request, LoRA context and trigger words, the acceptance fake's reading, store keys."""

import pytest

from prompt_programs import program as prep
from prompt_programs.fill import ProgramError
from prompt_programs.store import ProgramStore








class TestPrepare:


    def test_masking_round_trips(self):
        masked, exact = prep.mask_exact("a [sign that says OPEN] on {a|b}, [{{x}}] and [neon]")
        assert masked == "a [EXACT_1] on {a|b}, [{{x}}] and [EXACT_2]"
        assert prep.unmask_exact("A EXACT_1 and [EXACT_2].", exact) == "A [sign that says OPEN] and [neon]."

    async def test_exact_text_stays_protected_through_translate(self, monkeypatch):
        # After a run the text is back in brackets, so Translate's verbatim protection
        # hides it from the translation model and the final cleanup unwraps it.
        import prompt_pipeline as pp
        seen = []

        async def fake_translate(text, language, project_id):
            seen.append(text)
            return text.replace("a woman", "una mujer")

        monkeypatch.setattr(pp, "_profile_wildcards_and_segments", lambda profile_id: ([], []))
        monkeypatch.setattr(pp, "_translate_with_verbatim_protection",
                            lambda text, lang, pid: _protected(text, lang, pid, fake_translate))
        out = await pp.run_prompt_pipeline(None, "a woman under a sign that says [OPEN ALL NIGHT]",
                                           {"translate": {"enabled": True, "language": "es"}})
        assert "OPEN ALL NIGHT" not in " ".join(seen) and out == "una mujer under a sign that says OPEN ALL NIGHT"


    def test_named_wildcards_become_lists(self):
        out = prep.expand_named_lists("a {{color}} car, {{style}}", [{"name": "color", "values": ["red", "blue"]}],
                                      [{"name": "style", "content": "film photo"}])
        assert out == "a {red|blue} car, film photo"




class TestProgramSupport:
    @pytest.mark.parametrize("model,task,images,supported", [
        ("Qwen-Image-2.1", "text-to-image", 0, True), ("Qwen-Image-2.1", "image-to-image", 1, False),
        ("FLUX.3 Klein", "image-to-image", 1, False), ("sdxl", "text-to-image", 0, True),
        ("some model", "image-to-image", 1, False), ("some model", "text-to-audio", 0, False),
        ("some model", "text-to-video", 0, True),
    ])
    def test_edits_and_audio_keep_the_per_image_enhancer(self, monkeypatch, model, task, images, supported):
        import routes.generation as gen
        monkeypatch.setattr(gen, "_prompt_pipeline_context", lambda *a: (model, None, task, {}))
        monkeypatch.setattr(gen, "_prompt_input_image_count", lambda *a: images)
        assert gen.prompt_enhance_context({}, "t", task, None)["program_supported"] is supported


class TestSuggestOptions:
    ENTRY = {"key": "k", "prompt": "a woman in <stylish tank top>", "example": "a woman in a silk tank top",
             "slot_words": {"stylish_tank_top": "stylish tank top"},
             "elaborate": False, "mode": "prose",
             "choices": [{"id": "stylish_tank_top", "kind": "pick", "label": "Tank Top",
                          "about": "a stylish tank top", "options": ["a silk tank top", "a linen tank top"]},
                         {"id": "look", "kind": "lora", "label": "Look", "options": ["A"]}]}

    async def test_new_options_skip_existing_and_repeats(self, monkeypatch):
        from prompt_programs import options as opts
        calls = []

        async def fake_ask(messages, project_id, tool):
            calls.append(messages)
            return '```json\n["a silk tank top", "a ribbed cotton tank", "A ribbed cotton tank", "a sheer mesh tank"]\n```', None

        async def text_only(_pid):
            return ("", ""), False

        monkeypatch.setattr(opts, "_ask_options", fake_ask)
        monkeypatch.setattr(opts, "_endpoint", text_only)
        out = await opts.suggest_options(self.ENTRY, "stylish_tank_top", ["a silk tank top", "a linen tank top"], 2, None)
        assert out == ["a ribbed cotton tank", "a sheer mesh tank"] and len(calls) == 1
        system, user = calls[0][0]["content"], calls[0][1]["content"]
        # the same writer as background generation: its rules, the user's own words as a rule
        assert "Write 2 options" in system and "a few words" in system and "most typical" in system
        assert "- a linen tank top" in user and '"stylish tank top"' in user

    async def test_retries_once_when_short(self, monkeypatch):
        from prompt_programs import options as opts
        replies = ['["a ribbed cotton tank"]', '["a sheer mesh tank", "a crochet halter"]']

        async def fake_ask(messages, project_id, tool):
            return replies.pop(0), None

        async def text_only(_pid):
            return ("", ""), False

        monkeypatch.setattr(opts, "_ask_options", fake_ask)
        monkeypatch.setattr(opts, "_endpoint", text_only)
        out = await opts.suggest_options(self.ENTRY, "stylish_tank_top", [], 3, None)
        assert out == ["a ribbed cotton tank", "a sheer mesh tank", "a crochet halter"]

    async def test_only_picks(self):
        from prompt_programs import options as opts
        with pytest.raises(ProgramError):
            await opts.suggest_options(self.ENTRY, "look", [], 3, None)




async def _protected(text, lang, pid, translate):
    """The real masking from prompt_pipeline around a fake translation call."""
    from prompt_pipeline import extract_verbatim, restore_verbatim
    masked, segs = extract_verbatim(text)
    return restore_verbatim(await translate(masked, lang, pid), segs)


class TestLoraChoices:

    def test_notes_and_triggers_shape_what_the_model_is_told(self):
        from routes.generation import _shape_lora_context
        ctx = [{"name": "Wolf cut", "trigger_words": ["wolfcut"], "notes": "works best at 0.8"}]
        assert _shape_lora_context(ctx, True, True) == ctx
        assert _shape_lora_context(ctx, False, True)[0]["trigger_words"] == []
        assert _shape_lora_context(ctx, True, False)[0]["notes"] == ""
        assert _shape_lora_context([], False, False) == []


class TestTriggerWordsAreOptIn:
    """Builds without Fluent (and the agent) send no loraTriggers: nothing is added."""

    async def _run(self, monkeypatch, prompt_options):
        import routes.generation as gen

        async def fake_pipeline(db, prompt, options, **kw):
            return prompt

        async def fake_context(tool_id, parameters, profile_id=None):
            return [{"name": "Wolf cut", "trigger_words": ["wolfcut"], "notes": ""}]

        monkeypatch.setattr("prompt_pipeline.run_prompt_pipeline", fake_pipeline)
        monkeypatch.setattr("lora_notes.lora_context_for", fake_context)
        monkeypatch.setattr(gen, "prompt_enhance_context", lambda *a, **k: {
            "model": "m", "model_vendor": None, "schema_props": {}, "mode": "prose", "program_supported": True, "enhance": {}})
        monkeypatch.setattr(gen, "get_database_registry", lambda: type("R", (), {"get_database": lambda self, p: None})())
        monkeypatch.setattr(gen, "get_current_profile", lambda: "p")
        out = await gen._apply_generation_prompt_pipeline(
            {"prompt": "a woman", "loras": [{"lora": "wc.safetensors", "weight": 1}]},
            tool_id="t", task_type=None, prompt_options=prompt_options, prompt_preload=None)
        return out["prompt"]

    async def test_absent_adds_nothing(self, monkeypatch):
        assert await self._run(monkeypatch, {"autoImprove": {"enabled": False}}) == "a woman"

    async def test_fluent_builds_add_missing_triggers(self, monkeypatch):
        assert await self._run(monkeypatch, {"loraTriggers": True}) == "wolfcut, a woman"
        assert await self._run(monkeypatch, {"loraTriggers": False}) == "a woman"

    async def test_raw_never(self, monkeypatch):
        assert await self._run(monkeypatch, {"raw": True, "loraTriggers": True}) == "a woman"


class TestEditorAndRunAgreeOnTheKey:
    """The editor prepares with a sketch of the inputs (frontend contextParams); a run
    prepares with the real parameters. The parts of the key that depend on inputs must
    come out the same, or a run prepares a second program."""

    def test_video_start_frame(self):
        from routes.generation import _prompt_media_id
        editor = {"input_media_ids": [42]}
        run = {"image": "/library/frame.png", "image_media_id": 42}
        assert _prompt_media_id(editor, "image-to-video") == _prompt_media_id(run, "image-to-video") == 42

    def test_driving_audio(self):
        from routes.generation import _prompt_audio_conditioned
        schema = {"input_audios": {"x-control": "audio_picker"}}
        assert _prompt_audio_conditioned({"input_audios": ["ref"]}, schema)
        assert _prompt_audio_conditioned({"input_audios": ["/library/voice.wav"]}, schema)
        ref = {"input_audios": {"x-control": "audio_picker", "x-audio-role": "reference"}}
        assert not _prompt_audio_conditioned({"input_audios": ["ref"]}, ref)  # the editor doesn't send it either


class TestAcceptanceFakeReadsSlots:
    """The acceptance sandbox's fake chat model must answer the slot reader with a reading
    it can use, or every Fluent run of a prompt with slots on a fresh app is blocked."""

    async def test_the_fake_reply_is_a_usable_reading(self, tmp_path):
        from llm import _acceptance_program
        from prompt_programs import reader
        from prompt_programs.narrow import NarrowCache
        from prompt_programs.slots import compose, parse

        async def ask(messages, project_id, max_tokens):
            return _acceptance_program(messages)

        parsed = parse("# at dusk\na <young man> on a {red|blue} bench by the <lake>")
        got = await reader.read(parsed, ask=ask, project_id=None, model="m", cache=NarrowCache(tmp_path))
        entry = compose(parsed, {r["n"]: r for r in got["slots"]}, {r["n"]: r["label"] for r in got["lists"]})
        assert [s["kind"] for s in entry["slots"]] == ["free", "free"] and not any(s.get("degraded") for s in entry["slots"])
        assert {c["id"] for c in entry["choices"]} == {"young_man", "lake", "list1"}

    def test_other_requests_keep_the_dummy_reply(self):
        from llm import _acceptance_program
        assert _acceptance_program([{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "hi"}]) is None


# --------------------------------------------------------------------------- the sandbox
# Every hostile program runs on both paths: plain run(), and the phased draw() a program
# with pick specs takes (its own analyzer, then the same sandbox).

def _plain(body: str) -> str:
    return f'era = pick("era", ["1920s", "1970s"], source="list")\n{body}\nemit("A portrait,", era)\n'


def _phased(body: str) -> str:
    return f'era = pick("era", ["1920s", "1970s"], source="list", phase=1)\n{body}\nemit("A portrait,", era)\n'


def _both(body: str):
    from prompt_programs.draws import draw
    return [lambda: run(_plain(body), 3), lambda: draw(_phased(body), 3)]


SECRET = "sandbox-test-secret-value"

ESCAPES = [
    # the review's exploits: format-string field names traverse attributes and items
    'x = "{0.__func__.__globals__[sys].modules[os].environ[PP_SANDBOX_SECRET]}".format(pick)',
    'x = "{0.__self__.__loader__.find_spec.__func__.__globals__[sys].modules[os].environ[PP_SANDBOX_SECRET]}".format(len)',
    'x = str.format("{0.__self__}", len)',
    'x = "{0.__self__}".format_map({})',
    'f = "{}".format\nx = f(len)',
    'x = format(len, "")',
    'x = getattr(len, "__self__")',
    'x = f"{len.__self__}"',
    'x = f"{era.__class__}"',
    'x = f"{era:{len.__self__}}"',
    'x = "%(__class__)s" % era',
    'x = vars(len)',
]




DAG = 'L = ["x" * 1000]\nfor i in range(40):\n    L = [L, L]\n'
HOGS = [
    'x = "a" * 200000000',
    'x = [0] * 1000000000',
    'x = 3 * "ab" * 100000000',
    's = "ab"\nfor i in range(6):\n    s = s.replace("", s)\nx = s',
    'x = f"{1:>200000000}"',
    'x = f"{1.5:.200000000f}"',
    'w = 200000000\nx = f"{1:>{w}}"',
    'x = "%0200000000d" % 1',
    'x = "%*d" % (200000000, 1)',
    'x = max(range(300000000))',
    'x = sorted(range(300000000))',
    'x = len(list(range(100000000)))',
    'n = 7\nfor i in range(40):\n    n = n * n\nx = n',
    's = "ab"\nfor i in range(60):\n    s = s + s\nx = s',
    's = "ab"\nfor i in range(60):\n    s += s\nx = s',
    'd = {"k": "ab"}\nfor i in range(60):\n    d["k"] += d["k"]\nx = d["k"]',
    'L = [1]\nfor i in range(60):\n    L.extend(L)\nx = len(L)',
    's = "ab"\nfor i in range(60):\n    s = "".join([s, s])\nx = s',
    's = "ab"\nfor i in range(60):\n    s = str.join("", [s, s])\nx = s',
    'acc = []\nfor i in range(20000):\n    acc.append("y" * 99999)\nx = len(acc)',
    DAG + 'x = str(L)',
    DAG + 'x = f"{L}"',
    DAG + 'x = f"{L!r}"',
    DAG + 'x = "%s" % (L,)',
    DAG + 'x = "ok"\nemit(L)',
    DAG + 'x = "ok"\nemit("a", label=L)',
    # a guarded method stored or passed keeps no guard, so it can't be (S1)
    's = "x" * 1000\nf = s.replace\nx = f("", s)',
    's = "x" * 1000\nf = str.replace\nx = f(s, "", s)',
    's = "x" * 1000\nfs = [s.replace]\nx = fs[0]("", s)',
    's = "x" * 1000\nj = s.join\nx = j([s] * 1000)',
    'L = [1] * 100000\ne = L.extend\ne(L)\nx = len(L)',
    # str() however it's called (S2)
    'a = ["x" * 1000] * 1000\nx = str(object=a)',
    'a = ["x" * 1000] * 1000\nx = str(**{"object": a})',
    # copies count toward what a run makes
    'a = ["x"] * 100000\nacc = []\nfor i in range(200):\n    acc.append(a[:])\nx = "ok"',
    'a = ["x"] * 100000\nacc = []\nfor i in range(200):\n    acc.append(list(a))\nx = "ok"',
]

# Containers holding the same container over and over: comparing, hashing or sorting them
# walks every repeat inside one C call, past the CPU budget's reach (S3).
_TWINS = 'a = [0]\nb = [0]\nfor i in range({n}):\n    a = [a, a]\n    b = [b, b]\n'
_TUPLES = 't = (0,)\nu = (0,)\nfor i in range(60):\n    t = (t, t)\n    u = (u, u)\n'
WALKS = [
    _TWINS.format(n=27) + 'x = str(a == b)',
    _TWINS.format(n=40) + 'x = str(a == b)',
    _TWINS.format(n=60) + 'x = str(a == b)',
    _TWINS.format(n=60) + 'x = str(a != b)',
    _TWINS.format(n=60) + 'x = str(a < b)',
    _TWINS.format(n=60) + 'x = str(a in [b])',
    _TWINS.format(n=60) + 'x = str([b].index(a))',
    _TWINS.format(n=60) + 'x = str([b].count(a))',
    _TWINS.format(n=60) + 'x = str(len(sorted([a, b])))',
    _TWINS.format(n=60) + 'x = str(len(max(a, b)))',
    _TWINS.format(n=60) + 'x = str(len(min([a, b])))',
    _TUPLES + 'x = str(t == u)',
    _TUPLES + 'd = {}\nd[t] = 1\nx = "ok"',
    _TUPLES + 'x = str({}.get(t))',
    _TUPLES + 'x = str(len({t}))',
    _TUPLES + 'x = str(len({t: 1}))',
    _TUPLES + 'x = str(len({k: 1 for k in [t]}))',
    _TUPLES + 'x = str(len(set([t, u])))',
    _TUPLES + 'x = str(len(dict([(t, 1)])))',
    # built small and joined up afterwards: the walk is checked when it happens, not when built
    'ps = []\nls = []\nfor i in range(60):\n    p = []\n    ps.append(p)\n    ls.append([p, p])\n'
    'for i in range(59, 0, -1):\n    ps[i].append(ls[i - 1])\nx = str(ls[59] == ls[59][:])',
    'a = [1]\na.append(a)\nb = [1]\nb.append(b)\nx = str(a == b)',
]




class TestStoreKeys:
    def test_only_program_keys_reach_the_disk(self, tmp_path):
        from prompt_programs.store import program_key
        store = ProgramStore(tmp_path / "store")
        (tmp_path / "secret.json").write_text('{"program": "emit(1)"}')
        (tmp_path / "store").mkdir()
        for bad in ["../secret", "../../secret", "/etc/passwd", "ab/../../secret", "A" * 32, "0" * 31, "", None, 7,
                    "0" * 32 + "/../x", "..%2fsecret"]:
            assert store.get(bad) is None
        with pytest.raises(ValueError):
            store.put("../secret", {"x": 1})
        key = program_key({"prompt": "a cat"})
        store.put(key, {"key": key})
        assert store.get(key) == {"key": key}
