"""The program writer as a tool-calling session.

One message log per program lineage: the system message (instructions and this image
model's style guide) and the user's prompt start it; each prepare adds a user turn (the
prompt, or what an edit changed) and the model's tool calls with their results. The
program is written and changed only through tools, and every write or edit is answered by
code: applied, fixed in code, validated, and shown back numbered as it now stands, so the
model's view of the program is the stored program.

The log is stored as immutable nodes in the program store (ProgramStore.put_node), each
holding the messages one prepare added and its parent's id. An entry points at its node;
an edit continues from the node of the entry it edits, so two edits of one program are
siblings and a regenerated entry never rewrites history another entry continues from.

A turn ends when a write or edit validates (no further model call), or when the call
allowance or the deadline runs out, keeping the best program so far. Tools are a small
table (name → schema → handler → whether it changes the program), so a read-only tool is
one more row.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger
from prompt_programs import prepare as prep
from prompt_programs.runtime import LoraInfo, ProgramError, check
from prompt_programs.store import ProgramStore

log = get_logger(__name__)

# Model calls per prepare, across writes, edits, repairs, replies without a tool call and a
# start over (the text protocol allows MAX_ATTEMPTS = 3 for a new prompt).
MAX_CALLS = 4
# A log longer than this (or than the endpoint's window allows) starts a new root, seeded
# with the current prompt and program. No compaction.
HISTORY_CEILING = 24_000
_IMAGE_TOKENS = 800
_TOOL_TOKENS = 700
_MAX_DEPTH = 64


class ToolsUnsupported(Exception):
    """The endpoint's model makes no tool calls: use the text protocol."""


# --------------------------------------------------------------------------- what the model reads

_TEXT_OUTPUT = "Reply with only the program in one ```python block."
_TOOL_OUTPUT = ("Write the program with the write_program tool: its source is the whole program. Change it with "
                "edit_program.")
_STYLE_TEXT = "Its rules about how to reply don't\napply: you reply with the program."
_STYLE_TOOLS = "Its rules about how to reply don't\napply: you write the program with the tools."


def system_text(guide: str, elaborate: bool = True) -> str:
    """instructions.md and the style guide, with the text protocol's reply rules swapped for
    the tools'. Only the protocol differs from the text writer's system message."""
    text = prep._INSTRUCTIONS
    assert _TEXT_OUTPUT in text, "instructions.md lost its Output line"
    text = text.replace(_TEXT_OUTPUT, _TOOL_OUTPUT).replace("\nProgram:\n```python", "\nwrite_program source:\n```python")
    if guide:  # Enhance off sends no guide
        assert _STYLE_TEXT in prep._STYLE_NOTE
        text += prep._STYLE_NOTE.replace(_STYLE_TEXT, _STYLE_TOOLS) + guide.strip()
    return text


EDIT_TURN = """The user edited their prompt. It now reads (lines numbered):
{prompt}

What changed: {changes}.

The program as it stands now, with line numbers:
{numbered}

First decide: is this an edit of the same prompt, or a different prompt?
- A different prompt: what the image is of has changed (a woman walking a dog became a sports car;
  a bowl of ramen became a sleeping kitten; a fisherman became a cyberpunk hacker). Little of the
  program would survive. Call start_over, and it will be written fresh.
- An edit: the same subject with something changed, added or removed (a red coat became a blue
  coat, a guitar became a violin, autumn became spring, "seagulls overhead" was added, a # line
  was added). Update the program to match with edit_program, changing as little as you can: the
  emitted text and the picks this edit affects, by the same rules. Keep every other line as it is."""

_NUDGE_NEW = "Write the program with a tool call: write_program with the whole program."
_NUDGE_EDIT = ("Make the change with a tool call: edit_program with numbered-line edits, write_program with the "
               "whole program, or start_over if the new prompt is a different prompt.")


def _tool(name: str, description: str, properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}}


WRITE_SCHEMA = _tool(
    "write_program",
    "Write the whole program. The code checks it, fixes small slips itself, and answers with the program as it "
    "now stands, with line numbers, and any problems left to fix.",
    {"source": {"type": "string", "description": "The whole program: Python source, each string on one line."}},
    ["source"])

