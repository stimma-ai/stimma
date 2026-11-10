"""The program writer's tool-calling session: protocol, line edits, storage and fallbacks.

The model is scripted: each test hands the fake `_ask` the replies it should give, and every
request it receives is recorded, so the tests check both what the code stores and what the
model would have been shown.
"""

import asyncio
import copy
import json

import pytest

from llm import FinishReason, LLMResponse, ToolCall, Usage
from prompt_programs import prepare as prep
from prompt_programs import session as ses
from prompt_programs.runtime import ProgramError
from prompt_programs.session import EditError, apply_edits
from prompt_programs.store import ProgramStore

PROMPT = "A woman waiting for a train on a {rainy|foggy} morning."
EDITED = "A woman waiting for a train on a {rainy|foggy} evening."
GOOD = ('w = pick("weather", ["rainy", "foggy"], source="list", label="Weather", phase=1, line=1)\n'
        'emit("A woman waiting for a train on a", w, "morning.")\n')
# the user's list isn't a pick: a blocking problem
BAD = 'emit("A woman waiting for a train on a rainy morning.")\n'
GOOD_EVENING = GOOD.replace("morning", "evening")


class Cfg:
    max_context_tokens = 262_144

    def get_api_base(self):
        return "http://writer.test/v1"

    def get_model(self):
        return "writer-test"


def write(source, cid="c1"):
    return {"name": "write_program", "arguments": json.dumps({"source": source}), "id": cid}


def edit(edits, cid="c1"):
    return {"name": "edit_program", "arguments": json.dumps({"edits": edits}), "id": cid}


def reply(*calls, content="", finish=FinishReason.TOOL_CALLS):
    return LLMResponse(content=content, finish_reason=finish, usage=Usage(prompt_tokens=10, completion_tokens=5),
                       tool_calls=[ToolCall(id=c.get("id", ""), name=c["name"], arguments=c["arguments"]) for c in calls])


class Model:
    """Scripted replies; records the messages of every request."""

    def __init__(self):
        self.replies = []
        self.seen = []

    async def __call__(self, cfg, messages, tools, max_tokens):
        self.seen.append(copy.deepcopy(messages))
        r = self.replies.pop(0)
        if callable(r):
            r = await r()
        return r


@pytest.fixture
def model(monkeypatch, tmp_path):
    m = Model()
    style = {"guide": "STYLE GUIDE: write rich prose.", "images": []}

    async def fake_style(*a, **kw):
        return style["guide"], list(style["images"])

    async def no_loras(tool_id, items, profile_id):
        return [], {}

    async def endpoint(project_id):
        cfg = Cfg()
        return cfg, prep._PROTOCOL.get(prep._endpoint_id(cfg), "tools")

    monkeypatch.setattr(prep, "writer_style", fake_style)
    monkeypatch.setattr(prep, "lora_candidates", no_loras)
    monkeypatch.setattr(prep, "_store", lambda profile_id: ProgramStore(tmp_path))
    monkeypatch.setattr(prep, "_writer_endpoint", endpoint)
    monkeypatch.setattr(prep, "_PROTOCOL", {})
    monkeypatch.setattr(prep, "on_prepared", lambda entry, **kw: None)
    monkeypatch.setattr("prompt_pipeline._profile_wildcards_and_segments", lambda profile_id: ([], []))
    monkeypatch.setattr(ses, "_ask", m)
    m.style = style
    m.store = ProgramStore(tmp_path)
    return m


def ensure(prompt=PROMPT, **kw):
    return prep.ensure_program(prompt=prompt, tool_id="t", ctx={"model": "m", "mode": "prose", "schema_props": {},
                                                               "enhance": {}},
                               instructions="", lora_items=[], project_id=None, profile_id="p", **kw)


def chain_of(store, entry):
    nodes, why = ses.chain(store, entry["session"])
    assert nodes is not None, why
    return [m for n in nodes for m in n["turns"]]


def assert_replayable(messages):
    """Every assistant tool call is answered by a tool result before the next turn."""
    pending = set()
    for m in messages:
        if m["role"] == "assistant":
            assert not pending, f"unanswered calls {pending}"
            pending = {c["id"] for c in m.get("tool_calls") or []}
            for c in m.get("tool_calls") or []:
                json.loads(c["function"]["arguments"])  # servers re-parse what is replayed
        elif m["role"] == "tool":
            assert m["tool_call_id"] in pending
            pending.discard(m["tool_call_id"])
        else:
            assert not pending, f"unanswered calls {pending} before a {m['role']} message"
    assert not pending


