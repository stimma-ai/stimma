"""Prepare: turn a prompt into a program with the chat model (a write, and a repair or two
when the checks find problems), narrow its bound picks, then cache it.

Everything that shapes the program is part of its cache key, so asking again with the
same prompt, tool, LoRAs and parameters never calls the model. Realizing (running the
program for one generation) needs no model at all.
"""

from __future__ import annotations

import ast
from collections import Counter
import asyncio
import difflib
import json
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from core.logging import get_logger
from prompt_programs.runtime import (
    LoraInfo, ProgramError, RunResult, check, discover, extract_code, run, tidy_text,
)
from prompt_programs.draws import DrawAborted, analyze, draw, uses_draws
from prompt_programs.store import ProgramStore, program_key
from prompt_programs.vocab import vocabulary

log = get_logger(__name__)

PREPARE_VERSION = "pp-44"   # pp-44: judge, minors, words and agent branches merged
MAX_ATTEMPTS = 3
# A prepare that can't finish soon fails, so runs (and generate-forever lanes) waiting on
# it don't sit for minutes. Past the soft budget no new model call starts while a
# usable program is in hand; the hard limit stops everything.
PREPARE_SOFT_SECONDS = 30.0
PREPARE_LIMIT_SECONDS = 45.0


class StartOver(Exception):
    """The patch writer judged the new prompt a different prompt, not an edit: write it fresh."""


class PrepareTimeout(ProgramError):
    """Preparing took longer than PREPARE_LIMIT_SECONDS."""


class PrepareFailed(ProgramError):
    """The writer wrote no program that runs. The message is for the user; `problems` (what
    the checks told the writer) is for logs and the dev panel."""

    code = "program_failed"

    def __init__(self, problems: str = ""):
        super().__init__("The chat model couldn't prepare this prompt. Try again, or simplify the prompt.")
        self.problems = problems


class PromptTooLong(ProgramError):
    """A prompt (with its lists and segments expanded) or standing instructions too long to prepare."""

    code = "prompt_too_long"


# Inputs past these never reach the writer: a pasted essay would overflow its context, and
# every check runs over the program it writes.
MAX_PROMPT_CHARS = 8000
MAX_INSTRUCTIONS_CHARS = 4000


def writer_failure(e: BaseException) -> Optional[Exception]:
    """The error to report when the chat model itself failed to answer (unreachable, a
    provider rejection or 5xx, a broken stream, out of quota or balance), else None. Those
    are the chat model being unavailable, not a bug: the client offers Try again or Direct."""
    import httpx
    from llm_http import (ContentFilteredError, EntitlementError, LLMConnectionError, LLMStreamError,
                          QuotaExceededError)
    from llm_resolver import LLMInsufficientBalanceError, LLMUnavailableError

    if isinstance(e, ContentFilteredError):
        return PrepareFailed(f"the provider's content filter declined: {e}"[:300])
    if isinstance(e, EntitlementError):
        return LLMInsufficientBalanceError(str(e)[:300] or "No balance left for the chat model.")
    if isinstance(e, (LLMConnectionError, LLMStreamError, QuotaExceededError, httpx.HTTPError)):
        return LLMUnavailableError(str(e)[:300] or "The chat model didn't answer.")
    return None


# The vocabulary's catalogue (the lists a pick may bind to with cls=) is part of the
# instructions; the key carries a hash of them (with the style note and the model's guide).
_INSTRUCTIONS = (Path(__file__).parent / "instructions.md").read_text("utf-8").replace(
    "{vocabulary}", vocabulary().catalogue())



def _text_hash(guide: str) -> str:
    import hashlib
    return hashlib.sha256("\0".join([_INSTRUCTIONS, _STYLE_NOTE, guide]).encode("utf-8")).hexdigest()[:16]


# Schema parameters a program may vary when the user asks. Others (seed, sizes,
# media inputs, prompts, LoRAs) are never program-controlled.
_NEVER_PARAMS = {"seed", "prompt", "negative_prompt", "loras", "selected_loras", "width", "height",
                 "num_images", "batch_size", "image", "images", "mask", "mask_image", "input_images"}


# --------------------------------------------------------------------------- inputs

def expand_named_lists(prompt: str, wildcards: List[Dict[str, Any]], segments: List[Dict[str, Any]]) -> str:
    """{{name}} → the segment's text, or the wildcard's values as an inline {a|b|c} list,
    so the program sees the user's full list instead of one random value."""
    if not wildcards and not segments:
        return prompt
    lists = {str(w["name"]).lower(): [str(v) for v in (w.get("values") or [])] for w in wildcards}
    texts = {str(s["name"]).lower(): s.get("content", "") for s in segments}

    def repl(m: re.Match) -> str:
        key = m.group(1).strip().lower()
        if key in texts:
            return texts[key]
        values = lists.get(key)
        return "{" + "|".join(values) + "}" if values else m.group(0)

    return re.sub(r"\{\{([^{}]+)\}\}", repl, prompt)


def tool_param_specs(schema_props: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Numeric tool parameters a program may vary, with their limits."""
    out: Dict[str, Dict[str, Any]] = {}
    for name, spec in (schema_props or {}).items():
        if not isinstance(spec, dict) or name in _NEVER_PARAMS or name.startswith("_"):
            continue
        if spec.get("type") not in ("number", "integer") or spec.get("enum"):
            continue
        out[name] = {k: spec[k] for k in ("type", "minimum", "maximum", "default", "title") if k in spec}
    return out


def _words(s: str) -> Set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def match_loras(prompt: str, candidates: Sequence[LoraInfo]) -> List[LoraInfo]:
    """The LoRAs the prompt names. Looked up, never the whole list: a name matches when
    all its words appear in the prompt. If the prompt talks about LoRAs but names none,
    the model gets the candidates' names to choose from."""
    text = _words(prompt)
    named = [c for c in candidates if _words(c.name) and _words(c.name) <= text]
    if named:
        return named
    if re.search(r"\blora", prompt, re.I):
        return list(candidates)
    return []


# --------------------------------------------------------------------------- the model call

def _numbered(prompt: str) -> str:
    return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(prompt.splitlines()))


def build_user_message(prompt: str, model_name: Optional[str], mode: str,
                       params: Dict[str, Dict[str, Any]], loras: Sequence[LoraInfo], notes: Dict[str, str],
                       elaborate: bool = True, level: str = "") -> str:
    parts = [f"User's prompt (lines numbered):\n{_numbered(prompt)}", ""]
    smart = smart_wildcards(prompt)
    if level == "fill":
        parts.append("Write the program, keeping the user's words: emit their prompt as written, with only what the "
                     "style guide says the model needs, joined into readable text. Seeds you write are short phrases "
                     "(a few words) in the same register as the user's words. Add no extra picks (no added=True).")
    elif elaborate:
        parts.append(f"Write the program. What it emits is the prompt {model_name or 'the image model'} reads: "
                     "write it the way the style guide says, complete and rich, with a pick wherever the "
                     "image should vary.")
    else:
        parts.append("Write the program, keeping the user's words: emit their prompt as written, joined into "
                     "readable text with nothing added. Seeds you write are short phrases (a few words) in the "
                     "same register as the user's words. Add no extra picks (no added=True).")
        if mode == "keyword":
            parts.append("This model reads comma-separated tags: emit tags, and write seeds as tags.")
    parts.append("")
    lines = prompt.splitlines()

    def line_of(text: str) -> int:
        return next((i + 1 for i, ln in enumerate(lines) if text in ln), 1)
    if smart:
        parts.append("Smart wildcards, each a pick with about= in the user's words and 1 to 3 concrete seeds (never a "
                     "list of options), its variable emitted where the wildcard stands:")
        for n in smart:
            parts.append(f'- {{{{{n}}}}}: {smart_id(n)} = pick("{smart_id(n)}", about="{n}", seed=[<1 to 3 examples>], '
                         f'label=<one or two words>, phase=<N>, line={line_of("{{" + n)})')
        parts.append('Each wildcard\'s pick has exactly the id shown; one drawn per person ends with it '
                     '(f"friends[{i+1}].<id>").')
        parts.append("")
    lists = list(dict.fromkeys(m.group(1) for m in _INLINE_LIST.finditer(prompt)))
    if lists:
        parts.append("User lists, each a list pick with exactly its items, its variable itself emitted where the list "
                     "stands:" if len(lists) > 1 else
                     "User list: a list pick with exactly its items, its variable itself emitted where the list stands:")
        for raw in lists:
            items = ", ".join(json.dumps(o.strip(), ensure_ascii=False) for o in raw.split("|"))
            parts.append(f'- {{{raw}}}: pick(<id>, [{items}], label=<one or two words>, source="list", phase=<N>, '
                         f'line={line_of("{" + raw + "}")})')
        parts.append("A detail that must suit the drawn item (the light for a time of day, the outfit for a job) "
                     "names that list in its about with an f-string. If a list fills several places (two people in "
                     "different {red|blue} coats), each place is its own pick of it, each later one with exclude=[the "
                     "earlier ones].")
        if len(lists) > 1:
            parts.append("If one of these lists must fit another (clothes that suit the job, a tool for the trade), "
                         "that list goes in a later phase than the one it fits.")
        parts.append("")
    for n in sorted(_comment_lines(prompt)):
        parts.append(f"Line {n} is an instruction to you, not prompt text. A pick it asks for has line={n}. If it says "
                     "to keep something the same, that thing stays fixed text, with no pick.")
    if _comment_lines(prompt):
        parts.append("")
    if params:
        desc = ", ".join(
            f"{n} ({p.get('minimum', '?')}–{p.get('maximum', '?')})" for n, p in sorted(params.items()))
        parts.append(f"Parameters you may vary, only when the prompt asks: {desc}.")
    else:
        parts.append("This tool has no parameters you may vary.")
    if loras:
        parts.append("LoRAs the user may want chosen per image with pick_lora (only if their prompt asks to "
                     "choose LoRAs). A name goes only in pick_lora([...]), never in emit(): LoRAs work by being "
                     "on, and the trigger words of the one picked are added to the prompt for you.")
        for lo in loras:
            words = ", ".join(f'"{t.strip()}"' for t in lo.trigger.split(",") if t.strip()) or "none"
            parts.append(f'- "{lo.name}" (trigger words: {words}; notes: {notes.get(lo.name) or "none"})')
    else:
        parts.append("No LoRAs to choose among: don't use pick_lora.")
    return "\n".join(parts)


def plain_example(prompt: str) -> str:
    """The user's text without its # lines, with the varying spots protected."""
    lines = [ln for ln in prompt.splitlines() if not ln.lstrip().startswith("#")]
    return protect_variable_spots("\n".join(lines).strip())


def protect_variable_spots(prompt: str) -> str:
    """{{name}} and inline {a|b} become protected placeholders, so the enhancer writes the
    rich text around them and leaves them where they are."""
    s = re.sub(r"\{\{([^{}]+)\}\}", lambda m: "[{{" + m.group(1) + "}}]", prompt)
    return re.sub(r"(?<![\[{])\{([^{}]+\|[^{}]+)\}(?![}\]])", lambda m: "[{" + m.group(1) + "}]", s)


async def _ask_model(messages: List[Dict[str, Any]], project_id: Optional[int], max_tokens: int = 4096) -> str:
    from llm import llm_complete_text
    from llm_correlation import llm_correlation_context
    from llm_resolver import get_effective_llm_config

    cfg = await get_effective_llm_config("tool_assistant", project_id)
    with llm_correlation_context("prompt-program"):
        return await llm_complete_text(config=cfg, messages=messages, max_tokens=max_tokens, temperature=0.3)


_STYLE_NOTE = """

# The image model's prompt style

The text your program emits is the prompt the image model reads. Write it the way the guide
below says. The guide was written for rewriting one prompt; here it applies to every prompt
your program emits, with picks in place of what varies. Its rules about how to reply don't
apply: you reply with the program.

"""


async def writer_style(prompt: str, ctx: Dict[str, Any], instructions: str, lora_context: List[Dict[str, Any]],
                       project_id: Optional[int], profile_id: Optional[str],
                       level: str = "expand") -> Tuple[str, List[Tuple[int, str]]]:
    """This model's prompt-style guide (the enhancer's per-model guidance, with this
    request's images, canvas, protected text and LoRAs filled in) and the source images it
    refers to. No model call."""
    from database_registry import get_database_registry
    from routes.prompt_enhancement import ImprovePromptRequest, style_guide

    request = ImprovePromptRequest(prompt=prompt, instructions=instructions or None, model=ctx.get("model") or None,
                                   project_id=project_id, lora_context=lora_context or [], **(ctx.get("enhance") or {}))
    db = get_database_registry().get_database(profile_id)
    async with db.async_session_maker() as session:
        guide, images, _mode = await style_guide(request, session, fill=(level == "fill"), exact_canvas=False)
    return guide, images