EDIT_SCHEMA = _tool(
    "edit_program",
    "Change the program by its line numbers, as shown in the latest numbered program. Send only the changed "
    "lines, already changed. Each edit is {line, text}:\n"
    "- line N (a whole number): line N becomes text. Empty text deletes line N. If line N starts a statement "
    "that continues over the next lines and text is the whole new statement, it replaces all of those lines.\n"
    "- line N.5: text is added after line N (0.5 adds it before line 1; the last line's number plus one adds it at "
    "the end).\n"
    "text may hold several lines. All numbers refer to the program before this change, and each line is "
    "edited at most once.",
    {"edits": {"type": "array", "items": {"type": "object", "properties": {
        "line": {"type": "number", "description": "A line number, or N.5 to add after line N."},
        "text": {"type": "string", "description": "The new text; empty deletes the line."}},
        "required": ["line", "text"]}}},
    ["edits"])

# No argument: a "reason" field invited the model to argue an added detail into a new subject,
# and fewer edits were kept as edits.
START_OVER_SCHEMA = _tool(
    "start_over",
    "The user's edited prompt is a different prompt, not an edit: what the image is of has changed, and little of "
    "the program would survive. The program is then written fresh. Use it only then.",
    {}, [])


# --------------------------------------------------------------------------- line edits

class EditError(ValueError):
    """Line edits that can't be applied as given; the message says why."""


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise EditError("line must be a number")
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            raise EditError(f"line {value!r} is not a number") from None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EditError("line must be a number")
    return float(value)


def _parses(text: str) -> bool:
    try:
        ast.parse(text)
        return True
    except SyntaxError:
        return False


def apply_edits(source: str, edits: Any) -> str:
    """Apply numbered-line edits, all against the same pre-edit numbering (see EDIT_SCHEMA).
    Raises EditError for coordinates that are missing, out of range, repeated or overlapping."""
    if not isinstance(edits, list) or not edits:
        raise EditError("edits must be a non-empty list of {line, text}")
    lines = source.rstrip("\n").splitlines()
    n = len(lines)
    spans: Dict[int, int] = {}
    try:
        for st in ast.walk(ast.parse(source)):
            if isinstance(st, ast.stmt):
                spans[st.lineno] = max(spans.get(st.lineno, st.lineno), st.end_lineno or st.lineno)
    except SyntaxError:
        pass
    replace: Dict[int, List[str]] = {}
    insert: Dict[int, List[str]] = {}
    for e in edits:
        if not isinstance(e, dict) or "line" not in e:
            raise EditError("each edit is {line, text}")
        at = _number(e["line"])
        text = e.get("text")
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise EditError(f"text for line {e['line']} must be a string")
        k = math.floor(at)
        # the numbered view leaks into the text sometimes: "7: emit(...)" for line 7
        text = re.sub(rf"^\s*{k}(?:\.\d+)?:[ \t]", "", text)
        # a trailing newline ends the text, it is not an empty line ("seed=[\n")
        new = [ln.rstrip() for ln in text.rstrip("\n").split("\n")] if text.strip() else []
        if at == k and k == n + 1:  # one past the last line: added at the end (a rewritten tail runs one longer)
            if n in insert:
                raise EditError(f"two edits add lines after line {n}: put them in one text")
            insert[n] = new
        elif at == k:
            if not 1 <= k <= n:
                raise EditError(f"line {k} doesn't exist: the program has {n} lines (add a line after line N with N.5)")
            if k in replace:
                raise EditError(f"line {k} is edited twice")
            replace[k] = new
        else:
            if not 0 <= k <= n:
                raise EditError(f"line {at:g} is past the end: the program has {n} lines")
            if k in insert:
                raise EditError(f"two edits add lines after line {k}: put them in one text")
            insert[k] = new
    skip: Dict[int, int] = {}  # line -> the edited line whose new statement covers it
    for k, new in replace.items():
        end = spans.get(k, k)
        if new and end > k and _parses("\n".join(x.strip() for x in new) if len(new) == 1 else "\n".join(new)):
            for j in range(k + 1, end + 1):
                if j in replace:
                    raise EditError(f"line {k}'s new text is the whole statement through line {end}, so line {j} "
                                    "can't be edited separately: send the statement once, or each line on its own")
                skip[j] = k
            for j in range(k, end):
                if j in insert:
                    raise EditError(f"line {k}'s new text replaces the statement through line {end}: add lines "
                                    f"after line {end}, not inside it")
    out: List[str] = list(insert.get(0, []))
    for i, line in enumerate(lines, start=1):
        if i in skip:
            pass
        elif i in replace:
            new = replace[i]
            indent = line[: len(line) - len(line.lstrip())]
            if new and not new[0].startswith((" ", "\t")):
                new = [indent + new[0], *new[1:]]
            out.extend(new)
        else:
            out.append(line)
        out.extend(insert.get(i, []))
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- one user turn