# --------------------------------------------------------------------------- line edits

class TestApplyEdits:
    SRC = 'a = 1\nemit("x",\n     a,\n     "y")\nb = 2\n'

    def test_all_edits_use_the_same_numbering(self):
        out = apply_edits("a\nb\nc\n", [{"line": 1, "text": ""}, {"line": 3, "text": "C"}, {"line": 1.5, "text": "n"}])
        assert out == "n\nb\nC\n"

    def test_insert_before_the_first_line_and_after_the_last(self):
        assert apply_edits("a\nb\n", [{"line": 0.5, "text": "z"}, {"line": 2.5, "text": "end"}]) == "z\na\nb\nend\n"

    def test_a_whole_statement_replaces_its_continuation_lines(self):
        out = apply_edits(self.SRC, [{"line": 2, "text": 'emit("x", a, "z")'}])
        assert out == 'a = 1\nemit("x", a, "z")\nb = 2\n'

    def test_a_partial_line_replaces_only_that_line(self):
        out = apply_edits(self.SRC, [{"line": 3, "text": "     b,"}])
        assert out.splitlines()[2] == "     b,"

    def test_multiline_text_inserts_several_lines(self):
        assert apply_edits("a\nb\n", [{"line": 1, "text": "x\ny"}]) == "x\ny\nb\n"

    def test_one_past_the_end_adds_at_the_end(self):
        # a tail rewritten with one line inserted runs one past the end
        out = apply_edits("a\nb\nc\n", [{"line": 2, "text": "new"}, {"line": 3, "text": "b"}, {"line": 4, "text": "c"}])
        assert out == "a\nnew\nb\nc\n"

    def test_a_trailing_newline_adds_no_blank_line(self):
        assert apply_edits("a = [\n 1]\nb\n", [{"line": 1, "text": "a = [\n"}]) == "a = [\n 1]\nb\n"

    def test_the_numbered_prefix_is_dropped(self):
        assert apply_edits("a\nb\n", [{"line": 2, "text": "2: c"}]) == "a\nc\n"

    @pytest.mark.parametrize("edits, why", [
        ([], "non-empty"),
        ([{"line": 9, "text": "x"}], "doesn't exist"),
        ([{"line": 6, "text": "x"}, {"line": 5.5, "text": "y"}], "two edits add lines"),
        ([{"line": 1, "text": "x"}, {"line": 1, "text": "y"}], "twice"),
        ([{"line": 1.5, "text": "x"}, {"line": 1.5, "text": "y"}], "two edits add lines"),
        ([{"line": 2, "text": 'emit("x", a, "z")'}, {"line": 3, "text": "  q,"}], "can't be edited separately"),
        ([{"line": 2, "text": 'emit("x", a, "z")'}, {"line": 2.5, "text": "q"}], "not inside it"),
        ([{"line": "two", "text": "x"}], "not a number"),
        ([{"line": True, "text": "x"}], "must be a number"),
        ([{"text": "x"}], "{line, text}"),
        ([{"line": 1, "text": 3}], "must be a string"),
    ])
    def test_bad_coordinates_are_rejected(self, edits, why):
        with pytest.raises(EditError, match=why.replace("{", r"\{").replace("}", r"\}")):
            apply_edits(self.SRC, edits)


# --------------------------------------------------------------------------- the protocol

class TestFixQuotes:
    def test_an_error_above_every_emit_leaves_the_lines_alone(self):
        src = ('x = pick("x", ["a", "b"], label="X", source="list", phase=1, line=1)\n'
               '    "stray continuation"], label="Y")\n'
               'emit("A", x)\n')
        out, notes = prep.fix_quotes(src)
        assert out == src and not notes