def writer_messages(prompt: str, guide: str, images: Sequence[Tuple[int, str]], model_name: Optional[str], mode: str,
                    params: Dict[str, Dict[str, Any]], loras: Sequence[LoraInfo], notes: Dict[str, str],
                    elaborate: bool, instructions: str = "", level: str = "") -> List[Dict[str, Any]]:
    system = _INSTRUCTIONS + (_STYLE_NOTE + guide.strip() if guide else "")
    user = build_user_message(prompt, model_name, mode, params, loras, notes, elaborate, level)
    if instructions.strip():
        user += f"\n\nThe user's standing instructions for prompts: {instructions.strip()}"
    if images:
        content: Any = [{"type": "text", "text": user}]
        for n, b64 in images:
            content += [{"type": "text", "text": f"Image {n}:"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]
    else:
        content = user
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


async def _ask_in_time(messages: List[Dict[str, Any]], project_id: Optional[int], started: float,
                       max_tokens: int = 4096) -> str:
    """A text-protocol writer call bounded by what's left of the prepare's deadline. Raises
    asyncio.TimeoutError when it runs out, so the caller can keep the best program it has
    (the outer wait_for in _prepare would throw it away)."""
    left = PREPARE_LIMIT_SECONDS - (time.monotonic() - started)
    if left <= 0:
        raise asyncio.TimeoutError
    return await asyncio.wait_for(_ask_model(messages, project_id, max_tokens=max_tokens), left)


# What checking a written program can trip on besides ProgramError (a program the checks
# themselves fail on): a problem to report, never a crash. As the session's Turn.settle.
_CHECK_ERRORS = (ProgramError, RecursionError, ValueError, TypeError, KeyError, IndexError)


def _check_error(e: BaseException) -> str:
    if isinstance(e, ProgramError):
        return str(e)
    log.warning(f"[prompt-program] validating a written program failed: {type(e).__name__}: {e}")
    return f"The program couldn't be run: {type(e).__name__}: {e}"


# --------------------------------------------------------------------------- validation

_VERBATIM = re.compile(r"\[([^\[\]]+)\]")
_INLINE_LIST = re.compile(r"(?<!\{)\{([^{}]+\|[^{}]+)\}(?!\})")


_SMART = re.compile(r"\{\{([^{}]+)\}\}")


def smart_wildcards(prompt: str) -> List[str]:
    """{{name}}s left after global wildcards and segments expanded: the user wants these
    to vary and the program writes their options."""
    return list(dict.fromkeys(m.group(1).strip() for m in _SMART.finditer(prompt) if m.group(1).strip()))


def smart_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "choice"


_PERSON_DETAIL = re.compile(r"^[A-Za-z_]\w*\[\d+\]\.(.+)$")


def is_wildcard_id(pick_id: str, name: str) -> bool:
    """A pick holds the smart wildcard {{name}} when its id says so: exactly smart_id(name),
    or, one per person, a person's detail of that id (friends[2].winter_hat). Nothing else
    (its label or about) decides it."""
    want = smart_id(name)
    m = _PERSON_DETAIL.match(str(pick_id))
    return str(pick_id) == want or (m is not None and m.group(1) == want)


def _smart_choices(info: Dict[str, Any], name: str) -> List[Dict[str, Any]]:
    return [c for c in info["choices"] if c["kind"] == "pick" and is_wildcard_id(c["id"], name)]


def _smart_choice(info: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    got = _smart_choices(info, name)
    return got[0] if got else None


def _smart_missing(name: str, info: Dict[str, Any]) -> str:
    """The repair note for a {{wildcard}} no pick's id names."""
    want = smart_id(name)
    groups = [g.get("id") for g in info.get("groups") or [] if g.get("id")]
    per_person = (f' Inside a loop over {groups[0]}, one per person: pick(f"{groups[0]}[{{i+1}}].{want}", ...).'
                  if groups else "")
    return (f'{{{{{name}}}}} is a smart wildcard, but no pick has the id "{want}". Write it as pick("{want}", '
            f'about=..., seed=[1 to 3 examples], label=<one or two words>, phase=..., line=...) with exactly that id, '
            f"and emit its value where {{{{{name}}}}} stands. If a pick of yours already stands for it under another id, "
            f'rename that pick to "{want}".' + per_person)


def _bare(text: str) -> str:
    """A phrase without case, extra spaces or surrounding punctuation: "Brand." is the
    wildcard {{brand}}'s own name, not an example of it."""
    return re.sub(r"\s+", " ", str(text).strip().lower()).strip(" .,;:!\"'")


def is_name_of(option: str, name: str) -> bool:
    """The option is the wildcard's own name, as written (case, spacing and surrounding
    punctuation aside)."""
    return _bare(option) == _bare(name)


def drop_name_options(source: str, prompt: str) -> str:
    """Weak models list a descriptive {{name}} itself as an option ("35mm details, no
    shallow dof"). Cut those strings out of the pick's option list, keeping the rest of
    the source as written."""
    names = {smart_id(n): n.lower() for n in smart_wildcards(prompt)}
    if not names:
        return source
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    pos = _offsets(source)
    cuts = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "pick" and node.args
                and isinstance(node.args[0], ast.Constant) and node.args[0].value in names):
            continue
        lists = [node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "options"), None),
                 next((k.value for k in node.keywords if k.arg == "seed"), None)]
        name = names[node.args[0].value]
        for opts, least in zip(lists, (2, 1)):  # an option list keeps two, a seed list one
            if not isinstance(opts, ast.List):
                continue
            keep = [e for e in opts.elts if not (isinstance(e, ast.Constant) and is_name_of(str(e.value), name))]
            if len(keep) < least or len(keep) == len(opts.elts):
                continue
            for i, e in enumerate(opts.elts):
                if e in keep:
                    continue
                start = pos(e.lineno, e.col_offset)
                # through the following comma (or back to the preceding one for the last element)
                nxt = opts.elts[i + 1] if i + 1 < len(opts.elts) else None
                end = pos(nxt.lineno, nxt.col_offset) if nxt else pos(e.end_lineno, e.end_col_offset)
                cuts.append((start, end))
    for start, end in sorted(cuts, reverse=True):
        source = source[:start] + source[end:]
    return source


def _offsets(source: str):
    """(lineno, ast col) → index into source. ast columns count UTF-8 bytes."""
    lines = source.splitlines(keepends=True)
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln))

    def pos(lineno: int, col: int) -> int:
        return starts[lineno - 1] + len(lines[lineno - 1].encode()[:col].decode("utf-8", "ignore"))
    return pos


def fix_phases(source: str) -> Tuple[str, List[str]]:
    """Repair phases in place instead of sending the program back: a pick with no
    phase= gets phase 1, and a pick that uses another pick's value (by=, an if test, a
    lookup, a loop count, its arguments) moves to a later phase than it, as the
    dependency rule requires. Returns the source and what changed; anything it can't
    settle (a pick that uses its own value, a cycle) is left for validation to report."""
    from prompt_programs.draws import _Analyzer

    if not uses_draws(source):
        return source, []
    try:
        tree = check(source)
        an = _Analyzer(tree)
        for _ in range(50):  # the same fixed point analyze() runs
            an.changed = False
            for s in an.sites:
                s.deps.clear()
                s.exclude_deps.clear()
            an.block(tree.body, [])
            if not an.changed:
                break
    except (ProgramError, RecursionError):
        return source, []
    calls = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and id(node) in an.site_of:
            calls[an.site_of[id(node)]] = node
    written: Dict[int, Optional[ast.AST]] = {}
    phase: Dict[int, int] = {}
    for i, node in calls.items():
        kw = next((k for k in node.keywords if k.arg == "phase"), None)
        written[i] = kw.value if kw else None
        ok = kw is not None and isinstance(kw.value, ast.Constant) and type(kw.value.value) is int and kw.value.value >= 1
        if kw is not None and not ok:
            return source, []  # a phase that isn't a number: validation says how to write it
        phase[i] = kw.value.value if ok else 1
    for s in an.sites:
        if s.index in s.deps:
            return source, []
    for _ in range(len(an.sites) + 1):
        moved = False
        for s in an.sites:
            need = max([phase[s.index]] + [phase[d] + 1 for d in s.deps] + [phase[d] for d in s.exclude_deps])
            if need != phase[s.index]:
                phase[s.index], moved = need, True
        if not moved:
            break
    else:
        return source, []  # a cycle
    pos = _offsets(source)
    edits: List[Tuple[int, int, str]] = []
    notes: List[str] = []
    for i, node in calls.items():
        site = an.sites[i]
        kw_value = written[i]
        if site.kind != "pick" and kw_value is None and phase[i] == 1:
            continue  # pick_lora defaults to phase 1
        if kw_value is None:
            end = pos(node.end_lineno, node.end_col_offset) - 1  # the closing parenthesis
            j = end - 1
            while j > 0 and source[j].isspace():
                j -= 1
            edits.append((end, end, f"{' ' if source[j] == ',' else ', '}phase={phase[i]}"))
            notes.append(f'pick("{site.id_text}"): phase={phase[i]} added')
        elif kw_value.value != phase[i]:  # type: ignore[attr-defined]
            start, end = pos(kw_value.lineno, kw_value.col_offset), pos(kw_value.end_lineno, kw_value.end_col_offset)
            edits.append((start, end, str(phase[i])))
            notes.append(f'pick("{site.id_text}"): phase {kw_value.value} → {phase[i]}')  # type: ignore[attr-defined]
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source, notes


_BARE_TEXT = re.compile(r"(?<=,)(\s+)([A-Za-z][^\",()\[\]{}]*?\")")


def _parses_past(candidate: str, lineno: int) -> bool:
    """The candidate parses, or its first syntax error is past `lineno`."""
    try:
        ast.parse(candidate)
        return True
    except SyntaxError as again:
        return bool(again.lineno and again.lineno > lineno)


def fix_quotes(source: str) -> Tuple[str, List[str]]:
    """Syntax slips weak writers make, put right where the parser shows exactly what broke,
    each kept only if the syntax error goes away (or moves past that line):
    - a quote dropped between emit() parts: `",", resting its hands atop", desk`;
    - a string wrapped onto the next line (`"...shallow depth of field,` / `emphasizing..."`):
      the lines are joined with a space;
    - a comment wrapped onto a line without its `#`."""
    notes: List[str] = []
    for _ in range(8):
        try:
            ast.parse(source)
            return source, notes
        except SyntaxError as e:
            lines = source.split("\n")
            if e.lineno and "unterminated string literal" in (e.msg or "") and e.lineno < len(lines):
                n = e.lineno - 1
                for k in range(1, min(4, len(lines) - n)):  # wrapped over up to 3 more lines
                    joined = " ".join([lines[n].rstrip()] + [ln.strip() for ln in lines[n + 1:n + 1 + k]])
                    candidate = "\n".join(lines[:n] + [joined] + lines[n + 1 + k:])
                    if _parses_past(candidate, n + 1):
                        source = candidate
                        notes.append(f"a string wrapped over lines {n + 1}-{n + 1 + k} joined onto one line")
                        break
                else:
                    k = 0
                if k:
                    continue
            if e.lineno and e.lineno > 1:
                n = e.lineno - 1
                prev = next((ln for ln in reversed(lines[:n]) if ln.strip()), "")
                if prev.lstrip().startswith("#") and not lines[n].lstrip().startswith("#"):
                    candidate = "\n".join(lines[:n] + ["# " + lines[n].strip()] + lines[n + 1:])
                    if _parses_past(candidate, n + 1):
                        source = candidate
                        notes.append(f"comment text on line {n + 1} marked as a comment")
                        continue
            if not e.lineno or "emit(" not in source:
                return source, notes
            n = e.lineno - 1
            while n > 0 and "emit(" not in lines[n]:  # the error may surface on a continuation line
                n -= 1
            if "emit(" not in lines[n]:  # no emit() above the error: nothing of this kind to put right
                return source, notes
            line = lines[n]
            tries = [_BARE_TEXT.sub(lambda m: m.group(1) + '"' + m.group(2), line)]
            tries += [line[:m.start(2)] + '"' + line[m.start(2):] for m in _BARE_TEXT.finditer(line)]
            for fixed in dict.fromkeys(t for t in tries if t != line):
                candidate = "\n".join(lines[:n] + [fixed] + lines[n + 1:])
                try:
                    ast.parse(candidate)
                except SyntaxError as again:
                    if not again.lineno or again.lineno <= n + 1:
                        continue
                source = candidate
                notes.append(f"a missing quote put back on line {n + 1}")
                break
            else:
                return source, notes
    return source, notes