@dataclass
class Candidate:
    source: str
    checked: Dict[str, Any]
    problems: List[str]
    blocking: List[str] = field(default_factory=list)  # problems it can't run with (prepare.validate)

    def rank(self) -> Tuple[int, int]:
        return (len(self.blocking), len(self.problems))

    @property
    def runs(self) -> bool:
        """It can stand in for a valid program: what's left costs variety, not the user's words."""
        return not self.blocking


@dataclass
class Turn:
    """What one user turn works on: the prompt, the program as it stands (the code's, not the
    model's), the best candidate so far and how the turn ended."""
    prompt: str
    elaborate: bool
    loras: Sequence[LoraInfo]
    params: Dict[str, Any]
    old: Optional[str] = None          # an edit turn: the prompt before the edit
    program: Optional[str] = None
    best: Optional[Candidate] = None
    accepted: Optional[Candidate] = None
    accepted_by: str = ""
    start_over: Optional[str] = None
    fixes: List[str] = field(default_factory=list)
    last_error: str = ""

    @property
    def editing(self) -> bool:
        return self.old is not None

    @property
    def done(self) -> bool:
        return self.accepted is not None or self.start_over is not None

    def numbered(self) -> str:
        if not self.program:
            return "There is no program yet."
        return "The program now, with line numbers:\n" + prep._numbered_program(self.program)

    def settle(self, source: str, how: str) -> str:
        """Fix in code, validate, and say what happened. The fixed source is the program now.
        how: "write", "edit" (the model's), or "code" (a list or [exact text] change carried
        over in code)."""
        source, fixed = strip_wrapping(source)
        if how in ("edit", "code") and self.editing:  # a prompt edit carried into the program: the patch fixes
            source, _ = prep.fix_quotes(source)
            source, more = prep.fix_patched(source, self.prompt)
        else:
            source = prep.drop_name_options(prep.expand_people(source), self.prompt)
            source, more = prep.fix_written(source, self.prompt, self.loras)
        fixed += more
        self.fixes += fixed
        self.program = source
        checked: Optional[Dict[str, Any]] = None
        try:
            check(source)
            checked = prep.validate(source, self.prompt, self.loras, set(self.params), self._example(), self.elaborate)
            problems = list(checked["problems"])
        except ProgramError as e:
            problems = [str(e)]
        except (RecursionError, ValueError, TypeError, KeyError, IndexError) as e:  # a program the checks trip on
            log.warning(f"[prompt-program] validating a written program failed: {type(e).__name__}: {e}")
            problems = [f"The program couldn't be run: {type(e).__name__}: {e}"]
        if checked is not None:
            found = Candidate(source, checked, problems, list(checked.get("blocking") or []))
            if self.best is None or found.rank() <= self.best.rank():
                self.best = found
            if not problems:
                self.accepted, self.accepted_by = self.best, how
        self.last_error = "\n".join(problems)
        parts = []
        if fixed:
            parts.append("Fixed in code: " + "; ".join(fixed) + ".")
        parts.append("Problems to fix:\n" + "\n".join(f"- {p}" for p in problems) if problems
                     else "Valid: the program is accepted.")
        parts.append(self.numbered())
        return "\n".join(parts)

    def _example(self) -> str:
        """What validation compares the program with: nothing extra with Enhance on, the user's
        own words in kept-words mode."""
        return "" if self.elaborate else prep.plain_example(self.prompt)

    def refuse(self, why: str) -> str:
        still = f"\nStill to fix:\n" + "\n".join(f"- {p}" for p in self.last_error.split("\n")) if self.last_error else ""
        return f"Not applied: {why}{still}\n{self.numbered()}"