class TestWrapping:
    @pytest.mark.parametrize("wrapped", [
        "python\n" + GOOD, "```python\n" + GOOD + "```", "```\n" + GOOD + "```\n", "write_program source:\n" + GOOD,
        "Python\n\n" + GOOD, "```py\n" + GOOD,
    ])
    def test_fence_and_label_lines_are_dropped(self, wrapped):
        out, notes = ses.strip_wrapping(wrapped)
        assert out == GOOD and notes

    def test_a_plain_program_is_untouched(self):
        assert ses.strip_wrapping(GOOD) == (GOOD, [])

    async def test_a_tagged_write_validates_first_time(self, model):
        model.replies = [reply(write("python\n" + GOOD))]
        entry = await ensure()
        assert entry["attempts"] == 1 and entry["program"] == GOOD
        assert "'python' around the program dropped" in chain_of(model.store, entry)[-1]["content"]

    async def test_an_edit_that_puts_the_tag_back_on_line_1_is_cleaned(self, model):
        model.replies = [reply(write(BAD)),
                         reply(edit([{"line": 1, "text": "python\n" + GOOD.rstrip()}]))]
        entry = await ensure()
        assert entry["program"] == GOOD and entry["attempts"] == 2


class TestNewPrompt:
    async def test_a_valid_first_write_ends_the_turn(self, model):
        model.replies = [reply(write(GOOD))]
        entry = await ensure()
        assert entry["protocol"] == "tools" and entry["attempts"] == 1 and entry["program"] == GOOD
        log = chain_of(model.store, entry)
        assert [m["role"] for m in log] == ["system", "user", "assistant", "tool"]
        assert "write_program tool" in log[0]["content"] and "```python block" not in log[0]["content"]
        assert "Valid" in log[-1]["content"] and "1: w = pick(" in log[-1]["content"]
        assert model.store.get(entry["key"])["session"] == entry["session"]

    async def test_a_bound_pick_is_narrowed_by_its_words_after_the_write(self, model, monkeypatch):
        import json as _json
        src = ('w = pick("weather", ["rainy", "foggy"], source="list", label="Weather", phase=1, line=1)\n'
               'age = pick("age", cls="person.age_band", where="young", about="her age", seed=["20–24-year-old"], '
               'label="Age", phase=1, added=True)\n'
               'emit("A young", age, "woman waiting for a train on a", w, "morning.")\n')
        asked = []

        async def narrow_ask(messages, project_id, max_tokens=4096):
            asked.append(messages)
            if "find the words in it" in messages[0]["content"]:  # reading the prompt: it says nothing of age
                return _json.dumps({"age": None})
            return _json.dumps(["20–24-year-old", "25–29-year-old"])
        monkeypatch.setattr(prep, "_ask_model", narrow_ask)
        model.replies = [reply(write(src))]
        entry = await ensure()
        assert entry["filters"] == {"age": ["20–24-year-old", "25–29-year-old"]} and len(asked) == 2  # the reading, then "young"
        assert 'fit "young"' in asked[1][1]["content"]  # the writer's where= when the reading finds nothing
        assert next(c for c in entry["choices"] if c["id"] == "age")["options"] == ["20–24-year-old", "25–29-year-old"]
        assert model.store.get(entry["key"])["filters"] == entry["filters"]  # stored narrowed

    @pytest.mark.parametrize("limit", [2.5, 6.0])  # no time left to narrow; time for a narrowing that stalls
    async def test_slow_narrowing_never_loses_the_prepared_program(self, model, monkeypatch, limit):
        import asyncio as _asyncio
        src = ('w = pick("weather", ["rainy", "foggy"], source="list", label="Weather", phase=1, line=1)\n'
               'age = pick("age", cls="person.age_band", where="young", about="her age", seed=["20–24-year-old"], '
               'label="Age", phase=1, added=True)\n'
               'emit("A young", age, "woman waiting for a train on a", w, "morning.")\n')

        async def stalls(messages, project_id, max_tokens=4096):
            await _asyncio.sleep(60)
            return "[]"
        monkeypatch.setattr(prep, "_ask_model", stalls)
        monkeypatch.setattr(prep, "PREPARE_LIMIT_SECONDS", limit)
        model.replies = [reply(write(src))]
        entry = await ensure()
        assert entry["program"] == src and model.store.get(entry["key"]) is not None
        assert not any(entry.get("filters", {}).values())  # unnarrowed or unbound, never a lost prepare

    @pytest.mark.parametrize("prefix", ["python\n", "write_program source:\n"])
    async def test_a_stray_first_line_before_the_program_is_dropped(self, model, prefix):
        model.replies = [reply(write(prefix + GOOD))]
        entry = await ensure()
        assert entry["attempts"] == 1 and entry["program"] == GOOD

    async def test_problems_go_back_as_a_tool_result_and_an_edit_fixes_them(self, model):
        model.replies = [reply(write(BAD)), reply(edit([{"line": 1, "text": GOOD.replace("\n", "\n", 1).rstrip()}]))]
        entry = await ensure()
        assert entry["attempts"] == 2 and entry["program"] == GOOD
        result = model.seen[1][-1]
        assert result["role"] == "tool" and "Problems to fix" in result["content"] and "1: emit(" in result["content"]
        assert_replayable(chain_of(model.store, entry))

    async def test_malformed_arguments_are_answered_and_not_replayed(self, model):
        broken = {"name": "write_program", "arguments": '{"source": "emit(\\"x)', "id": "c1"}
        model.replies = [reply(broken, finish=FinishReason.LENGTH), reply(write(GOOD, "c2"))]
        entry = await ensure()
        assert entry["session_stats"]["json_failures"] == 1 and entry["attempts"] == 2
        log = chain_of(model.store, entry)
        assert log[2]["tool_calls"][0]["function"]["arguments"] == "{}"
        assert "weren't valid JSON" in log[3]["content"] and "cut off" in log[3]["content"]
        assert_replayable(log)

    async def test_a_text_reply_is_nudged_once_then_counts_as_a_call(self, model):
        prep._PROTOCOL[prep._endpoint_id(Cfg())] = "tools"  # known to make tool calls
        model.replies = [reply(content="Sure, here is my plan.", finish=FinishReason.STOP), reply(write(GOOD))]
        entry = await ensure()
        assert entry["session_stats"]["no_tool"] == 1 and entry["attempts"] == 2
        log = chain_of(model.store, entry)
        assert [m["role"] for m in log] == ["system", "user", "assistant", "user", "assistant", "tool"]
        assert "write_program" in log[3]["content"]

    async def test_every_call_in_a_batch_is_answered_and_one_change_applies(self, model):
        model.replies = [reply(write(BAD, "a"), write(GOOD, "b"), {"name": "nope", "arguments": "{}", "id": "c"}),
                         reply(write(GOOD, "d"))]
        entry = await ensure()
        first = model.seen[1]
        results = {m["tool_call_id"]: m["content"] for m in first if m["role"] == "tool"}
        assert set(results) == {"a", "b", "c"}
        assert "Problems to fix" in results["a"] and "one change per reply" in results["b"]
        assert "Unknown tool" in results["c"]
        assert entry["session_stats"]["extra_calls"] == 1 and entry["program"] == GOOD
        assert_replayable(chain_of(model.store, entry))

    async def test_calls_after_an_accepted_write_are_answered_not_run(self, model):
        model.replies = [reply(write(GOOD, "a"), edit([{"line": 1, "text": ""}], "b"))]
        entry = await ensure()
        log = chain_of(model.store, entry)
        assert "already accepted" in log[-1]["content"] and entry["program"] == GOOD
        assert_replayable(log)

    async def test_the_result_shows_the_program_as_fixed_in_code(self, model):
        # a string wrapped onto the next line: fix_quotes joins it, so the numbering changes
        wrapped = ('w = pick("weather", ["rainy", "foggy"], source="list", label="Weather", phase=1, line=1)\n'
                   'emit("A woman waiting for a train on a", w, "mor\nning.")\n'
                   'emit("Extra text that the list never reaches", "{rainy|foggy}")\n')
        model.replies = [reply(write(wrapped)), reply(edit([{"line": 3, "text": ""}]))]
        entry = await ensure()
        shown = model.seen[1][-1]["content"]
        assert "Fixed in code" in shown and "joined onto one line" in shown
        assert "3: emit(\"Extra text" in shown  # the numbering the next edit uses
        assert entry["program"].count("\n") == 2 and "Extra" not in entry["program"]

    async def test_out_of_calls_it_keeps_the_best_program(self, model):
        model.replies = [reply(write(BAD, f"c{i}")) for i in range(ses.MAX_CALLS)]
        entry = await ensure()
        assert entry["attempts"] == ses.MAX_CALLS and entry["program"] == BAD and entry["warnings"]

    async def test_no_program_at_all_fails_and_stores_nothing(self, model, tmp_path):
        model.replies = [reply({"name": "write_program", "arguments": "{", "id": f"c{i}"}) for i in range(ses.MAX_CALLS)]
        with pytest.raises(ProgramError):
            await ensure()
        assert not list(tmp_path.rglob("*.json"))  # no entry, no node, no recent pointer