def fix_unplaced(source: str) -> Tuple[str, List[str]]:
    """A pick the program never uses does nothing. When its first seed still stands in
    emit()'s fixed text (the writer forgot to swap it in), the pick goes there; a hidden
    one, or variety the writer added (added=True), whose seed stands nowhere is dropped and
    the text stays as written: nobody asked for it, so the program is whole without it."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, []
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    texts = [a for c in ast.walk(tree) if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "emit"
             for a in c.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    pos = _offsets(source)
    lines = source.splitlines(keepends=True)
    edits: List[Tuple[int, int, str]] = []
    notes: List[str] = []
    for st in tree.body:
        if not (isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name)
                and isinstance(st.value, ast.Call) and getattr(st.value.func, "id", None) == "pick"
                and st.targets[0].id not in used):
            continue
        var = st.targets[0].id
        seed = next((k.value for k in st.value.keywords if k.arg == "seed"), None)
        if not isinstance(seed, ast.List):
            continue  # a user list or written options: the writer has to place it
        first = seed.elts[0].value if seed.elts and isinstance(seed.elts[0], ast.Constant) else None
        holders = [a for a in texts if isinstance(first, str) and len(first.split()) >= 2
                   and a.value.lower().count(first.lower()) == 1]
        if len(holders) == 1:
            arg = holders[0]
            at = arg.value.lower().index(first.lower())
            before, after = arg.value[:at], arg.value[at + len(first):]
            parts = [json.dumps(before, ensure_ascii=False)] if before.strip() else []
            parts.append(var)
            if after.strip():
                parts.append(json.dumps(after, ensure_ascii=False))
            edits.append((pos(arg.lineno, arg.col_offset), pos(arg.end_lineno, arg.end_col_offset), ", ".join(parts)))
            texts.remove(arg)
            notes.append(f"{var} placed where its seed stood")
        elif any(k.arg in ("hidden", "added") and isinstance(k.value, ast.Constant) and k.value.value is True
                 for k in st.value.keywords) and not any(
                isinstance(first, str) and first.lower() in a.value.lower() for a in texts):
            # only a hidden or added detail: a choice the user asked for goes back to the writer
            start = sum(len(ln) for ln in lines[: st.lineno - 1])
            end = sum(len(ln) for ln in lines[: st.end_lineno])
            if source[start:end].strip() == ast.get_source_segment(source, st):  # the statement has its lines to itself
                edits.append((start, end, ""))
                notes.append(f"{var} dropped: never used")
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source, notes


# --------------------------------------------------------------------------- program helpers


def _comment_lines(prompt: str) -> Set[int]:
    return {i + 1 for i, ln in enumerate(prompt.splitlines()) if ln.lstrip().startswith("#")}


def _kw(node: ast.Call, name: str) -> Optional[ast.AST]:
    return next((k.value for k in node.keywords if k.arg == name), None)


def _const(node: Optional[ast.AST]) -> Any:
    return node.value if isinstance(node, ast.Constant) else None


def _pick_assigns(tree: ast.AST) -> List[Tuple[Optional[str], ast.Call]]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", None) == "pick":
            var = node.targets[0].id if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) else None
            out.append((var, node.value))
    return out


def fix_brackets(source: str) -> Tuple[str, List[str]]:
    """The placeholder's brackets copied around a pick: emit("A [", job, "] at work")
    would write "A [ nurse ] at work". The brackets go; the pick stays."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, []
    pos = _offsets(source)
    # A literal between two bracketed picks ("] in [") loses both ends: its cuts are
    # gathered first, then it is rewritten once.
    cuts: Dict[int, Tuple[ast.Constant, Set[str]]] = {}
    pairs = 0
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and getattr(call.func, "id", None) == "emit"):
            continue
        a = call.args
        for i in range(1, len(a) - 1):
            before, after = a[i - 1], a[i + 1]
            if not (isinstance(a[i], ast.Name) and isinstance(before, ast.Constant) and isinstance(before.value, str)
                    and isinstance(after, ast.Constant) and isinstance(after.value, str)):
                continue
            if before.value.rstrip().endswith("[") and after.value.lstrip().startswith("]"):
                cuts.setdefault(id(before), (before, set()))[1].add("tail")
                cuts.setdefault(id(after), (after, set()))[1].add("head")
                pairs += 1
    if not cuts:
        return source, []
    edits: List[Tuple[int, int, str]] = []
    for node, ends in cuts.values():
        text = str(node.value)
        if "head" in ends:
            text = " " + text.lstrip()[1:].lstrip()
        if "tail" in ends:
            text = text.rstrip()[:-1].rstrip() + " "
        edits.append((pos(node.lineno, node.col_offset), pos(node.end_lineno, node.end_col_offset),
                      json.dumps(text, ensure_ascii=False)))
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source, [f"{pairs} placeholder bracket pair(s) taken out of emit()"]


def fix_generated_refs(source: str) -> Tuple[str, List[str]]:
    """A pick whose about= names a pick written with about= (f"what {age_1} wears"):
    that pick gets new values as it is used, so naming it would need a pool per value.
    Its own description takes its place, in brackets like the other varying spots the
    option writer sees ("what [the first friend's age] wears"); the judge still checks
    the drawn value against it."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, []
    described: Dict[str, str] = {}
    for var, call in _pick_assigns(tree):
        about = _const(_kw(call, "about"))
        if var and isinstance(about, str) and about.strip() and _const(_kw(call, "source")) != "list":
            described[var] = about.strip()
    if not described:
        return source, []
    pos = _offsets(source)
    edits: List[Tuple[int, int, str]] = []
    notes: List[str] = []
    for _, call in _pick_assigns(tree):
        about = _kw(call, "about")
        if not isinstance(about, ast.JoinedStr):
            continue
        hits = [v for v in about.values if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name)
                and v.value.id in described and v.conversion == -1 and v.format_spec is None]
        if not hits:
            continue
        text, live = "", False
        for v in about.values:
            if isinstance(v, ast.Constant):
                text += str(v.value).replace("{", "{{").replace("}", "}}")
            elif v in hits:
                text += "[" + described[v.value.id].replace("{", "{{").replace("}", "}}") + "]"  # type: ignore[attr-defined]
            elif isinstance(v, ast.FormattedValue) and v.conversion == -1 and v.format_spec is None:
                text += "{" + ast.unparse(v.value) + "}"
                live = True
            else:
                break
        else:
            literal = ("f" + json.dumps(text, ensure_ascii=False)) if live else json.dumps(
                text.replace("{{", "{").replace("}}", "}"), ensure_ascii=False)
            edits.append((pos(about.lineno, about.col_offset), pos(about.end_lineno, about.end_col_offset), literal))
            notes.append(f"about= of {_const(call.args[0]) if call.args else '?'} describes "
                         + ", ".join(sorted({h.value.id for h in hits})) + " instead of naming it")  # type: ignore[attr-defined]
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source, notes


def fix_requested(source: str, prompt: str) -> Tuple[str, List[str]]:
    """What the user asked to vary is a choice they see: a pick from a # line loses
    hidden=True and added=True. A group() whose count nothing loops over is dropped."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, []
    comments = _comment_lines(prompt)
    pos = _offsets(source)
    edits: List[Tuple[int, int, str]] = []
    notes: List[str] = []
    for var, call in _pick_assigns(tree):
        if _const(_kw(call, "line")) not in comments:
            continue
        parts = [*call.args, *call.keywords]
        for i, k in enumerate(parts):
            if isinstance(k, ast.keyword) and k.arg in ("hidden", "added") and _const(k.value) is True and i > 0:
                prev = parts[i - 1]
                edits.append((pos(prev.end_lineno, prev.end_col_offset), pos(k.end_lineno, k.end_col_offset), ""))
                notes.append(f'pick("{_const(call.args[0]) if call.args else var}"): {k.arg}=True dropped, the user asked to vary it')
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    lines = source.splitlines(keepends=True)
    for st in tree.body:
        call = st.value if isinstance(st, (ast.Assign, ast.Expr)) else None
        if not (isinstance(call, ast.Call) and getattr(call.func, "id", None) == "group"):
            continue
        if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id in used for t in st.targets):
            continue
        start = sum(len(ln) for ln in lines[: st.lineno - 1])
        end = sum(len(ln) for ln in lines[: st.end_lineno])
        if source[start:end].strip() == ast.get_source_segment(source, st):
            edits.append((start, end, ""))
            notes.append("a group() nothing loops over dropped")
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source, notes