# A line that is never program text: a code fence, a fence's language tag on its own ("python"),
# or the label the instructions' examples put above a program. Models wrap the source with them.
_WRAPPING = re.compile(r"^\s*(?:```\s*(?:python|py)?|python3?|py|(?:write_program\s+)?source:|program:)\s*$", re.I)


def strip_wrapping(source: str) -> Tuple[str, List[str]]:
    """Fence and label lines around the program (leading or trailing) dropped. Returns the
    source and what was cut, for the tool result."""
    lines = source.split("\n")
    cut = []
    while lines and (_WRAPPING.match(lines[0]) or not lines[0].strip()):
        if lines[0].strip():
            cut.append(lines[0].strip())
        lines.pop(0)
    while lines and (_WRAPPING.match(lines[-1]) or not lines[-1].strip()):
        if lines[-1].strip():
            cut.append(lines[-1].strip())
        lines.pop()
    if not cut:
        return source, []
    return "\n".join(lines) + "\n", [f"{', '.join(repr(c) for c in dict.fromkeys(cut))} around the program dropped"]


def _write(turn: Turn, args: Dict[str, Any]) -> str:
    source = args.get("source")
    if not isinstance(source, str) or not source.strip():
        return turn.refuse("write_program needs source: the whole program as one string.")
    return turn.settle(source, "write")


# The text protocol's escalation: a repair that doesn't settle it is followed by a rewrite. In the
# session, an edit that leaves the turn with no program that runs asks for one.
_REWRITE = ("Edits haven't made a program that runs. Write the whole program again with write_program, "
            "fixing what is listed above.")


def _edit(turn: Turn, args: Dict[str, Any]) -> str:
    if turn.program is None:
        return turn.refuse("there is no program yet: write it with write_program.")
    try:
        edited = apply_edits(turn.program, args.get("edits"))
    except EditError as e:
        result = turn.refuse(f"{e}.")
    else:
        result = turn.refuse("those edits change nothing.") if edited == turn.program else turn.settle(edited, "edit")
    if turn.accepted is None and turn.best is None:
        result += "\n" + _REWRITE
    return result


def _start_over(turn: Turn, args: Dict[str, Any]) -> str:
    if not turn.editing:
        return turn.refuse("this is a new prompt: write its program with write_program.")
    # a reason isn't asked for, but some models give one anyway: it goes in the log
    turn.start_over = str(args.get("reason") or "").strip()[:200] or "a different prompt"
    return "Starting over: the program will be written fresh for the new prompt."


@dataclass
class Tool:
    schema: Dict[str, Any]
    handler: Callable[[Turn, Dict[str, Any]], str]
    mutates: bool  # changes the program (one per reply; may end the turn). False: read-only, any number.


TOOLS: Dict[str, Tool] = {
    "write_program": Tool(WRITE_SCHEMA, _write, True),
    "edit_program": Tool(EDIT_SCHEMA, _edit, True),
    "start_over": Tool(START_OVER_SCHEMA, _start_over, True),
}


# --------------------------------------------------------------------------- the model call

async def _ask(cfg: Any, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], max_tokens: int) -> Any:
    from agent.v2.llm_options import agent_llm_options
    from llm import llm_completion
    from llm_correlation import llm_correlation_context
    with llm_correlation_context("prompt-program"):
        return await llm_completion(cfg, messages, tools=tools, max_tokens=max_tokens, temperature=0.3,
                                    **agent_llm_options(enable_thinking=False))


def _no_tools_error(e: Exception) -> bool:
    """A request rejected because the endpoint doesn't take tools (vLLM without a tool parser:
    400 '"auto" tool choice requires --enable-auto-tool-choice'). The provider's own message
    rides on the exception (LLMProviderHTTPError.upstream_message), not in its summary."""
    status = getattr(e, "upstream_status", None)
    msg = f"{e} {getattr(e, 'upstream_message', '') or ''}".lower()
    rejected = status in (400, 404, 422, 501) or any(x in msg for x in ("400", "bad request", "unsupported"))
    return rejected and any(x in msg for x in ("tool", "function call", "function_call"))