class TestStuckEdits:
    BROKEN = GOOD.replace("emit(", "emit(missing, ")  # NameError: no program that runs

    async def test_a_failed_edit_with_nothing_runnable_asks_for_a_rewrite(self, model):
        model.replies = [reply(write(self.BROKEN)), reply(edit([{"line": 1, "text": GOOD.splitlines()[0]}])),
                         reply(write(GOOD))]
        entry = await ensure()
        result = model.seen[2][-1]["content"]
        assert "change nothing" in result and "Still to fix" in result and "missing" in result
        assert "write_program" in result.splitlines()[-1] and entry["program"] == GOOD

    async def test_no_rewrite_request_while_a_runnable_program_is_in_hand(self, model):
        model.replies = [reply(write(BAD)), reply(edit([{"line": 1, "text": BAD.strip()}])), reply(write(GOOD))]
        await ensure()
        assert "Write the whole program again" not in model.seen[2][-1]["content"]


class TestDeadline:
    async def test_a_stalled_call_with_nothing_in_hand_times_out(self, model, monkeypatch):
        monkeypatch.setattr(prep, "PREPARE_LIMIT_SECONDS", 0.3)

        async def stall():
            await asyncio.sleep(5)
        model.replies = [stall]
        with pytest.raises(prep.PrepareTimeout):
            await asyncio.wait_for(ensure(), 5)
        assert not prep._in_flight

    async def test_a_stalled_repair_keeps_the_candidate(self, model, monkeypatch, tmp_path):
        monkeypatch.setattr(prep, "PREPARE_LIMIT_SECONDS", 0.3)

        async def stall():
            await asyncio.sleep(5)
        model.replies = [reply(write(BAD)), stall]
        entry = await asyncio.wait_for(ensure(), 5)
        assert entry["program"] == BAD and entry["seconds"] < 2
        log = chain_of(model.store, entry)
        assert log[-1]["role"] == "tool"  # the stalled call left nothing in the log
        assert_replayable(log)

    async def test_past_the_soft_budget_no_repair_starts(self, model, monkeypatch):
        monkeypatch.setattr(prep, "PREPARE_SOFT_SECONDS", 0.0)
        model.replies = [reply(write(BAD))]
        entry = await ensure()
        assert entry["attempts"] == 1 and entry["session_stats"]["soft_stop"]