def fix_duplicates(source: str, prompt: str = "") -> Tuple[str, List[str]]:
    """A pick's seed phrase left in emit()'s fixed text while the same emit() also passes
    the pick says it twice, and contradicts every other value the pick draws: cut the
    fixed copy. Returns the source and what changed."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, []
    seeds: Dict[str, List[str]] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", None) == "pick"):
            seed = next((k.value for k in node.value.keywords if k.arg == "seed"), None)
            if isinstance(seed, ast.List):
                seeds[node.targets[0].id] = [str(e.value).strip() for e in seed.elts if isinstance(e, ast.Constant)
                                             and isinstance(e.value, str) and len(e.value.split()) >= 2]
    pos = _offsets(source)
    edits: List[Tuple[int, int, str]] = []
    notes: List[str] = []
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and getattr(call.func, "id", None) == "emit"):
            continue
        passed = [a.id for a in call.args if isinstance(a, ast.Name) and a.id in seeds]
        for arg in call.args:
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                continue
            text = arg.value
            for var in passed:
                for phrase in seeds[var]:
                    at = text.lower().find(phrase.lower())
                    before, after = text[:at].rstrip(), text[at + len(phrase):].lstrip()
                    # only a phrase that stands alone between punctuation: cutting one mid-clause
                    # ("glints under the dramatic light") would leave the sentence broken
                    if at >= 0 and (not before or before[-1] in ",.;:") and (not after or after[0] in ",.;:"):
                        text = text[:at] + text[at + len(phrase):]
                        notes.append(f'"{phrase}" cut from the fixed text: {var} says it')
            if text != arg.value:
                text = re.sub(r"\s{2,}", " ", text)
                edits.append((pos(arg.lineno, arg.col_offset), pos(arg.end_lineno, arg.end_col_offset),
                              json.dumps(text, ensure_ascii=False)))
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source, notes


def fix_list_sources(source: str, prompt: str) -> Tuple[str, List[str]]:
    """A user list the writer made into picks without source="list" ("two girls in
    different colored {red|blue|green} bodysuits" as two picks): mark each source="list",
    and give the second and later picks of the same list exclude= of the earlier ones,
    so one list can fill several places with different values. Returns the source and
    what changed."""
    written = [tuple(o.strip() for o in m.group(1).split("|")) for m in _INLINE_LIST.finditer(prompt)]
    if not written:
        return source, []
    lists = [list(t) for t in dict.fromkeys(written)]
    times = {t: written.count(t) for t in written}  # how often the prompt writes each list
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, []
    pos = _offsets(source)
    edits: List[Tuple[int, int, str]] = []
    notes: List[str] = []
    taken: Dict[int, List[str]] = {}  # list index -> variables of its picks so far
    holders = {i: 0 for i in range(len(lists))}
    for st in tree.body:  # count first: exclusions only when picks outnumber the places written
        call = st.value if isinstance(st, ast.Assign) else None
        if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "pick":
            opts = call.args[1] if len(call.args) > 1 else next((k.value for k in call.keywords if k.arg == "options"), None)
            if isinstance(opts, ast.List):
                vals = [str(e.value).strip() for e in opts.elts if isinstance(e, ast.Constant)]
                idx = next((i for i, lst in enumerate(lists) if lst == vals), None)
                if idx is not None:
                    holders[idx] += 1
    for st in tree.body:  # top-level `name = pick(...)` only: order and scope are plain there
        if not (isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name)
                and isinstance(st.value, ast.Call) and getattr(st.value.func, "id", None) == "pick"):
            continue
        call, var = st.value, st.targets[0].id
        opts = call.args[1] if len(call.args) > 1 else next((k.value for k in call.keywords if k.arg == "options"), None)
        if not (isinstance(opts, ast.List) and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in opts.elts)):
            continue
        values = [str(e.value).strip() for e in opts.elts]
        idx = next((i for i, lst in enumerate(lists) if lst == values), None)
        if idx is None:
            continue
        add: List[str] = []
        src = next((k for k in call.keywords if k.arg == "source"), None)
        if src is None:
            add.append('source="list"')
        elif not (isinstance(src.value, ast.Constant) and src.value.value == "list"):
            edits.append((pos(src.value.lineno, src.value.col_offset), pos(src.value.end_lineno, src.value.end_col_offset), '"list"'))
        if src is None or not (isinstance(src.value, ast.Constant) and src.value.value == "list"):
            notes.append(f"{var} marked as the user's list")
        earlier = taken.setdefault(idx, [])
        # "{red|blue} car next to a {red|blue} bike" writes the list twice: two free draws.
        # One list written once but held by several picks is one list filling several places.
        # Only when the prompt writes the list once: with copies elsewhere ("coats in
        # different {red|blue}" beside "a {red|blue} car") which picks share it is a guess.
        shared = times[tuple(lists[idx])] == 1 and holders[idx] > 1
        if shared and earlier and not any(k.arg == "exclude" for k in call.keywords) and len(earlier) < len(values):
            add.append(f"exclude=[{', '.join(earlier)}]")
            notes.append(f"{var} draws from the same list as {', '.join(earlier)}: a different value")
        earlier.append(var)
        if add:  # right after the last argument: a trailing comma or comment after it stays valid
            last = max([*call.args, *(k.value for k in call.keywords)], key=lambda n: (n.end_lineno, n.end_col_offset))
            end = pos(last.end_lineno, last.end_col_offset)
            edits.append((end, end, ", " + ", ".join(add)))
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source, notes


def fix_one_item_lists(source: str, prompt: str = "") -> Tuple[str, List[str]]:
    """pick(id, ["lilacs"], ...) draws "lilacs" every time: the writer keeping a word the user
    stated. It is fixed text, so the call becomes that string. (A user's {a|b} list always has
    two items or more.) A {{wildcard}} written that way is broken, not fixed: validation sends it
    back."""
    wild = {smart_id(n): n for n in smart_wildcards(prompt)}
    if not uses_draws(source):
        return source, []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, []
    pos = _offsets(source)
    edits: List[Tuple[int, int, str]] = []
    notes: List[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "pick" and len(node.args) > 1):
            continue
        opts = node.args[1]
        if not (isinstance(opts, ast.List) and len(opts.elts) == 1 and isinstance(opts.elts[0], ast.Constant)
                and isinstance(opts.elts[0].value, str)) or _kw(node, "about") is not None or _kw(node, "seed") is not None:
            continue
        pid = str(_const(node.args[0]) or "")
        if any(is_wildcard_id(pid, n) for n in wild.values()) or any(is_name_of(opts.elts[0].value, n) for n in wild.values()):
            continue
        edits.append((pos(node.lineno, node.col_offset), pos(node.end_lineno, node.end_col_offset),
                      json.dumps(opts.elts[0].value, ensure_ascii=False)))
        notes.append(f'pick("{_const(node.args[0])}") of one item made fixed text')
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source, notes


_EXACT = re.compile(r"\[([^\[\]{}][^\[\]]*)\]")


def mask_exact(prompt: str) -> Tuple[str, Dict[str, str]]:
    """[exact text] is the user's, untouched: no model ever reads it. Each becomes a
    token like [EXACT_1] for every model step, and realize() puts the text back."""
    exact: Dict[str, str] = {}

    def repl(m: re.Match) -> str:
        token = f"EXACT_{len(exact) + 1}"
        exact[token] = m.group(1)
        return f"[{token}]"

    return _EXACT.sub(repl, prompt), exact


def unmask_exact(text: str, exact: Dict[str, str]) -> str:
    """Put the user's text back, still in [brackets]: later steps (Translate) keep
    bracketed text untouched, and the final cleanup removes the brackets."""
    for token, original in sorted((exact or {}).items(), key=lambda kv: -len(kv[0])):  # EXACT_10 before EXACT_1
        text = text.replace(f"[{token}]", token).replace(token, f"[{original}]")
    return text


def _verbatim_segments(prompt: str) -> List[str]:
    return [m.group(1).strip() for m in _VERBATIM.finditer(prompt) if m.group(1).strip()]


def realized_text(prompt: str) -> str:
    """What the image model would see (protected text unwrapped)."""
    return re.sub(r"\s+", " ", _VERBATIM.sub(lambda m: m.group(1), prompt)).strip()


def _emitted_in(value: str, text: str) -> bool:
    """A drawn value is in the (lowercased) emitted prompt as written, or as the prompt's tidy
    writes it: a filled "a {main} coat" reads "an olive coat" there (runtime.tidy_text)."""
    v = value.lower()
    return v in text or tidy_text([value]).lower() in text


def _mentions(text: str, name: str) -> bool:
    return re.search(rf"(?i)(?<![\w]){re.escape(name)}(?![\w])", text) is not None


def _tidy_cut(text: str) -> str:
    """Text with a phrase cut out: no doubled commas or spaces left where it stood."""
    text = re.sub(r"\s*,(\s*,)+", ",", text)
    text = re.sub(r"\s+([,.])", r"\1", text)
    text = re.sub(r",([.;:!?])", r"\1", text)
    text = re.sub(r"^\s*,\s*|\s*,\s*$", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def fix_trigger_words(source: str, loras: Sequence[LoraInfo], prompt: str) -> Tuple[str, List[str]]:
    """The trigger words of the LoRA a pick_lora draws are added for it. A program that writes
    them too (a lookup from the LoRA's name to its trigger words, or the words in emit()) would
    put them in twice: they are cut from the program's text. Only exact trigger words of LoRAs it
    chooses among, and never ones the user wrote."""
    triggers = []
    for lo in loras:
        for t in (lo.trigger or "").split(","):
            t = t.strip()
            if len(t) > 2 and not _mentions(prompt, t):
                triggers.append(t)
    if not triggers or "pick_lora" not in source:
        return source, []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, []
    if not any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == "pick_lora" for n in ast.walk(tree)):
        return source, []
    texts: List[ast.Constant] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            texts += [v for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
        elif isinstance(node, ast.Call) and getattr(node.func, "id", None) == "emit":
            texts += [a for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    pos = _offsets(source)
    edits: List[Tuple[int, int, str]] = []
    cut: List[str] = []
    for node in texts:
        text = str(node.value)
        for t in sorted(triggers, key=len, reverse=True):
            if _mentions(text, t):
                text = re.sub(rf"(?i)(?<![\w]){re.escape(t)}(?![\w])", "", text)
                cut.append(t)
        if text != node.value:
            edits.append((pos(node.lineno, node.col_offset), pos(node.end_lineno, node.end_col_offset),
                          json.dumps(_tidy_cut(text) if text.strip(" ,.") else "", ensure_ascii=False)))
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source, [f'trigger words "{t}" cut: they are added with the LoRA' for t in dict.fromkeys(cut)]


def _names_lora_set(options: Sequence[str], names: Sequence[str]) -> bool:
    """A pick's options are the LoRAs' own names (each equal to one, case, spacing and
    surrounding punctuation aside), at least two of them: the same choice as the LoRA pick."""
    opts = {_bare(o) for o in options if _bare(o)}
    return len(opts) >= 2 and opts <= {_bare(n) for n in names}


def _formats_lora(source: str) -> bool:
    """The program turns a pick_lora value (the LoRA's name) into text: an f-string, + or str()."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    names = {n.targets[0].id for n in ast.walk(tree)
             if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
             and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", None) == "pick_lora"}

    def is_lora(x: ast.AST) -> bool:
        return isinstance(x, ast.Name) and x.id in names
    for n in ast.walk(tree):
        if isinstance(n, ast.FormattedValue) and is_lora(n.value):
            return True
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add) and (is_lora(n.left) or is_lora(n.right)):
            return True
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "str" and any(is_lora(a) for a in n.args):
            return True
    return False


def _listed_picks(source: str) -> Set[str]:
    """Ids of picks that give their options as a list (pick(id, [...])) rather than about= and seed=."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    out: Set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "pick" and len(node.args) > 1
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            out.add(node.args[0].value)
    return out


def validate(source: str, prompt: str, loras: Sequence[LoraInfo], params: Set[str],
             enhanced: str = "", elaborate: bool = True) -> Dict[str, Any]:
    """The written program's problems (sent back to the writer) and notes (logged). `enhanced`
    and `elaborate` are accepted for callers' sake; no check reads them."""
    if uses_draws(source):  # phases and dependencies, checked on the code (raises ProgramError)
        analyze(source, strict=True)
        draw(source, 11, None, loras, params)  # and the draw path runs it
    info = discover(source, loras, params)
    samples = [run(source, s, None, loras, params) for s in (11, 23, 37, 51)]
    problems: List[str] = []   # broken or visibly wrong: one repair, as line edits
    notes: List[str] = []      # quality hints: logged and shown in dev mode, never a retry
    if any(re.search(r"<<<|>>>|^\s*[\"']{3}", r.prompt) for r in samples):
        problems.append("Emit only the prompt text itself, with no quote marks or <<< >>> around it.")
    if any(re.search(r"\{[^{}]*\|[^{}]*\}", r.prompt) or "[{" in r.prompt for r in samples):
        problems.append("Replace every {a|b} list with its pick's value; never emit the braces.")
    for seg in _verbatim_segments(prompt):
        bad = [r for r in samples if seg.lower() not in realized_text(r.prompt).lower()]
        if bad:
            problems.append(f'The protected text "{seg}" must appear exactly in every prompt you emit.')
    for r in samples:
        for line in prompt.splitlines():
            ln = line.strip()
            if ln.startswith("#") and len(ln) > 12 and ln.lstrip("# ").lower()[:40] in r.prompt.lower():
                problems.append(f'Don\'t emit instruction lines ("{ln[:50]}"). They are for you, not the image model.')
                break
    missing: Dict[str, str] = {}
    # a palette pick (a template's Colours) reaches the prompt as the colours it fills in, never by its name
    palettes = {lf.slots for lf in vocabulary().leaves.values() if lf.slots}
    for r in samples:  # a choice that never reaches the prompt does nothing
        text = r.prompt.lower()
        for d in r.draws:
            if d.kind == "pick" and getattr(d, "cls", None) in palettes:
                continue
            if d.kind == "pick" and not d.hidden and d.value and not _emitted_in(str(d.value), text):
                missing.setdefault(d.id, str(d.value))
    # LoRAs work by being on. A listed LoRA's exact name in the text, when the user didn't write
    # it: while another LoRA (or none) is on, the text says what the image isn't (sent back);
    # while that LoRA is on, it is only noise (noted). A name that is a LoRA's own trigger word
    # is added with that LoRA, never by the program.
    triggers = {_bare(t) for lo in loras for t in (lo.trigger or "").split(",") if t.strip()}
    for r in samples:
        text = r.prompt.lower()
        on = {lu.name for lu in r.loras}
        named = [n for n in dict.fromkeys([lu.name for lu in r.loras] + [lo.name for lo in loras])
                 if _bare(n) not in triggers and _mentions(text, n) and not _mentions(prompt, n)]
        off = [n for n in named if n not in on]
        if off:
            problems.append(f'The prompt you emit says "{off[0]}", the name of a LoRA that isn\'t on in that image, so '
                            "the text contradicts the image. pick_lora() turns a LoRA on and its trigger words are "
                            "added for you: leave LoRA names out of emit() and the seeds, or put words for a LoRA in a "
                            "lookup on the name pick_lora returns, so they appear only when that LoRA is on.")
            break
        if named and _formats_lora(source):
            problems.append(f'The prompt you emit says "{named[0]}": the value pick_lora() returns is the LoRA\'s name, '
                            "for comparing or looking up, never text. Don't put it into a string (f\"{...}\", + or "
                            "str()); emit only words that describe the image.")
            break
        if named:
            notes.append(f'The prompt names the LoRA "{named[0]}" while it is on. A LoRA works by being on; its name '
                         "in the text tells the image model nothing.")
    lora_sets = [(c["id"], set(c.get("options") or [])) for c in info["choices"] if c.get("kind") == "lora"]
    stacked: Set[Tuple[str, str]] = set()
    # a LoRA applies to the whole image: two picks over one set in one run stack. With more
    # than one LoRA pick, look across discovery's runs, since one may run only sometimes.
    lora_runs = samples if len(lora_sets) < 2 else [run(source, 7 + i * 7919, None, loras, params) for i in range(48)]
    for r in lora_runs:
        ran = [(d.id, set(d.options or [])) for d in r.draws if d.kind == "lora"]
        for i, (a, sa) in enumerate(ran):
            for b, sb in ran[i + 1:]:
                if sa & sb and (a, b) not in stacked:
                    stacked.add((a, b))
                    problems.append(f'pick_lora("{a}") and pick_lora("{b}") choose from the same LoRAs, so every image '
                                    "would get two of them: a LoRA applies to the whole image, not to one person. "
                                    "Use one pick_lora for them.")
    named: Set[str] = set()
    for cid, names in lora_sets:  # the LoRA carries its trait; text that names it can disagree with it
        for c in info["choices"]:
            if c["id"] in named:
                continue
            if c.get("kind") == "pick" and _names_lora_set(c.get("options") or [], sorted(names)):
                named.add(c["id"])
                notes.append(f'pick("{c["id"]}") names the same things as pick_lora("{cid}") ({", ".join(c["options"][:3])}…), '
                                "so the text can disagree with the LoRA that's on. The LoRA alone carries it: remove that pick "
                                "and don't describe it in the text.")
    for r in samples:  # parameters are set by param(); the image model must not read them
        for name in r.params:
            if re.search(rf"\b{re.escape(name)}\b\s*[:=]?\s*[0-9]", r.prompt, re.I):
                problems.append(f'Don\'t write {name} into the prompt text. param("{name}", ...) already sets it.')
                break
    twice: Dict[str, str] = {}
    for r in samples:  # each pick stands in one place ("holding dreadlocks" came from emitting it twice)
        text = realized_text(r.prompt).lower()
        drawn = Counter(str(d.value or "").lower().strip() for d in r.draws if d.kind == "pick" and not d.hidden)
        for d in r.draws:
            v = str(d.value or "").lower().strip()
            # two people can draw the same value ("a low ponytail" for two friends): once per draw is fine
            if d.kind == "pick" and not d.hidden and len(v.split()) >= 2 and text.count(v) > drawn[v]:
                twice.setdefault(d.id, str(d.value))
    for cid, value in twice.items():
        notes.append(f'pick("{cid}") appears more than once in the prompt ("{value}"). Emit each pick once, where its subject belongs.')
    written = [[o.strip() for o in m.group(1).split("|")] for m in _INLINE_LIST.finditer(prompt)]
    lists = {c["id"]: c for c in info["choices"] if c.get("source") == "list"
             and any((c.get("options") or [])[:len(u)] == u for u in written)}
    for cid, value in missing.items():
        if cid in lists:  # the user's own list: its value is the words they wrote, emitted as is
            items = "|".join(lists[cid].get("options") or [])
            problems.append(f'pick("{cid}") is the user\'s list {{{items}}}, but its value ("{value}") never appears in the '
                            "emitted prompt. Pass its variable itself to emit(...) where the list stood in the user's prompt. "
                            "A pick that describes the list's value doesn't replace it: drop that pick, or emit it beside the "
                            "list's variable.")
        else:
            problems.append(f'pick("{cid}") drew "{value}" but it never appears in the emitted prompt. Pass its variable to '
                            "emit(...) where its subject stands, and drop any other pick or fixed text that says the same thing.")
    for name in smart_wildcards(prompt):
        if not _smart_choice(info, name):
            problems.append(_smart_missing(name, info))
    if uses_draws(source):  # older programs write options as lists
        user_lists = [[o.strip() for o in m.group(1).split("|")] for m in _INLINE_LIST.finditer(prompt)]
        listed = _listed_picks(source)
        smart = smart_wildcards(prompt)
        for c in info["choices"]:  # only the user's own {a|b} lists are lists; a list never gets options of its own
            opts = c.get("options") or []
            if c.get("kind") != "pick" or c.get("source") != "list" or any(opts[:len(u)] == u for u in user_lists):
                continue  # (as the exact-list check below: the user's items first)
            listed.discard(c["id"])
            items = "|".join(c.get("options") or [])
            hint = (f' The prompt\'s {", ".join("{{" + n + "}}" for n in smart)} '
                    f'{"is a smart wildcard" if len(smart) == 1 else "are smart wildcards"}: pick(id, about=..., '
                    "seed=[1 to 3 examples], label=..., phase=..., line=...), with no list of options.") if smart else ""
            problems.append(f'pick("{c["id"]}") has source="list", but the user\'s prompt has no list {{{items}}}: '
                            'source="list" is only for the user\'s own {a|b|c} lists, with exactly their items.' + hint)
        for name in smart:
            c = next((x for x in _smart_choices(info, name) if x["id"] in listed), None)
            if c:
                problems.append(f'{{{{{name}}}}} is a smart wildcard, not a list: write pick("{c["id"]}", about=..., '
                                "seed=[1 to 3 examples], label=..., phase=..., line=...) with no list of options. Its "
                                "options are written later from about= and the seeds.")
    for name in smart_wildcards(prompt):  # a descriptive name says what to write, it isn't an option
        c = _smart_choice(info, name)
        if c and any(is_name_of(o, name) for o in c["options"]):
            notes.append(f'{{{{{name}}}}} needs seeds that are concrete examples of "{name}" (one to three specific '
                            f'ones, as they would read in the sentence), never the word "{name}" itself.')
    for c in info["choices"]:  # labels are pill names, not descriptions
        if len(c["label"]) > 24 or len(c["label"].split()) > 3:
            notes.append(f'label="{c["label"]}" is too long for {c["id"]}: use one or two words, like "Weather" or "Photo look".')
    if any("{{" in r.prompt for r in samples):
        problems.append("Don't emit {{...}}: replace each smart wildcard with its pick's value.")
    for m in _INLINE_LIST.finditer(prompt):
        opts = [o.strip() for o in m.group(1).split("|")]
        if not any(c["options"][: len(opts)] == opts and c.get("source") == "list" for c in info["choices"]):
            problems.append(f'The user list {{{m.group(1)}}} must be a pick with exactly these options in order and source="list".')
    problems += _shared_person_details(info, source)
    return {"info": info, "problems": list(dict.fromkeys(problems)), "notes": list(dict.fromkeys(notes))}


_PERSON_INDEX = re.compile(r"^([A-Za-z_]\w*)\[(\d+)\]\.")


def _shared_person_details(info: Dict[str, Any], source: str = "") -> List[str]:
    """With more than one person (a group(), or picks like girl[1].hair and girl[2].hair), a
    detail of a person (a pick bound to a person list) whose id names no person is shared by
    all of them: "a couple" drawing one ethnicity for both."""
    indexed = {(m.group(1), m.group(2)) for c in info["choices"] if (m := _PERSON_INDEX.match(str(c.get("id"))))}
    people = any(int(g.get("count") or 0) >= 2 for g in info.get("groups") or []) or len(indexed) >= 2
    if not people:
        return []
    vocab = vocabulary()
    palettes = {lf.slots for lf in vocab.leaves.values() if lf.slots}
    loops = []  # (variable, group id) for each group() the program itself declares
    try:
        loops = [(n.targets[0].id, _const(n.value.args[0])) for n in ast.walk(ast.parse(source))
                 if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                 and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", None) == "group"
                 and n.value.args and isinstance(_const(n.value.args[0]), str)]
    except SyntaxError:
        pass
    shared = [str(c["id"]) for c in info["choices"]
              if c.get("kind") == "pick" and str(c.get("cls") or "").startswith("person.")
              and str(c.get("cls")) not in palettes and "." not in str(c.get("id") or "")]
    if not shared:
        return []
    names = ", ".join(f'pick("{cid}")' for cid in shared)
    if loops:
        var, g = loops[0]
        how = (f"Draw them inside the loop, one per person: under `for i in range({var}):` write "
               f'`{shared[0]} = pick(f"{g}[{{i+1}}].{shared[0]}", ...)` and emit `{shared[0]}` in that same loop, '
               "where that person is described.")
    else:
        who = (sorted(indexed) or [("person", "")])[0][0]
        how = f"Write one pick per person: {who}[1].{shared[0]}, {who}[2].{shared[0]}, and so on, each emitted where that person is."
    return [f"{names} {'is' if len(shared) == 1 else 'are'} drawn once and shared by everyone, but each person needs "
            f"their own. {how} This changes the program's shape: rewrite it whole with write_program."]


def normalize_sources(info: Dict[str, Any], prompt: str) -> None:
    """A {{name}} wildcard is the user's own choice: from their text, on its line, whatever
    the writer marked it. Every other choice keeps the source the writer gave it."""
    lines = [ln.lower() for ln in prompt.splitlines()]
    for name in smart_wildcards(prompt):  # the user's own {{name}}: from their text, on its line
        for c in _smart_choices(info, name):
            c["source"], c["wildcard"] = "text", name
            c["line"] = next((i + 1 for i, ln in enumerate(lines) if "{{" + name.lower() in ln.replace("{{ ", "{{")), c.get("line"))


# --------------------------------------------------------------------------- entry point

def _store(profile_id: Optional[str]) -> ProgramStore:
    import app_dirs
    from core.profile_context import get_current_profile
    return ProgramStore(app_dirs.get_profile_dir(profile_id or get_current_profile()) / "prompt_programs")


async def lora_candidates(tool_id: str, items: Sequence[Dict[str, Any]], profile_id: Optional[str]) -> Tuple[List[LoraInfo], Dict[str, str]]:
    """The tool's LoRA list items (from the editor) with trigger words and notes."""
    from lora_notes import display_name, resolve_lora_notes
    notes_by_value: Dict[str, Any] = {}
    try:
        found = await resolve_lora_notes(profile_id, tool_id)
        notes_by_value = {v: (it.get("note") or {}) for v, it in (found.get("items") or {}).items()}
    except Exception as e:  # notes never block preparing
        log.warning(f"[prompt-program] LoRA notes unavailable for {tool_id}: {e}")
    out: List[LoraInfo] = []
    notes: Dict[str, str] = {}
    for item in items or []:
        path = str(item.get("lora") or item.get("path") or item.get("name") or "")
        if not path:
            continue
        note = notes_by_value.get(path) or {}
        name = str(item.get("name") or display_name(path))
        triggers = note.get("trigger_words") or []
        try:
            weight = float(item.get("weight", 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        out.append(LoraInfo(name=name, path=path, weight=weight, trigger=", ".join(triggers), on=bool(item.get("enabled"))))
        if note.get("notes"):
            notes[name] = str(note["notes"])[:300]
    return out, notes


ENHANCE_LEVELS = ("off", "fill", "expand")


def enhance_level(enhance: Optional[str], elaborate: bool = True) -> str:
    """The Enhance level: "off", "fill" or "expand". Older callers send only elaborate."""
    level = str(enhance or "").strip().lower()
    return level if level in ENHANCE_LEVELS else ("expand" if elaborate else "off")


async def ensure_program(*, prompt: str, tool_id: str, ctx: Dict[str, Any], instructions: str,
                         lora_items: Sequence[Dict[str, Any]], project_id: Optional[int],
                         profile_id: Optional[str], cache_only: bool = False, force: bool = False,
                         elaborate: bool = True, lora_notes: bool = True, lora_triggers: bool = True,
                         base_key: Optional[str] = None, enhance: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The prepared program for these inputs, from cache or by asking the model.
    enhance: "expand" (the per-model guide is part of the writer's instructions and the
    program writes a complete, rich prompt with content picks), "fill" (a short per-model
    guide: the user's words plus only what the model needs to read them, no added picks) or
    "off" (the user's own words). Without it, elaborate picks expand or off. base_key: the
    program the editor showed before this prompt (an edit continues from it when it fits).
    lora_triggers: the prompt menu's "Trigger words"; off, the writer isn't told the on
    LoRAs' trigger words (so it never writes them), as the classic enhancer isn't."""
    level = enhance_level(enhance, elaborate)
    elaborate = level == "expand"
    from prompt_pipeline import _profile_wildcards_and_segments

    wildcards, segments = _profile_wildcards_and_segments(profile_id)
    source_prompt = expand_named_lists(prompt, wildcards, segments).strip()
    if len(source_prompt) > MAX_PROMPT_CHARS:
        raise PromptTooLong(f"This prompt is too long to prepare ({len(source_prompt):,} characters with its lists "
                            f"and segments filled in; the limit is {MAX_PROMPT_CHARS:,}). Shorten it, or use Direct.")
    if len(instructions or "") > MAX_INSTRUCTIONS_CHARS:
        raise PromptTooLong(f"Your standing instructions for prompts are too long to prepare with "
                            f"({len(instructions):,} characters; the limit is {MAX_INSTRUCTIONS_CHARS:,}).")
    # The models below only ever see tokens for [exact text]; the key keeps the real text.
    masked_prompt, exact = mask_exact(source_prompt)
    params = tool_param_specs(ctx.get("schema_props") or {})
    candidates, notes = await lora_candidates(tool_id, lora_items, profile_id)
    if not lora_notes:  # the prompt menu's "LoRA notes" is off: the model isn't told them
        notes = {}
    # Two separate things. The writer may choose among `loras` with pick_lora (only when the
    # prompt asks to choose LoRAs). The enhancer is told only about the LoRAs switched on,
    # for their trigger words and notes; choosing isn't its job, and names aren't prompt text.
    loras = match_loras(source_prompt, candidates)
    # With "Trigger words" off they reach neither the writer nor the key: only the notes do.
    lora_context = [{"name": lo.name,
                     "trigger_words": [t.strip() for t in lo.trigger.split(",") if t.strip()] if lora_triggers else [],
                     "notes": notes.get(lo.name, "")}
                    for lo in candidates if lo.on and ((lo.trigger and lora_triggers) or notes.get(lo.name))]
    # The canvas's size never reaches the writer, only its shape, and only for models whose
    # guide composes for it (Qwen-Image, FLUX.3 Klein): there the shape is part of the key, so
    # turning a landscape portrait won't reuse a program written "a wide landscape…"; for
    # every other model one program serves every size.
    from routes.prompt_enhancement import canvas_shape, guide_template, guide_uses_canvas
    enhance = {k: v for k, v in (ctx.get("enhance") or {}).items() if k not in ("width", "height")}
    if level != "off" and guide_uses_canvas(str(ctx.get("mode") or ""), fill=(level == "fill")):
        enhance["canvas"] = canvas_shape((ctx.get("enhance") or {}).get("width"), (ctx.get("enhance") or {}).get("height"))
    parts = {
        "v": PREPARE_VERSION, "vocab": vocabulary().version, "tool": tool_id, "model": ctx.get("model"),
        "mode": ctx.get("mode"), "enhance": enhance, "instructions": instructions,
        # on/off reaches the key only through `notes` (the on LoRAs' trigger words and notes):
        # switching a plain LoRA on or off doesn't need a new program
        "params": sorted(params), "loras": [{k: v for k, v in vars(lo).items() if k != "on"} for lo in loras],
        "notes": lora_context,
        "lora_notes": {lo.name: notes[lo.name] for lo in loras if notes.get(lo.name)},  # what the writer reads
        "elaborate": level,
        "writer": await _writer_fingerprint(project_id),  # another writer model writes another program
        # what the writer is told: an edit to instructions.md, the vocabulary or this model's
        # guide is a new program even if PREPARE_VERSION isn't bumped
        "text": _text_hash(guide_template(str(ctx.get("mode") or ""), fill=(level == "fill")) if level != "off" else ""),
    }
    key = program_key({**parts, "prompt": source_prompt})
    context = program_key(parts)  # the same editing context, whatever the prompt says
    _latest[context] = key
    store = _store(profile_id)
    cached = None if force else store.get(key)
    if cached and not cache_only and (store.recent(context) or [None])[0] != key:
        store.remember(context, key)  # back to this prompt: the next small edit patches it
    if cached and cached.get("narrow_pending"):
        renarrow(cached, store, project_id)  # in the background; this run draws from it as it is
    if cached or cache_only:
        return cached
    # One prepare per key: concurrent runs and the editor share it instead of each
    # asking the model.
    # The key covers the writer context; the store root is the profile. A forced prepare
    # never joins an ordinary one (it must not hand back the program it is replacing).
    flight = (str(store.root), key, bool(force))
    running = _in_flight.get(flight)
    if running is None:
        args = dict(key=key, store=store, tool_id=tool_id, ctx=ctx, instructions=instructions, source_prompt=masked_prompt,
                    params=params, loras=loras, notes=notes, lora_context=lora_context, project_id=project_id,
                    profile_id=profile_id, elaborate=bool(elaborate), level=level, exact=exact)
        running = asyncio.ensure_future(_prepare(context=context, force=force, base_key=base_key, **args))
        _in_flight[flight] = running
        running.add_done_callback(lambda _t, k=flight: _in_flight.pop(k, None) if _in_flight.get(k) is _t else None)
    return await asyncio.shield(running)


_in_flight: Dict[Tuple[str, str, bool], "asyncio.Future[Dict[str, Any]]"] = {}

# The program each editing context asked for last (context key → program key), so background
# option generation can drop queued work for prompts the user has edited away from.
_latest: Dict[str, str] = {}


def preparing() -> bool:
    """Whether any prepare is in flight (background option generation gives way to it)."""
    return bool(_in_flight)


def is_current(program_key: str, context_key: str) -> bool:
    """Whether a program is the one its editing context asked for last (or nothing says otherwise)."""
    latest = _latest.get(context_key) if context_key else None
    return latest is None or latest == program_key


async def _writer_fingerprint(project_id: Optional[int]) -> Optional[str]:
    """The writer model (never its credentials): part of the program key."""
    try:
        cfg, _ = await _writer_endpoint(project_id)
        return cfg.get_model() if cfg is not None else None
    except Exception:  # no chat model configured: cached programs can still be looked up
        return None


# Whether an endpoint's model makes tool calls, learned on first contact: (api base, model) →
# "tools" or "text". Endpoints without usable tool calls get the text protocol.
_PROTOCOL: Dict[Tuple[str, str], str] = {}


def _endpoint_id(cfg: Any) -> Tuple[str, str]:
    return (str(cfg.get_api_base() or ""), str(cfg.get_model() or ""))


async def _writer_endpoint(project_id: Optional[int]) -> Tuple[Any, str]:
    """The writer's LLM config and the protocol it speaks ("tools", or "text")."""
    from llm_resolver import get_effective_llm_config
    cfg = await get_effective_llm_config("tool_assistant", project_id)
    return cfg, _PROTOCOL.get(_endpoint_id(cfg), "tools")


async def _prepare(*, context: str, force: bool, **args: Any) -> Dict[str, Any]:
    # The session keeps its own deadline (PREPARE_LIMIT_SECONDS, keeping the best program
    # it has); this is only the backstop for a step that ignores it.
    try:
        return await asyncio.wait_for(_prepare_once(context=context, force=force, **args), PREPARE_LIMIT_SECONDS + 2)
    except asyncio.TimeoutError:
        log.warning(f"[prompt-program] prepare {args.get('key')} gave up after {PREPARE_LIMIT_SECONDS:.0f}s")
        raise PrepareTimeout(f"Preparing took longer than {PREPARE_LIMIT_SECONDS:.0f} seconds, so it stopped. "
                             "The chat model may be busy or too slow for this prompt.") from None
    except Exception as e:
        failure = writer_failure(e)
        if failure is None:
            raise
        log.warning(f"[prompt-program] prepare {args.get('key')}: the chat model failed: {type(e).__name__}: {e}")
        raise failure from e


NARROW_RESERVE = 3.0   # seconds of the prepare deadline left for storing the entry after narrowing


async def _narrow(entry: Dict[str, Any], store: ProgramStore, project_id: Optional[int], started: float) -> None:
    """Bound picks narrowed by the user's words (where=, or a wildcard's own name): one
    cached model call per (list, words), see narrow.py. Never fails the prepare: it gets only
    what's left of the prepare's deadline, and with too little left the picks stay unnarrowed
    rather than the prepared program being lost to the timeout. A narrowing skipped or left
    unfinished that way isn't final: the entry records it (narrow_pending) and a later
    lookup of the program narrows it again in the background (renarrow)."""
    from prompt_programs.narrow import NARROW_SECONDS, NarrowCache, mark_pending, narrow_entry
    left = PREPARE_LIMIT_SECONDS - (time.monotonic() - started) - NARROW_RESERVE
    if left < 2.0:
        if mark_pending(entry):
            log.info("[prompt-program] no time left to narrow the bound picks; they draw from their whole lists "
                     "until a later lookup narrows them")
        return
    t0 = time.monotonic()
    try:
        notes = await narrow_entry(entry, NarrowCache(store.root / "narrow"), _ask_model, project_id,
                                   seconds=min(NARROW_SECONDS, left))
    except Exception as e:  # never fails the prepare
        log.warning(f"[prompt-program] narrowing {entry.get('key')} failed: {e}")
        mark_pending(entry)
        return
    if entry.get("filters"):
        entry.setdefault("timing", {})["narrow"] = round(time.monotonic() - t0, 2)
        entry["warnings"] = list(entry.get("warnings") or []) + notes


RENARROW_BACKOFF_SECONDS = 30.0   # between tries for one program
RENARROW_MAX_TRIES = 5            # then its picks keep the fallback for good (logged)
_renarrowing: Dict[Tuple[str, str], "asyncio.Task[None]"] = {}
_renarrow_after: Dict[Tuple[str, str], float] = {}


def renarrow(entry: Dict[str, Any], store: ProgramStore, project_id: Optional[int]) -> Optional["asyncio.Task[None]"]:
    """Narrow again, in the background, the picks of a stored program whose narrowing was
    skipped or didn't finish; the stored entry is updated when it completes and later runs
    draw from it. Never blocks: this run draws from the entry as it is. One try per program
    at a time, at most every RENARROW_BACKOFF_SECONDS. Returns the task, or None."""
    if not entry.get("narrow_pending") or int(entry.get("narrow_tries") or 0) >= RENARROW_MAX_TRIES:
        return None
    flight = (str(store.root), str(entry.get("key")))
    if flight in _renarrowing or time.monotonic() < _renarrow_after.get(flight, 0.0):
        return None
    _renarrow_after[flight] = time.monotonic() + RENARROW_BACKOFF_SECONDS

    async def run() -> None:
        from prompt_programs.narrow import NARROW_SECONDS, NarrowCache, narrow_entry, reopen_pending
        current = store.get(flight[1])
        if not current or not current.get("narrow_pending"):
            return
        tries = int(current.get("narrow_tries") or 0) + 1
        reopen_pending(current)
        try:
            notes = await narrow_entry(current, NarrowCache(store.root / "narrow"), _ask_model, project_id,
                                       seconds=NARROW_SECONDS)
        except Exception as e:
            log.warning(f"[prompt-program] narrowing {flight[1]} again failed: {e}")
            return
        now = store.get(flight[1])
        if not now or now.get("program") != current.get("program") or now.get("created_at") != current.get("created_at"):
            return  # prepared again meanwhile ("Try different choices"): never put the old one back
        current["narrow_tries"] = tries
        current["warnings"] = list(dict.fromkeys(list(current.get("warnings") or []) + notes))
        store.put(flight[1], current)
        left = sorted(current.get("narrow_pending") or {})
        if left and tries >= RENARROW_MAX_TRIES:
            log.warning(f"[prompt-program] {flight[1]}: narrowing {left} didn't finish after {tries} tries; "
                        "they keep their fallback")
        else:
            log.info(f"[prompt-program] {flight[1]} narrowed again (try {tries}){': still pending ' + str(left) if left else ''}")

    task = asyncio.ensure_future(run())
    _renarrowing[flight] = task
    task.add_done_callback(lambda _t: _renarrowing.pop(flight, None))
    return task


async def _prepare_once(*, context: str, force: bool, base_key: Optional[str] = None, **args: Any) -> Dict[str, Any]:
    """A small edit of a prompt prepared in this context continues that program's writer
    session; anything else (or "Try different choices") starts a new one. Endpoints whose
    model makes no tool calls get the text protocol (_prepare_text)."""
    started = time.monotonic()
    store: ProgramStore = args["store"]
    base = None if force else _patch_base(store, context, args["source_prompt"], base_key)
    cfg, protocol = await _writer_endpoint(args["project_id"])
    if protocol == "tools":
        from prompt_programs.session import ToolsUnsupported, prepare_session
        try:
            entry = await prepare_session(cfg=cfg, base=base, context=context, started=started, **args)
        except ToolsUnsupported as e:
            _PROTOCOL[_endpoint_id(cfg)] = "text"
            log.warning(f"[prompt-program] {_endpoint_id(cfg)[1]} makes no tool calls ({e}): using the text protocol")
        else:
            entry["context_key"] = context
            await _narrow(entry, store, args["project_id"], started)
            store.put(entry["key"], entry)
            store.remember(context, entry["key"])
            _notify_prepared(entry, args["project_id"], args["profile_id"])
            return entry
    return await _prepare_text(context=context, base=base, started=started, **args)


async def _prepare_text(*, context: str, base: Optional[Dict[str, Any]], started: Optional[float] = None,
                        **args: Any) -> Dict[str, Any]:
    """The text protocol: the program comes back in a ```python block, edits as numbered
    lines in plain text, and nothing persists between calls but the program."""
    store: ProgramStore = args["store"]
    started = started if started is not None else time.monotonic()
    entry = None
    if base is not None:
        try:
            entry = await _prepare_patch(base=base, started=started, **args)
        except StartOver as e:
            log.info(f"[prompt-program] starting over: {e}")
            base = None  # a new prompt: its own program, lineage and options
        except ProgramError as e:
            log.info(f"[prompt-program] patch from {base.get('key')} failed: {e}")
    if entry is None:
        # A small edit whose patch didn't hold is still the same prompt's next version: the
        # writer sees the old program and keeps what didn't change, and its options stay.
        entry = await _prepare_new(prev=base, started=started, **args)
    entry["context_key"] = context
    await _narrow(entry, store, args["project_id"], started)
    store.put(entry["key"], entry)
    store.remember(context, entry["key"])
    _notify_prepared(entry, args["project_id"], args["profile_id"])
    return entry


# --------------------------------------------------------------------------- fixing in place

_LINE_EDIT_HOW = """Reply with only your changed lines, already changed: for each, its line number, a colon and its
new text, like
7: emit("A portrait of a", subject, "in the rain.")
Don't repeat lines you keep. To delete a line, write its number and a colon with nothing after it. To add
a line after line 4, number it 4.5. No explanation."""

REPAIR_NOTE = """That program has a problem:
{problems}

The program, with line numbers:
{numbered}

Fix only that, changing as little as you can. """ + _LINE_EDIT_HOW

_LINE_EDIT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*:(?:\s|$)(.*)$")


def _numbered_program(source: str) -> str:
    return "\n".join(f"{i + 1}: {ln}" for i, ln in enumerate(source.rstrip("\n").splitlines()))


def _open_brackets(text: str) -> int:
    """Brackets left open at the end of a line of code (string literals skipped)."""
    depth, quote, i = 0, "", 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            break
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        i += 1
    return depth


def apply_line_edits(source: str, reply: str) -> Optional[str]:
    """Apply numbered-line edits ("7: new text", "7:" deletes, "4.5: ..." inserts after 4)
    to a program. A changed line that starts a statement spanning several lines replaces
    the whole statement. None when the reply holds no edits."""
    edits: Dict[float, List[str]] = {}
    current: Optional[float] = None
    for raw in (reply or "").splitlines():
        if raw.strip().startswith("```"):
            current = None
            continue
        m = _LINE_EDIT.match(raw)
        if m:
            current = float(m.group(1))
            edits[current] = [m.group(2).rstrip()] if m.group(2).strip() else []
        elif current is not None and edits.get(current) and _open_brackets("\n".join(edits[current])) > 0:
            edits[current].append(raw.rstrip())  # the edited statement continues
        else:
            current = None
    if not edits:
        return None
    lines = source.rstrip("\n").splitlines()
    try:
        spans = {st.lineno: st.end_lineno for st in ast.walk(ast.parse(source)) if isinstance(st, ast.stmt)}
    except SyntaxError:
        spans = {}
    out: List[str] = []
    skip_to = 0
    for n, line in enumerate(lines, start=1):
        if n <= skip_to and float(n) not in edits:
            continue
        if float(n) in edits:
            new = edits[float(n)]
            end = spans.get(n, n)
            if new and end > n and not any(float(k) in edits for k in range(n + 1, end + 1)):
                try:
                    ast.parse("\n".join(x.strip() for x in new) if len(new) == 1 else "\n".join(new))
                    skip_to = end  # the new text is the whole statement
                except SyntaxError:
                    pass
            indent = line[: len(line) - len(line.lstrip())]
            if new and not new[0].startswith((" ", "\t")):
                new = [indent + new[0], *new[1:]]
            out.extend(new)
        else:
            out.append(line)
        for k in sorted(k for k in edits if n < k < n + 1):
            out.extend(edits[k])
    for k in sorted(k for k in edits if k > len(lines)):
        out.extend(edits[k])
    result = "\n".join(out) + "\n"
    return result


# --------------------------------------------------------------------------- small edits

def _prompt_words(text: str) -> List[str]:
    return re.findall(r"\S+", text)


def prompt_changes(old: str, new: str) -> List[Tuple[str, str]]:
    """Word-level changes from old to new: (removed, added) runs."""
    a, b = _prompt_words(old), _prompt_words(new)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    return [(" ".join(a[i1:i2]), " ".join(b[j1:j2])) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]


def _lists_and_frame(prompt: str) -> Tuple[str, List[str]]:
    return _INLINE_LIST.sub("{\u2026}", prompt), [m.group(1) for m in _INLINE_LIST.finditer(prompt)]


def edit_kind(old: str, new: str) -> Optional[str]:
    """How a prompt edit can be applied to the old prompt's program:
    "same" (only [exact text] changed: the program is unchanged), "lists" (only the items
    of {a|b} lists changed: rewritten in code), "text" (a small edit the writer patches),
    or None (prepare anew: the new prompt is empty). Whether a text change is an edit of
    this prompt or a different prompt is the writer's call: it answers START OVER (or calls
    start_over) for a different prompt. Code never judges it from the words."""
    if old == new:
        return "same"
    f0, l0 = _lists_and_frame(old)
    f1, l1 = _lists_and_frame(new)
    if f0 == f1 and len(l0) == len(l1):
        return "lists"
    if not old.strip() or not new.strip():
        return None
    return "text"


def _patch_base(store: ProgramStore, context: str, prompt: str, base_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The program this prompt may be an edit of (the writer decides whether it is). The one
    the editor says it showed (base_key) when it was prepared in this context; otherwise the
    recent program in this context with the fewest changed words to this prompt (a guess: it
    can pick a sibling the user wasn't looking at)."""
    if base_key:
        e = store.get(base_key)
        if (e and e.get("context_key") == context and e.get("version") == PREPARE_VERSION and e.get("program")
                and edit_kind(e["prompt"], prompt) is not None):
            return e
    best: Optional[Tuple[int, Dict[str, Any]]] = None
    for k in store.recent(context):
        e = store.get(k)
        if not e or e.get("version") != PREPARE_VERSION or not e.get("program") or edit_kind(e["prompt"], prompt) is None:
            continue
        size = sum(len(x) + len(y) for x, y in prompt_changes(e["prompt"], prompt))
        if best is None or size < best[0]:
            best = (size, e)
    return best[1] if best else None


def patch_lists(source: str, old: str, new: str) -> Optional[str]:
    """Rewrite the options of user-list picks whose {a|b} items changed. None if a
    changed list has no pick holding exactly its old items, or several picks hold them and
    the old prompt wrote that list more than once."""
    _, before = _lists_and_frame(old)
    _, after = _lists_and_frame(new)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    holders: Dict[Tuple[str, ...], List[ast.List]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "pick"):
            continue
        kw = {k.arg: k.value for k in node.keywords}
        if not (isinstance(kw.get("source"), ast.Constant) and kw["source"].value == "list"):
            continue
        opts = node.args[1] if len(node.args) > 1 else kw.get("options")
        if isinstance(opts, ast.List) and all(isinstance(e, ast.Constant) for e in opts.elts):
            holders.setdefault(tuple(str(e.value) for e in opts.elts), []).append(opts)
    pos = _offsets(source)
    edits = []
    for a, b in zip(before, after):
        if a == b:
            continue
        found = holders.get(tuple(o.strip() for o in a.split("|"))) or []
        # One list can fill several places (each its own pick); that's only certain when
        # the old prompt wrote it once. Two identical lists, one edited, is ambiguous.
        items = tuple(o.strip() for o in a.split("|"))
        written = sum(1 for x in before if tuple(o.strip() for o in x.split("|")) == items)
        if not found or (len(found) > 1 and written != 1):
            return None
        text = "[" + ", ".join(json.dumps(o.strip(), ensure_ascii=False) for o in b.split("|")) + "]"
        for node in found:
            edits.append((pos(node.lineno, node.col_offset), pos(node.end_lineno, node.end_col_offset), text))
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


PATCH_NOTE = """The user edited their prompt. It now reads (lines numbered):
{prompt}

What changed: {changes}.

The program, with line numbers:
{numbered}

First decide: is this an edit of the same prompt, or a different prompt?
- A different prompt: what the image is of has changed (a woman walking a dog became a sports car;
  a bowl of ramen became a sleeping kitten; a fisherman became a cyberpunk hacker). Little of the
  program would survive. Reply with only START OVER, and it will be written fresh.
- An edit: the same subject with something changed, added or removed (a red coat became a blue
  coat, a guitar became a violin, autumn became spring, "seagulls overhead" was added, a # line
  was added). Reply EDIT on the first line, then update the program to match, changing as little
  as you can: the emitted text and the picks this edit affects, by the same rules. Keep every
  other line as it is.

""" + _LINE_EDIT_HOW


def _describe_changes(changes: Sequence[Tuple[str, str]]) -> str:
    out = []
    for removed, added in changes:
        if removed and added:
            out.append(f'"{removed}" became "{added}"')
        elif added:
            out.append(f'added "{added}"')
        else:
            out.append(f'removed "{removed}"')
    return "; ".join(out)


async def _prepare_patch(*, base: Dict[str, Any], key: str, store: ProgramStore, tool_id: str, ctx: Dict[str, Any],
                         instructions: str, source_prompt: str, params: Dict[str, Any], loras: List[LoraInfo],
                         notes: Dict[str, str], lora_context: List[Dict[str, Any]], project_id: Optional[int],
                         profile_id: Optional[str], elaborate: bool = True, level: str = "",
                         exact: Optional[Dict[str, str]] = None,
                         started: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Carry a small prompt edit into the program it was prepared from: no enhancer, a
    short model call for a text edit (none for list items or [exact text]), and at most
    one repair. None (prepare anew) when the patch doesn't validate or runs out of time.
    started: when the prepare began (its deadline covers every call)."""
    began = time.monotonic()
    started = started if started is not None else began
    old, new = base["prompt"], source_prompt
    kind = edit_kind(old, new)
    enhanced = base.get("enhanced") or ""
    calls: List[Dict[str, Any]] = []
    source: Optional[str] = None
    if kind == "same":
        source = base["program"]
    elif kind == "lists":
        source = patch_lists(base["program"], old, new)
        if source is not None:
            for a, b in zip(_lists_and_frame(old)[1], _lists_and_frame(new)[1]):
                enhanced = enhanced.replace("[{" + a + "}]", "[{" + b + "}]")
    if source is None:
        changes = prompt_changes(old, new)
        program = base["program"]
        level = level or ("expand" if elaborate else "off")
        guide, images = (await writer_style(new, ctx, instructions, lora_context, project_id, profile_id, level)
                         if level != "off" else ("", []))
        messages = [
            *writer_messages(old, guide, images, ctx.get("model"), ctx.get("mode") or "prose",
                             params, loras, notes, elaborate, instructions, level),
            {"role": "assistant", "content": f"```python\n{program}```"},
            {"role": "user", "content": PATCH_NOTE.format(prompt=_numbered(new), changes=_describe_changes(changes),
                                                           numbered=_numbered_program(program))},
        ]
        t0 = time.monotonic()
        try:
            reply = await _ask_in_time(messages, project_id, started, max_tokens=_repair_cap(program))
        except asyncio.TimeoutError:
            log.info(f"[prompt-program] patch of {base.get('key')} ran out of time")
            return None
        if re.match(r"\s*\**\s*START OVER", reply or "", re.I):
            raise StartOver(f"the writer judged {key} a different prompt from {base.get('key')}")
        source = apply_line_edits(program, reply)
        if source is not None:
            source, _ = fix_quotes(source)  # a string wrapped onto the next line
        calls.append({"kind": "patch", "seconds": round(time.monotonic() - t0, 2), "chars": len(reply or ""),
                      "applied": source is not None})
        if source is None or source == program:
            return None
        kind = "text"
    fixed: List[str] = []
    for round_ in range(2):  # the patch, then at most one repair of it
        source, more = fix_patched(source, new)
        fixed += more
        try:
            check(source)
            # validate() runs the program some 50 times: in a worker thread, off the event loop
            checked = await asyncio.to_thread(validate, source, new, loras, set(params),
                                              enhanced if elaborate else plain_example(new), elaborate)
        except _CHECK_ERRORS as e:
            raise ProgramError(_check_error(e)) from None
        problems = checked["problems"]
        if not problems:
            break
        log.info(f"[prompt-program] patch ({kind}) rejected: {' '.join(problems)[:300]}")
        if kind != "text" or round_:
            return None
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": REPAIR_NOTE.format(problems="\n".join(problems),
                                                                     numbered=_numbered_program(source))}]
        t0 = time.monotonic()
        try:
            reply = await _ask_in_time(messages, project_id, started, max_tokens=_repair_cap(source))
        except asyncio.TimeoutError:
            log.info(f"[prompt-program] repair of the patch of {base.get('key')} ran out of time")
            return None
        edited = apply_line_edits(source, reply)
        calls.append({"kind": "repair", "seconds": round(time.monotonic() - t0, 2), "chars": len(reply or ""),
                      "applied": edited is not None and edited != source})
        if edited is None or edited == source:
            return None
        source = edited
    entry = _entry(key=key, tool_id=tool_id, ctx=ctx, elaborate=elaborate, level=level, prompt=new, enhanced=enhanced,
                   exact=exact, source=source, checked=checked, params=params, loras=loras)
    entry.update({
        "attempts": len(calls), "repairs": fixed, "patched_from": base.get("key"), "patch": kind,
        "lineage": base.get("lineage") or base.get("key"),
        "seconds": round(time.monotonic() - began, 2), "upsample_seconds": 0.0,
        "timing": {"enhance": 0.0, "calls": calls},
    })
    log.info(f"[prompt-program] patched {base.get('key')} → {key} ({kind}) in {entry['seconds']}s")
    return entry


def _truncated(reply: str) -> bool:
    """A reply cut off at the token cap: an open code fence that never closes."""
    return reply.count("```") == 1


def on_prepared(entry: Dict[str, Any], *, project_id: Optional[int], profile_id: Optional[str]) -> None:
    """Called once a program is stored, before prepare returns: start filling its
    option pools (and judgment prefill) in the background. Never blocks."""
    from prompt_programs.fluent import start_options  # fluent imports prepare
    start_options(entry, profile_id=profile_id, project_id=project_id)


def _notify_prepared(entry: Dict[str, Any], project_id: Optional[int], profile_id: Optional[str]) -> None:
    try:
        on_prepared(entry, project_id=project_id, profile_id=profile_id)
    except Exception as e:  # never fails a prepare
        log.warning(f"[prompt-program] on_prepared failed for {entry.get('key')}: {e}")


def _with_previous(content: Any, prev: Dict[str, Any]) -> Any:
    note = ("\n\nThe previous version of this prompt read:\n" + _numbered(prev.get("prompt") or "")
            + "\n\nIts program:\n```python\n" + prev["program"] + "```\nWrite the program for the new prompt, "
            "keeping the id, label, about and seeds of every pick whose part of the prompt didn't change.")
    if isinstance(content, list):
        return [{**content[0], "text": content[0]["text"] + note}, *content[1:]]
    return content + note


def _writer_cap(prompt: str) -> int:
    """Output tokens for a program: its prompt text plus a line per pick. Bounds a runaway
    reply (a repeating model) instead of letting it fill 4096 tokens."""
    return min(4096, 1800 + len(prompt) // 2)


def _repair_cap(source: str) -> int:
    """Edits rewrite a line or two: room for the longest line (usually emit()) plus a
    short one, so a rambling reply is cut off early."""
    longest = max((len(ln) for ln in source.splitlines()), default=0)
    return min(2048, 192 + (2 * longest) // 3)


async def _prepare_new(*, key: str, store: ProgramStore, tool_id: str, ctx: Dict[str, Any], instructions: str,
                       source_prompt: str, params: Dict[str, Any], loras: List[LoraInfo], notes: Dict[str, str],
                       lora_context: List[Dict[str, Any]], project_id: Optional[int],
                       profile_id: Optional[str], elaborate: bool = True, level: str = "",
                       exact: Optional[Dict[str, str]] = None, prev: Optional[Dict[str, Any]] = None,
                       started: Optional[float] = None) -> Dict[str, Any]:
    """source_prompt arrives with [exact text] already masked (see mask_exact). `prev`: the
    previous version of this prompt's program (a small edit whose patch didn't hold).

    One write, then fixes in place: phases and doubled phrases are fixed in code, and
    other problems go back as numbered-line edits instead of a full rewrite. If a repair
    doesn't settle it, the writer rewrites, told what was wrong. At most MAX_ATTEMPTS
    model calls, each within the prepare's deadline (started: when the prepare began, so a
    patch tried first or a session given up on counts against it); one that runs out keeps
    the best program so far."""
    began = time.monotonic()
    started = started if started is not None else began
    # One model call writes the program, its text already in this model's style: the
    # enhancer's per-model guide is the writer's own instructions, not a separate step.
    level = level or ("expand" if elaborate else "off")
    guide, images = (await writer_style(source_prompt, ctx, instructions, lora_context, project_id, profile_id, level)
                     if level != "off" else ("", []))
    # What validation compares the program with: the user's own words (kept-words mode).
    enhanced = "" if elaborate else plain_example(source_prompt)
    upsampled_at = time.monotonic()
    base = writer_messages(source_prompt, guide, images, ctx.get("model"), ctx.get("mode") or "prose",
                           params, loras, notes, elaborate, instructions, level)
    if prev and prev.get("program"):
        base[-1] = {**base[-1], "content": _with_previous(base[-1]["content"], prev)}
    cap = _writer_cap(source_prompt)
    calls: List[Dict[str, Any]] = []
    fixes: List[str] = []
    source: Optional[str] = None
    retry: Optional[Tuple[str, str]] = None   # (program, what was wrong) for a rewrite
    best: Optional[Tuple[str, Dict[str, Any]]] = None
    last_error = ""
    repaired = False  # the current source came from a repair, not a write
    timed_out = False
    while True:
        out_of_time = best is not None and time.monotonic() - started > PREPARE_SOFT_SECONDS
        if source is None:  # write the program (again)
            if len(calls) >= MAX_ATTEMPTS or out_of_time:
                break
            t0 = time.monotonic()
            msgs = base + ([{"role": "assistant", "content": retry[0]}, {"role": "user", "content": retry[1]}]
                           if retry else [])
            try:
                reply = await _ask_in_time(msgs, project_id, started, max_tokens=cap)
            except asyncio.TimeoutError:
                timed_out = True
                break
            calls.append({"kind": "write", "seconds": round(time.monotonic() - t0, 2), "chars": len(reply or "")})
            if _truncated(reply):
                last_error = "The reply was cut off: it was far too long."
                retry = (reply[:2000], "Your reply was cut off because it was far too long. Write the program "
                         "again, short: write the text once in emit() and give each pick 1 to 3 seeds.")
                continue
            source, repaired = drop_name_options(extract_code(reply), source_prompt), False
        source, fixed = fix_written(source, source_prompt, loras)
        fixes += fixed
        try:
            check(source)
            checked = await asyncio.to_thread(validate, source, source_prompt, loras, set(params), enhanced, elaborate)
        except _CHECK_ERRORS as e:
            problems = [_check_error(e)]
        else:
            problems = checked["problems"]
            if best is None or len(problems) <= len(best[1]["problems"]):
                best = (source, checked)
        if not problems or len(calls) >= MAX_ATTEMPTS:
            break
        if best is not None and time.monotonic() - started > PREPARE_SOFT_SECONDS:
            log.info(f"[prompt-program] out of time after {len(calls)} call(s): keeping the best program")
            break
        last_error = "\n".join(problems)
        log.info(f"[prompt-program] attempt {len(calls)} rejected: {last_error[:300]}")
        retry = (f"```python\n{source}```", f"That program has a problem:\n{last_error}\nReply with the corrected program only.")
        if repaired:  # a repair didn't settle it: rewrite, told what was wrong
            source = None
            continue
        t0 = time.monotonic()
        try:
            reply = await _ask_in_time(base + [{"role": "assistant", "content": f"```python\n{source}```"},
                                               {"role": "user", "content": REPAIR_NOTE.format(
                                                   problems=last_error, numbered=_numbered_program(source))}],
                                       project_id, started, max_tokens=_repair_cap(source))
        except asyncio.TimeoutError:
            timed_out = True
            break
        edited = apply_line_edits(source, reply)
        if edited is None and "```" in (reply or "") and "emit(" in reply and not _LINE_EDIT.search(reply):
            edited = extract_code(reply)  # it wrote the whole program instead: take it
        if edited == source:
            edited = None
        calls.append({"kind": "repair", "seconds": round(time.monotonic() - t0, 2), "chars": len(reply or ""),
                      "applied": edited is not None})
        source, repaired = (drop_name_options(edited, source_prompt), True) if edited is not None else (None, False)
    if best is None:
        if timed_out:
            raise PrepareTimeout(f"Preparing took longer than {PREPARE_LIMIT_SECONDS:.0f} seconds, so it stopped. "
                                 "The chat model may be busy or too slow for this prompt.")
        raise PrepareFailed(last_error)
    if timed_out:
        log.info(f"[prompt-program] out of time after {len(calls)} call(s): keeping the best program")
    source, checked = best
    entry = _entry(key=key, tool_id=tool_id, ctx=ctx, elaborate=elaborate, level=level, prompt=source_prompt, enhanced=enhanced,
                   exact=exact, source=source, checked=checked, params=params, loras=loras)
    entry.update({
        "attempts": len(calls), "repairs": fixes,
        "lineage": (prev.get("lineage") or prev.get("key")) if prev else key,
        "seconds": round(time.monotonic() - began, 2), "upsample_seconds": round(upsampled_at - began, 2),
        "timing": {"enhance": round(upsampled_at - began, 2), "calls": calls},
    })
    log.info(f"[prompt-program] prepared {key} ({entry['mode']}) in {entry['seconds']}s "
             f"(upsample {entry['upsample_seconds']}s, model calls {[c['kind'] for c in calls]}, "
             f"{len(entry['choices'])} choices, {len(fixes)} fixed in code)")
    return entry


def fix_written(source: str, prompt: str, loras: Sequence[LoraInfo]) -> Tuple[str, List[str]]:
    """The fixes in code a written (or repaired) program gets before validation, in order.
    Returns the source and what changed."""
    notes: List[str] = []
    for fix in (fix_quotes, fix_generated_refs, lambda x: fix_one_item_lists(x, prompt),
                lambda x: fix_list_sources(x, prompt), fix_phases, fix_unplaced, fix_brackets,
                lambda x: fix_requested(x, prompt), lambda x: fix_duplicates(x, prompt),
                lambda x: fix_trigger_words(x, loras, prompt)):
        source, more = fix(source)
        notes += more
    return source, notes


def fix_patched(source: str, prompt: str) -> Tuple[str, List[str]]:
    """The fixes in code a program patched for a prompt edit gets (fewer than a fresh write:
    what the edit didn't touch was already fixed)."""
    source = drop_name_options(source, prompt)
    notes: List[str] = []
    for fix in (fix_generated_refs, lambda x: fix_one_item_lists(x, prompt), lambda x: fix_list_sources(x, prompt),
                fix_phases, lambda x: fix_requested(x, prompt)):
        source, more = fix(source)
        notes += more
    return source, notes


def _entry(*, key: str, tool_id: str, ctx: Dict[str, Any], elaborate: bool, prompt: str, enhanced: str, level: str = "",
           exact: Optional[Dict[str, str]], source: str, checked: Dict[str, Any], params: Dict[str, Any],
           loras: Sequence[LoraInfo]) -> Dict[str, Any]:
    info = checked["info"]
    normalize_sources(info, prompt)
    return {
        "key": key, "version": PREPARE_VERSION, "prompt": prompt, "tool_id": tool_id,
        "mode": ctx.get("mode"), "elaborate": bool(elaborate),
        "enhance": level or ("expand" if elaborate else "off"), "enhanced": enhanced, "exact": exact or {},
        "program": source, "choices": info["choices"], "groups": info["groups"],
        "params": {n: params[n] for n in info["params"] if n in params},
        "loras": [vars(lo) for lo in loras],
        "lora_choices": {c["id"]: c["options"] for c in info["choices"] if c["kind"] == "lora"},
        "example": realized_text(info["example"]),
        "warnings": checked["problems"] + checked.get("notes", []), "created_at": time.time(),
        "protocol": "text",
    }


def draw_seed(seed: Any = None) -> int:
    """The seed for a run's draws. It is its own seed, never the image's: the same
    image seed with new draws, or the same draws with a new image seed, are both
    useful. Missing or negative means fresh draws."""
    try:
        s = int(seed)
    except (TypeError, ValueError):
        s = -1
    return s % (2**31) if s >= 0 else random.randrange(0, 2**31)


def realize(entry: Dict[str, Any], *, seed: int, pins: Optional[Dict[str, Any]] = None,
            fixed: Optional[Dict[str, Any]] = None, edits: Optional[Dict[str, Any]] = None,
            triggers: bool = True, profile_id: Optional[str] = None, project_id: Optional[int] = None,
            revision: Optional[Dict[str, Any]] = None, runtime: Any = None, unmask: bool = True) -> RunResult:
    """One generation's prompt from a prepared program. Programs with pick specs draw
    with generated options (prompt_programs.fluent); pass a recorded `revision` to replay
    its pools, or a `runtime` to draw with a given options service (evaluations, tests).
    unmask=False leaves [exact text] as its [EXACT_n] tokens, for steps a model reads
    (the fix judge); put it back with unmask_exact(prompt, entry["exact"])."""
    loras = [LoraInfo(**lo) for lo in entry.get("loras") or []]
    if not triggers:  # the prompt menu's "Trigger words" is off: a picked LoRA adds none
        loras = [LoraInfo(lo.name, lo.path, lo.weight, "") for lo in loras]
    clean_pins = {str(k): [str(x) for x in (v if isinstance(v, list) else [v])] for k, v in (pins or {}).items() if v}
    clean_edits = {str(k): v for k, v in (edits or {}).items() if isinstance(v, dict)}
    params = set(entry.get("params") or {}) or None
    # Programs with pick specs take the phased draw path; programs prepared before it
    # run exactly as they always have.
    if uses_draws(entry["program"]):
        from prompt_programs.fluent import runtime_for
        rt = runtime or runtime_for(entry, edits=clean_edits, profile_id=profile_id, project_id=project_id,
                                    revision=revision)
        result = draw(entry["program"], seed, clean_pins, loras, params, fixed or None, clean_edits or None,
                      options=rt.options)
    else:
        result = run(entry["program"], seed, clean_pins, loras, params, fixed or None, clean_edits or None)
    if unmask and entry.get("exact"):  # the user's [exact text], straight to the image model
        result.prompt = unmask_exact(result.prompt, entry["exact"])
    return result


__all__ = ["ensure_program", "realize", "draw_seed", "realized_text", "tidy_text", "ProgramError",
           "DrawAborted"]