class Budget:
    """One deadline and one call allowance for a whole prepare."""

    def __init__(self, started: float, cfg: Any, max_tokens: int):
        self.started = started
        self.calls = 0
        self.timed_out = False
        self.max_tokens = max_tokens
        self.window = int(getattr(cfg, "max_context_tokens", None) or 32_768)
        self.history_cap = min(HISTORY_CEILING, self.window - max_tokens - _TOOL_TOKENS - 1024)

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def left(self) -> float:
        return prep.prepare_limit() - self.elapsed()


def estimate_tokens(messages: Sequence[Dict[str, Any]]) -> int:
    """A rough, high count: characters / 3, an image as _IMAGE_TOKENS."""
    chars, images = 0, 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for part in content:
                if part.get("type") in ("image_url", "image_ref"):
                    images += 1
                else:
                    chars += len(str(part.get("text") or ""))
        else:
            chars += len(content or "")
        for c in m.get("tool_calls") or []:
            chars += len(c["function"]["arguments"]) + 40
    return chars // 3 + images * _IMAGE_TOKENS


async def _converse(cfg: Any, messages: List[Dict[str, Any]], added: List[Dict[str, Any]], turn: Turn,
                    budget: Budget, calls_log: List[Dict[str, Any]], stats: Dict[str, Any]) -> None:
    """Call the model until the turn ends: a write or edit validates, start_over, or the
    allowance, the deadline or the window runs out. Every message goes into `messages` (the
    whole log) and `added` (what this prepare stores). Every tool call gets its result, so
    the log is always a valid conversation to replay."""
    tools = [t.schema for t in TOOLS.values()]
    endpoint = prep._endpoint_id(cfg)

    def push(message: Dict[str, Any]) -> None:
        messages.append(message)
        added.append(message)

    # Replies in prose before anything was written (see _prose_only), in a row.
    declining: Optional[List[str]] = []

    while not turn.done:
        if budget.calls >= MAX_CALLS:
            break
        if turn.best is not None and budget.elapsed() > prep.prepare_soft():
            stats["soft_stop"] = True
            break
        if budget.left() <= 0:
            budget.timed_out = True
            break
        if turn.best is not None and estimate_tokens(messages) + _TOOL_TOKENS + budget.max_tokens > budget.window:
            stats["window_stop"] = True
            break
        t0 = time.monotonic()
        try:
            resp = await asyncio.wait_for(_ask(cfg, messages, tools, budget.max_tokens), budget.left())
        except asyncio.TimeoutError:
            budget.timed_out = True
            break
        except Exception as e:
            if prep._PROTOCOL.get(endpoint) != "tools" and _no_tools_error(e):
                raise ToolsUnsupported(str(e)[:200]) from e
            raise
        budget.calls += 1
        usage = getattr(resp, "usage", None)
        rec: Dict[str, Any] = {"seconds": round(time.monotonic() - t0, 2),
                               "tokens_in": getattr(usage, "prompt_tokens", 0) or 0,
                               "tokens_out": getattr(usage, "completion_tokens", 0) or 0}
        content = (resp.content or "").strip()
        if not resp.tool_calls:
            if prep._PROTOCOL.get(endpoint) != "tools" and "```" in content and "emit(" in content:
                raise ToolsUnsupported("it replied with the program as text")
            if declining is not None and _prose_only(resp, content) and prep._PROTOCOL.get(endpoint) == "tools":
                declining.append(content)
                if len(declining) >= DECLINE_REPLIES:
                    stats["no_tool"] += 1
                    log.info(f"[prompt-program] the writer answered in prose {len(declining)} times without "
                             "writing anything: it declined this prompt")
                    raise prep.PrepareDeclined("\n---\n".join(declining))
            else:
                declining = None
            stats["no_tool"] += 1
            calls_log.append({**rec, "kind": "text", "chars": len(content)})
            push({"role": "assistant", "content": content or "(no reply)"})
            push({"role": "user", "content": _NUDGE_EDIT if turn.editing else _NUDGE_NEW})
            continue
        prep._PROTOCOL[endpoint] = "tools"
        declining = None  # it took the task: whatever happens next is not a refusal
        parsed: List[Tuple[str, str, Any, Optional[ValueError]]] = []
        wire: List[Dict[str, Any]] = []
        for i, call in enumerate(resp.tool_calls):
            cid = call.id or f"call_{budget.calls}_{i}"
            raw = call.arguments or "{}"
            try:
                args, err = json.loads(raw), None
            except ValueError as e:
                args, err = None, e
            if err is not None:
                # Local models often put the program's line breaks (or tabs) into the JSON
                # string as they are: read that leniently, and replay it re-encoded.
                try:
                    args, err = json.loads(raw, strict=False), None
                    raw = json.dumps(args, ensure_ascii=False)
                    stats["json_recovered"] = stats.get("json_recovered", 0) + 1
                except ValueError:
                    pass
            # Malformed arguments aren't replayed (servers re-parse them): the result says what happened.
            wire.append({"id": cid, "type": "function",
                         "function": {"name": call.name, "arguments": raw if err is None else "{}"}})
            parsed.append((cid, call.name, args, err))
        push({"role": "assistant", "content": content, "tool_calls": wire})
        kinds = []
        mutated = False
        for cid, name, args, err in parsed:
            tool = TOOLS.get(name)
            if tool is None:
                text = f"Unknown tool {name!r}. The tools are {', '.join(TOOLS)}."
                kinds.append("unknown")
            elif turn.done:
                text = "Not run: " + ("the program was already accepted." if turn.accepted else "starting over.")
                kinds.append("skipped")
            elif tool.mutates and mutated:
                stats["extra_calls"] += 1
                text = turn.refuse("one change per reply: the call before this one was applied; make further "
                                   "changes after reading its result.")
                kinds.append("skipped")
            elif err is not None:
                stats["json_failures"] += 1
                finish = getattr(resp, "finish_reason", None)
                cut = " The reply was cut off: it was too long." if getattr(finish, "value", finish) == "length" else ""
                text = turn.refuse(f"the arguments weren't valid JSON ({err}).{cut} Call {name} again with valid "
                                   "JSON arguments.")
                mutated = mutated or tool.mutates
                kinds.append(f"{name}:json")
            else:
                # In a worker thread: writing or editing validates the program (some 50 runs
                # of it), which must not hold up the event loop. Nothing else touches `turn`
                # meanwhile: this loop is its only user, and it waits here.
                text = await asyncio.to_thread(tool.handler, turn, args if isinstance(args, dict) else {})
                mutated = mutated or tool.mutates
                kinds.append(name)
            push({"role": "tool", "tool_call_id": cid, "name": name, "content": text})
        calls_log.append({**rec, "kind": ",".join(kinds), "problems": turn.last_error.count("\n") + 1
                          if turn.last_error else 0, "accepted": turn.accepted is not None})