class TestEdits:
    async def _base(self, model, prompt=PROMPT, program=GOOD):
        model.replies = [reply(write(program))]
        return await ensure(prompt)

    async def test_an_edit_continues_the_session(self, model):
        base = await self._base(model)
        model.replies = [reply(edit([{"line": 2, "text": 'emit("A woman waiting for a train on a", w, "evening.")'}]))]
        entry = await ensure(EDITED)
        assert entry["program"] == GOOD_EVENING and entry["patched_from"] == base["key"] and entry["patch"] == "text"
        node = model.store.get_node(entry["session"])
        assert node["parent"] == base["session"]
        sent = model.seen[-1]
        assert sent[:4] == chain_of(model.store, base)  # the whole earlier log, then the edit turn
        assert "It now reads" in sent[4]["content"] and "2: emit(" in sent[4]["content"]
        assert_replayable(chain_of(model.store, entry))

    async def test_a_list_change_is_carried_in_code(self, model):
        base = await self._base(model)
        entry = await ensure("A woman waiting for a train on a {rainy|foggy|snowy} morning.")
        assert entry["attempts"] == 0 and entry["patch"] == "lists" and '"snowy"' in entry["program"]
        assert model.store.get_node(entry["session"])["parent"] == base["session"]
        # the next edit turn still shows the program as it stands
        model.replies = [reply(edit([{"line": 2, "text": 'emit("A woman waiting for a train on a", w, "evening.")'}]))]
        await ensure("A woman waiting for a train on a {rainy|foggy|snowy} evening.")
        assert '"snowy"' in model.seen[-1][-1]["content"]

    async def test_start_over_writes_fresh_within_the_same_allowance(self, model):
        await self._base(model)
        new = "A red sports car waiting at a train crossing on a {rainy|foggy} morning."
        car = GOOD.replace("A woman waiting for a train on a", "A red sports car waiting at a train crossing on a")
        model.replies = [reply({"name": "start_over", "arguments": '{"reason": "a car"}', "id": "s"}),
                         reply(write(car))]
        entry = await ensure(new)
        assert entry["session_stats"]["start_over"] == "a car" and entry["attempts"] == 2
        assert entry["lineage"] == entry["key"] and "patched_from" not in entry
        node = model.store.get_node(entry["session"])
        assert node["root"] and node["parent"] is None
        assert model.seen[-1][1]["role"] == "user" and "sports car" in model.seen[-1][1]["content"]

    async def test_siblings_share_their_parent_untouched(self, model):
        base = await self._base(model)
        before = model.store.get_node(base["session"])
        model.replies = [reply(edit([{"line": 2, "text": 'emit("A woman waiting for a train on a", w, "evening.")'}]))]
        a = await ensure(EDITED, base_key=base["key"])
        model.replies = [reply(edit([{"line": 2, "text": 'emit("A woman waiting for a train on a", w, "night.")'}]))]
        b = await ensure("A woman waiting for a train on a {rainy|foggy} night.", base_key=base["key"])
        pa, pb = (model.store.get_node(e["session"])["parent"] for e in (a, b))
        assert pa == pb == base["session"] and model.store.get_node(base["session"]) == before

    async def test_the_editors_base_beats_the_closest_recent_prompt(self, model):
        base = await self._base(model)
        model.replies = [reply(edit([{"line": 2, "text": 'emit("A woman waiting for a train on a", w, "evening.")'}]))]
        evening = await ensure(EDITED)
        # the closest recent prompt to this one is the evening one; the editor says it showed the morning one
        model.replies = [reply(edit([{"line": 2, "text": 'emit("A woman waiting for a train on a", w, "dusk.")'}]))]
        dusk = await ensure("A woman waiting for a train on a {rainy|foggy} evening at dusk.", base_key=base["key"])
        assert dusk["patched_from"] == base["key"] and evening["key"] != base["key"]

    async def test_forcing_an_ancestor_leaves_its_descendants_history(self, model):
        base = await self._base(model)
        model.replies = [reply(edit([{"line": 2, "text": 'emit("A woman waiting for a train on a", w, "evening.")'}]))]
        child = await ensure(EDITED, base_key=base["key"])
        model.replies = [reply(write(GOOD.replace("Weather", "Sky")))]
        again = await ensure(force=True)
        assert again["key"] == base["key"] and again["session"] != base["session"]
        assert ses.chain(model.store, child["session"])[0] is not None  # the old ancestor node is still there
        model.replies = [reply(edit([{"line": 2, "text": 'emit("A woman waiting for a train on a", w, "evening light.")'}]))]
        grandchild = await ensure("A woman waiting for a train on a {rainy|foggy} evening light.", base_key=child["key"])
        assert model.store.get_node(grandchild["session"])["parent"] == child["session"]

    async def test_a_restart_replays_the_stored_log(self, model, tmp_path, monkeypatch):
        base = await self._base(model)
        prep._in_flight.clear()
        monkeypatch.setattr(prep, "_store", lambda profile_id: ProgramStore(tmp_path))  # a new store object
        model.replies = [reply(edit([{"line": 2, "text": 'emit("A woman waiting for a train on a", w, "evening.")'}]))]
        entry = await ensure(EDITED)
        assert model.seen[-1][:4] == chain_of(model.store, base) and entry["session_stats"]["reset"] is None

    @pytest.mark.parametrize("damage, why", [("missing", "missing node"), ("cycle", "cycle"), ("old", "no session")])
    async def test_a_broken_history_starts_a_seeded_root(self, model, damage, why):
        base = await self._base(model)
        stored = model.store.get(base["key"])
        if damage == "missing":
            model.store._node_path(base["session"]).unlink()
        elif damage == "cycle":
            node = model.store.get_node(base["session"])
            node["parent"], node["root"] = node["id"], False
            model.store._node_path(node["id"]).write_text(json.dumps(node))
        else:  # prepared without a session (the text protocol, or before this version)
            stored.pop("session")
            model.store.put(base["key"], stored)
        model.replies = [reply(edit([{"line": 2, "text": 'emit("A woman waiting for a train on a", w, "evening.")'}]))]
        entry = await ensure(EDITED)
        assert entry["session_stats"]["reset"] == why and entry["program"] == GOOD_EVENING
        sent = model.seen[-1]
        assert [m["role"] for m in sent] == ["system", "user", "assistant", "tool", "user"]
        assert json.loads(sent[2]["tool_calls"][0]["function"]["arguments"])["source"] == GOOD
        node = model.store.get_node(entry["session"])
        assert node["root"] and node["parent"] is None
        assert_replayable(chain_of(model.store, entry))

    async def test_a_long_log_starts_a_seeded_root(self, model, monkeypatch):
        await self._base(model)
        monkeypatch.setattr(ses, "HISTORY_CEILING", 50)
        model.replies = [reply(edit([{"line": 2, "text": 'emit("A woman waiting for a train on a", w, "evening.")'}]))]
        entry = await ensure(EDITED)
        assert entry["session_stats"]["reset"] == "context cap"

    async def test_a_changed_style_guide_starts_a_seeded_root(self, model):
        await self._base(model)
        model.style["guide"] = "STYLE GUIDE: write tags."
        model.replies = [reply(edit([{"line": 2, "text": 'emit("A woman waiting for a train on a", w, "evening.")'}]))]
        entry = await ensure(EDITED)
        assert entry["session_stats"]["reset"] == "style guide changed"
        assert "write tags" in model.seen[-1][0]["content"]

    async def test_the_fallback_program_is_what_the_next_edit_shows(self, model):
        model.replies = [reply(write(BAD, f"c{i}")) for i in range(ses.MAX_CALLS)]
        base = await ensure()
        model.replies = [reply(edit([{"line": 1, "text": GOOD_EVENING.rstrip()}]))]
        entry = await ensure(EDITED)
        assert entry["program"] == GOOD_EVENING
        assert "1: emit(\"A woman waiting for a train on a rainy morning.\")" in model.seen[-1][-1]["content"]
        assert base["program"] == BAD


class TestImages:
    async def test_images_are_stored_as_references_and_put_back(self, model):
        model.style["images"] = [(1, "QUJDRA==")]
        base = await TestEdits()._base(model)
        raw = model.store._node_path(base["session"]).read_text()
        assert "QUJDRA==" not in raw and "image_ref" in raw
        model.replies = [reply(edit([{"line": 2, "text": 'emit("A woman waiting for a train on a", w, "evening.")'}]))]
        await ensure(EDITED)
        user = model.seen[-1][1]["content"]
        assert any(p.get("type") == "image_url" and "QUJDRA==" in p["image_url"]["url"] for p in user)

    async def test_a_new_source_image_starts_a_seeded_root(self, model):
        model.style["images"] = [(1, "QUJDRA==")]
        await TestEdits()._base(model)
        model.style["images"] = [(1, "RUZHSA==")]
        model.replies = [reply(edit([{"line": 2, "text": 'emit("A woman waiting for a train on a", w, "evening.")'}]))]
        entry = await ensure(EDITED)
        assert entry["session_stats"]["reset"] == "images changed"
        assert any("RUZHSA==" in (p.get("image_url") or {}).get("url", "") for p in model.seen[-1][1]["content"])


class TestTextFallback:
    async def test_an_endpoint_without_tool_calls_gets_the_text_protocol(self, model, monkeypatch):
        async def refuse():
            raise RuntimeError('400 Bad Request: "auto" tool choice requires --enable-auto-tool-choice')
        model.replies = [refuse]
        texts = []

        async def ask_text(messages, project_id, max_tokens=4096):
            texts.append(messages)
            return f"```python\n{GOOD}```"
        monkeypatch.setattr(prep, "_ask_model", ask_text)
        entry = await ensure()
        assert entry["protocol"] == "text" and len(texts) == 1 and "session" not in entry
        await ensure(EDITED.replace("evening", "night"))  # known now: no tool request at all
        assert len(model.seen) == 1

    async def test_the_providers_own_message_is_read(self, model, monkeypatch):
        class Rejected(Exception):
            upstream_status = 400
            upstream_message = '"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser'

        async def refuse():
            raise Rejected("The AI provider rejected the request (HTTP 400).")
        model.replies = [refuse]

        async def ask_text(messages, project_id, max_tokens=4096):
            return f"```python\n{GOOD}```"
        monkeypatch.setattr(prep, "_ask_model", ask_text)
        assert (await ensure())["protocol"] == "text"

    async def test_other_rejections_are_not_taken_for_missing_tools(self, model):
        class Rejected(Exception):
            upstream_status = 400
            upstream_message = "This model's maximum context length is 8192 tokens"

        async def refuse():
            raise Rejected("The AI provider rejected the request (HTTP 400).")
        model.replies = [refuse]
        with pytest.raises(Rejected):
            await ensure()
        assert prep._PROTOCOL == {}

    async def test_a_program_written_as_text_switches_to_the_text_protocol(self, model, monkeypatch):
        model.replies = [reply(content=f"```python\n{GOOD}```", finish=FinishReason.STOP)]

        async def ask_text(messages, project_id, max_tokens=4096):
            return f"```python\n{GOOD}```"
        monkeypatch.setattr(prep, "_ask_model", ask_text)
        entry = await ensure()
        assert entry["protocol"] == "text" and prep._PROTOCOL[prep._endpoint_id(Cfg())] == "text"