# A writer that answers the prompt in prose instead of a tool call, this many times in a row
# before writing anything (its first reply, then once more after the nudge to use the tool),
# declined the prompt (prep.PrepareDeclined). One prose reply is often a weak model talking
# before it writes, and the nudge fixes it; twice in a row with nothing written is a refusal.
# Read from the shape of the replies only, never their words.
DECLINE_REPLIES = 2


def _prose_only(resp: Any, content: str) -> bool:
    """A reply that is only prose: some text, no tool call, no code block (a program written
    as text is an attempt, not a refusal), and not cut off at the token cap."""
    finish = getattr(resp, "finish_reason", None)
    return bool(content) and not resp.tool_calls and "```" not in content and getattr(finish, "value", finish) != "length"


# --------------------------------------------------------------------------- storage

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _for_storage(messages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Messages as stored: images as references to the request's images, not base64."""
    out = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                url = (part.get("image_url") or {}).get("url", "") if part.get("type") == "image_url" else ""
                if url.startswith("data:"):
                    parts.append({"type": "image_ref", "sha": _sha(url.split(",", 1)[-1])})
                else:
                    parts.append(part)
            m = {**m, "content": parts}
        out.append(m)
    return out


def _attach(messages: Sequence[Dict[str, Any]], images: Dict[str, str]) -> Optional[List[Dict[str, Any]]]:
    """Stored messages with their images put back. None if an image is no longer at hand."""
    out = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                if part.get("type") == "image_ref":
                    b64 = images.get(part.get("sha"))
                    if b64 is None:
                        return None
                    parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
                else:
                    parts.append(part)
            m = {**m, "content": parts}
        out.append(m)
    return out


def chain(store: ProgramStore, node_id: Optional[str]) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """The nodes from the root to node_id, or None and why not (missing node, a cycle, too deep)."""
    if not node_id:
        return None, "no session"
    nodes: List[Dict[str, Any]] = []
    seen = set()
    at: Optional[str] = node_id
    while at:
        if at in seen:
            return None, "cycle"
        if len(nodes) >= _MAX_DEPTH:
            return None, "too deep"
        seen.add(at)
        node = store.get_node(at)
        if node is None:
            return None, "missing node"
        nodes.append(node)
        at = node.get("parent")
    nodes.reverse()
    if not nodes[0].get("root"):
        return None, "no root"
    return nodes, ""


# --------------------------------------------------------------------------- a prepare

async def prepare_session(*, cfg: Any, base: Optional[Dict[str, Any]], context: str, started: float, key: str,
                          store: ProgramStore, tool_id: str, ctx: Dict[str, Any], instructions: str,
                          source_prompt: str, params: Dict[str, Any], loras: List[LoraInfo], notes: Dict[str, str],
                          lora_context: List[Dict[str, Any]], project_id: Optional[int], profile_id: Optional[str],
                          elaborate: bool = True, level: str = "",
                          exact: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Prepare `source_prompt` ([exact text] already masked) as a session turn: an edit of
    `base` continues its log, anything else starts a new one. Stores the session node and
    returns the entry; the caller stores the entry (node before pointer)."""
    prompt = source_prompt
    mode = ctx.get("mode") or "prose"
    level = level or ("expand" if elaborate else "off")
    guide, images = (await prep.writer_style(prompt, ctx, instructions, lora_context, project_id, profile_id, level)
                     if level != "off" else ("", []))
    styled_at = time.monotonic()
    system = {"role": "system", "content": system_text(guide, elaborate)}
    sys_hash = _sha(system["content"])
    manifest = [[n, _sha(b64)] for n, b64 in images]
    by_sha = {_sha(b64): b64 for _, b64 in images}
    budget = Budget(started, cfg, prep._writer_cap(prompt))
    calls_log: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {"json_failures": 0, "no_tool": 0, "extra_calls": 0, "reset": None, "start_over": None,
                             "soft_stop": False, "window_stop": False}

    def user_message(for_prompt: str) -> Dict[str, Any]:
        return prep.writer_messages(for_prompt, guide, images, ctx.get("model"), mode, params, loras, notes,
                                    elaborate, instructions, level)[1]

    def node_for(parent: Optional[str], turns: List[Dict[str, Any]], program: str) -> str:
        return store.put_node({"parent": parent, "root": parent is None, "system_hash": sys_hash, "images": manifest,
                               "prompt": prompt, "program": program, "key": key, "turns": _for_storage(turns),
                               "created_at": time.time()})

    turn: Optional[Turn] = None
    node_id: Optional[str] = None
    patch_kind: Optional[str] = None

    if base is not None:
        old = base["prompt"]
        kind = prep.edit_kind(old, prompt)
        nodes, why = chain(store, base.get("session"))
        if nodes is not None and nodes[0].get("system_hash") != sys_hash:
            nodes, why = None, "style guide changed"
        elif nodes is not None and nodes[0].get("images") != manifest:
            nodes, why = None, "images changed"
        history = _attach([m for nd in nodes for m in nd.get("turns") or []], by_sha) if nodes else None
        if nodes and history is None:
            why = "images missing"
        if kind in ("same", "lists"):  # carried over in code, no model call, when it still validates
            patched = base["program"] if kind == "same" else prep.patch_lists(base["program"], old, prompt)
            if patched is not None:
                code = Turn(prompt=prompt, elaborate=elaborate, loras=loras, params=params, old=old)
                await asyncio.to_thread(code.settle, patched, "code")  # validates: off the event loop
                if code.accepted is not None:
                    turn, patch_kind = code, kind
                    # an empty node keeps the lineage's log; the next edit turn shows the program as it stands
                    node_id = node_for(base.get("session"), [], code.accepted.source) if history is not None else None
        if turn is None:
            user = {"role": "user", "content": EDIT_TURN.format(
                prompt=prep._numbered(prompt), changes=prep._describe_changes(prep.prompt_changes(old, prompt)),
                numbered=prep._numbered_program(base["program"]))}
            parent: Optional[str] = base.get("session")
            seed: List[Dict[str, Any]] = []
            if history is not None and estimate_tokens(history + [user]) > budget.history_cap:
                history, why = None, "context cap"
            if history is None:  # a new root, seeded with the program as it stands
                stats["reset"] = why
                parent, history = None, []
                seed = [system, user_message(old),
                        {"role": "assistant", "content": "", "tool_calls": [{"id": "seed", "type": "function", "function": {
                            "name": "write_program", "arguments": json.dumps({"source": base["program"]},
                                                                             ensure_ascii=False)}}]},
                        {"role": "tool", "tool_call_id": "seed", "name": "write_program",
                         "content": "Valid: the program is accepted.\nThe program now, with line numbers:\n"
                                    + prep._numbered_program(base["program"])}]
            turn = Turn(prompt=prompt, elaborate=elaborate, loras=loras, params=params, old=old, program=base["program"])
            added = seed + [user]
            messages = history + added
            await _converse(cfg, messages, added, turn, budget, calls_log, stats)
            if turn.start_over is not None:
                stats["start_over"] = turn.start_over
                log.info(f"[prompt-program] starting over: {turn.start_over}")
                base, turn = None, None
            else:
                patch_kind = "text"
                if turn.accepted is not None or turn.best is not None:
                    node_id = node_for(parent, added, (turn.accepted or turn.best).source)  # type: ignore[union-attr]

    if turn is None:  # a new prompt (or start over): a new root
        turn = Turn(prompt=prompt, elaborate=elaborate, loras=loras, params=params)
        added = [system, user_message(prompt)]
        await _converse(cfg, list(added), added, turn, budget, calls_log, stats)
        if turn.accepted is not None or turn.best is not None:
            node_id = node_for(None, added, (turn.accepted or turn.best).source)  # type: ignore[union-attr]

    chosen = turn.accepted or (turn.best if turn.best is not None and turn.best.runs else None)
    if chosen is None:
        if turn.best is not None:  # it runs, but would lose or garble the user's words
            log.info(f"[prompt-program] no program to keep after {budget.calls} call(s): "
                     f"{' '.join(turn.best.blocking)[:300]}")
            raise prep.PrepareFailed("\n".join(turn.best.problems))
        if budget.timed_out:
            raise prep.PrepareTimeout(f"Preparing took longer than {prep.prepare_limit():.0f} seconds, so it "
                                      "stopped. The chat model may be busy or too slow for this prompt.")
        raise prep.PrepareFailed(turn.last_error or "the writer wrote no program")
    if turn.accepted is None:
        log.info(f"[prompt-program] no valid program after {budget.calls} call(s): keeping the best one "
                 f"({len(chosen.problems)} problem(s) left: {' '.join(chosen.problems)[:300]})")
    entry = prep._entry(key=key, tool_id=tool_id, ctx=ctx, elaborate=elaborate, level=level, prompt=prompt,
                        enhanced="" if elaborate else prep.plain_example(prompt), exact=exact, source=chosen.source,
                        checked=chosen.checked, params=params, loras=loras)
    entry.update({
        "attempts": budget.calls, "repairs": turn.fixes, "protocol": "tools", "session": node_id,
        "lineage": (base.get("lineage") or base.get("key")) if base is not None else key,
        "seconds": round(time.monotonic() - started, 2), "upsample_seconds": round(styled_at - started, 2),
        "timing": {"enhance": round(styled_at - started, 2), "calls": calls_log},
        "session_stats": stats,
        # A program kept with problems that cost variety only (prepare.validate's blocking
        # ones never are): what's left, for the dev panel and the run's record.
        "problems": list(chosen.problems), "partial": bool(chosen.problems),
    })
    if base is not None:
        entry.update({"patched_from": base.get("key"), "patch": patch_kind})
    log.info(f"[prompt-program] prepared {key} in {entry['seconds']}s with {budget.calls} call(s) "
             f"{[c['kind'] for c in calls_log]} ({'edit of ' + str(base.get('key')) if base else 'new'}"
             f"{', reset: ' + stats['reset'] if stats['reset'] else ''})")
    return entry