class TestKeysAndFlights:
    async def test_the_writer_model_is_part_of_the_key(self, model, monkeypatch):
        model.replies = [reply(write(GOOD))]
        a = await ensure()

        class Other(Cfg):
            def get_model(self):
                return "another-writer"

        async def other(project_id):
            return Other(), "tools"
        monkeypatch.setattr(prep, "_writer_endpoint", other)
        model.replies = [reply(write(GOOD))]
        b = await ensure()
        assert a["key"] != b["key"]

    async def test_a_forced_prepare_never_joins_an_ordinary_one(self, model):
        gate = asyncio.Event()

        async def slow():
            await gate.wait()
            return reply(write(GOOD))
        model.replies = [slow, reply(write(GOOD.replace("Weather", "Sky")))]
        first = asyncio.ensure_future(ensure())
        await asyncio.sleep(0.05)
        forced = asyncio.ensure_future(ensure(force=True))
        await asyncio.sleep(0.05)
        gate.set()
        a, b = await first, await forced
        assert len(model.seen) == 2 and a["program"] != b["program"]


# --------------------------------------------------------------------------- Enhance levels

class TestEnhanceLevels:
    def test_level_from_old_and_new_clients(self):
        assert prep.enhance_level(None, True) == "expand"
        assert prep.enhance_level(None, False) == "off"
        assert prep.enhance_level("fill", True) == "fill"
        assert prep.enhance_level("FILL", False) == "fill"
        assert prep.enhance_level("bogus", False) == "off"

    def test_fill_sends_the_fill_guide_and_keeps_the_users_words(self, model, monkeypatch):
        levels = []

        async def style(*a, **kw):
            levels.append(a[6] if len(a) > 6 else kw.get("level"))
            return "FILL GUIDE: quote in-image text.", []

        monkeypatch.setattr(prep, "writer_style", style)
        model.replies = [reply(write(GOOD))]
        entry = asyncio.run(ensure(enhance="fill"))
        assert levels == ["fill"]
        system, user = model.seen[0][0]["content"], model.seen[0][1]["content"]
        assert "FILL GUIDE: quote in-image text." in system
        assert "keeping the user's words" in user and "only what the style guide says the model needs" in user
        assert "complete and rich" not in user
        # validated and seeded like Enhance off: the user's words, short seeds
        assert entry["enhance"] == "fill" and entry["elaborate"] is False

    def test_off_sends_no_guide(self, model, monkeypatch):
        async def style(*a, **kw):
            raise AssertionError("Enhance off has no style guide")

        monkeypatch.setattr(prep, "writer_style", style)
        model.replies = [reply(write(GOOD))]
        entry = asyncio.run(ensure(enhance="off"))
        assert "STYLE GUIDE" not in model.seen[0][0]["content"]
        assert entry["enhance"] == "off"

    def test_levels_are_separate_programs(self, model):
        model.replies = [reply(write(GOOD)), reply(write(GOOD))]
        expand = asyncio.run(ensure(enhance="expand"))
        fill = asyncio.run(ensure(enhance="fill"))
        assert expand["key"] != fill["key"]
        assert expand["enhance"] == "expand" and expand["elaborate"] is True
