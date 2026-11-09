"""Prepare: turn a prompt into a program with one LLM call, then cache it.

Everything that shapes the program is part of its cache key, so asking again with the
same prompt, tool, LoRAs and parameters never calls the model. Realizing (running the
program for one generation) needs no model at all.
"""

from __future__ import annotations

import ast
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
from prompt_programs.draws import DrawAborted, analyze, draw, legacy_program, uses_draws
from prompt_programs.store import ProgramStore, program_key
from prompt_programs.vocab import vocabulary

log = get_logger(__name__)

PREPARE_VERSION = "pp-37"
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
# The vocabulary's catalogue (the lists a pick may bind to with cls=) is part of the
# instructions; a vocabulary change changes the instructions, and so PREPARE_VERSION's key.
_INSTRUCTIONS = (Path(__file__).parent / "instructions.md").read_text("utf-8").replace(
    "{vocabulary}", vocabulary().catalogue())

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
                       elaborate: bool = True) -> str:
    parts = [f"User's prompt (lines numbered):\n{_numbered(prompt)}", ""]
    smart = smart_wildcards(prompt)
    if elaborate:
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


_PLACEHOLDER_NOTE = (
    "This prompt will become a template: some details vary from image to image. Keep every "
    "[...] placeholder exactly where it belongs in the sentence. Words in angle brackets, like "
    "\u27e8hairstyle\u27e9, name something that changes from image to image: write one concrete, "
    "vivid example of each in its place, without the brackets, and describe it only there. "
    "Where the prompt asks for something to vary, write one concrete example of it. Add no "
    "placeholders or brackets of your own: write everything else out in full."
)


def _needs_placeholder_note(prompt: str) -> bool:
    """Only prompts with placeholders or # lines need the note; without any, it invites
    the enhancer to invent placeholders ("[location]") of its own."""
    return bool(re.search(r"[\[{\u27e8]", prompt)) or any(ln.lstrip().startswith("#") for ln in prompt.splitlines())


def _for_enhancer(prompt: str) -> str:
    """{{name}} becomes \u27e8name\u27e9 for the enhancer, which writes one example of it in place.
    Weak enhancers asked to keep a {{name}} placeholder also describe it, then dump the
    placeholders at the end; writing the example is what they do well."""
    return re.sub(r"\{\{([^{}]+)\}\}", lambda m: "\u27e8" + m.group(1).strip() + "\u27e9", prompt)


def plain_example(prompt: str) -> str:
    """The user's text without its # lines, with the varying spots protected."""
    lines = [ln for ln in prompt.splitlines() if not ln.lstrip().startswith("#")]
    return protect_variable_spots("\n".join(lines).strip())


_KEEP_WORDS = """Rewrite an image prompt so it reads naturally, keeping the user's words.

- Keep every word the user wrote and their order where you can. Add only the small words a
  reader needs: "a", "and", "wearing", "with", commas. Add no description, detail, style or mood.
- Words in angle brackets, like \u27e8hairstyle\u27e9, name something that changes from image to
  image. Replace each with one short, concrete example of it (a few words), in its place.
- Keep every [{a|b}] and [text] placeholder exactly as written, brackets included.
- Lines starting with # are instructions for you: follow them, and leave them out.
{format}
Reply with only the rewritten prompt."""

_KEEP_FORMAT = {
    "keyword": "- This model reads comma-separated tags, not sentences: write the prompt as tags.",
}


async def keep_words(prompt: str, mode: str, project_id: Optional[int]) -> str:
    """Enhance off, step one: the user's own words as one readable example, with an
    example written for each smart wildcard. Nothing is added beyond joining words."""
    system = _KEEP_WORDS.replace("{format}", _KEEP_FORMAT.get(mode, "- Write it as plain sentences."))
    reply = await _ask_model([{"role": "system", "content": system},
                              {"role": "user", "content": protect_variable_spots(_for_enhancer(prompt))}], project_id)
    out = re.sub(r"^```\w*\s*|\s*```$", "", (reply or "").strip()).strip().strip('"')
    return out.replace("\u27e8", "").replace("\u27e9", "") or plain_example(prompt)


def protect_variable_spots(prompt: str) -> str:
    """{{name}} and inline {a|b} become protected placeholders, so the enhancer writes the
    rich text around them and leaves them where they are."""
    s = re.sub(r"\{\{([^{}]+)\}\}", lambda m: "[{{" + m.group(1) + "}}]", prompt)
    return re.sub(r"(?<![\[{])\{([^{}]+\|[^{}]+)\}(?![}\]])", lambda m: "[{" + m.group(1) + "}]", s)


async def upsample(prompt: str, ctx: Dict[str, Any], instructions: str, lora_context: List[Dict[str, Any]],
                   project_id: Optional[int], profile_id: Optional[str]) -> str:
    """Step one: the regular per-model enhancer (same style, checks and context as the
    per-image path) writes one rich example of the prompt."""
    from database_registry import get_database_registry
    from prompt_pipeline import _improve_with_verbatim_protection

    db = get_database_registry().get_database(profile_id)
    note = _PLACEHOLDER_NOTE if _needs_placeholder_note(prompt) else ""
    out = await _improve_with_verbatim_protection(
        db, protect_variable_spots(_for_enhancer(prompt)),
        instructions="\n".join(x for x in (instructions, note) if x),
        model=ctx.get("model"), project_id=project_id, lora_context=lora_context, **ctx["enhance"],
    )
    return out.replace("\u27e8", "").replace("\u27e9", "")


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
                       project_id: Optional[int], profile_id: Optional[str]) -> Tuple[str, List[Tuple[int, str]]]:
    """This model's prompt-style guide (the enhancer's per-model guidance, with this
    request's images, canvas, protected text and LoRAs filled in) and the source images it
    refers to. No model call."""
    from database_registry import get_database_registry
    from routes.prompt_enhancement import ImprovePromptRequest, style_guide

    request = ImprovePromptRequest(prompt=prompt, instructions=instructions or None, model=ctx.get("model") or None,
                                   project_id=project_id, lora_context=lora_context or [], **(ctx.get("enhance") or {}))
    db = get_database_registry().get_database(profile_id)
    async with db.async_session_maker() as session:
        guide, images, _mode = await style_guide(request, session)
    return guide, images


def writer_messages(prompt: str, guide: str, images: Sequence[Tuple[int, str]], model_name: Optional[str], mode: str,
                    params: Dict[str, Dict[str, Any]], loras: Sequence[LoraInfo], notes: Dict[str, str],
                    elaborate: bool, instructions: str = "") -> List[Dict[str, Any]]:
    system = _INSTRUCTIONS + (_STYLE_NOTE + guide.strip() if elaborate and guide else "")
    user = build_user_message(prompt, model_name, mode, params, loras, notes, elaborate)
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


async def _ask_repair(messages: List[Dict[str, str]], project_id: Optional[int], max_tokens: int = 1024) -> str:
    """Edits that fix a program in place (its own name so timing can tell it apart)."""
    return await _ask_model(messages, project_id, max_tokens=max_tokens)


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


def _smart_choice(info: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    want = smart_id(name)
    for c in info["choices"]:
        if c["kind"] == "pick" and (c["id"] == want or smart_id(c["label"]) == want):
            return c
    words = set(want.split("_"))  # a pick that says it is this wildcard: about="the local street food"
    for c in info["choices"]:
        if c["kind"] == "pick" and c.get("source") != "list" and c.get("about") and words <= _words(c["about"]):
            return c
    head = [w for w in want.split("_") if len(w) > 2][-1:]  # {{happy expression}} → a pick about her expression
    for c in info["choices"]:
        if (head and c["kind"] == "pick" and c.get("source") != "list"
                and head[0] in _words(" ".join([c["id"].replace("_", " "), c.get("label") or "", c.get("about") or ""]))):
            return c
    return None


def _bare(text: str) -> str:
    """A phrase without its article, case or trailing punctuation: "A brand." is the
    wildcard {{brand}}'s own name, not an example of it."""
    t = re.sub(r"\s+", " ", str(text).strip().lower()).strip(" .,;:!\"'")
    t = re.sub(r"^(?:a|an|the|some|any)\s+", "", t)
    return re.sub(r"(?<=[a-z])s$", "", t) if len(t) > 3 else t


def is_name_of(option: str, name: str) -> bool:
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


MAX_ADDED = 3


def _detail(pid: str) -> str:
    """One detail per person: girl[1].hair, girl[2].hair and hair_2 are all "hair"."""
    return re.sub(r"\[[^\]]*\]|\{[^}]*\}|\d+", "", pid).strip("_.") or pid


def _wildcard_ids(tree: ast.AST, prompt: str) -> Set[str]:
    """Ids of the picks validation takes for the prompt's {{name}} wildcards."""
    names = smart_wildcards(prompt)
    if not names:
        return set()
    choices = []
    for _, call in _pick_assigns(tree):
        pid = _const(call.args[0]) if call.args else _const(_kw(call, "id"))
        if isinstance(pid, str):
            about = _kw(call, "about")
            choices.append({"kind": "pick", "id": pid, "label": str(_const(_kw(call, "label")) or pid),
                            "source": _const(_kw(call, "source")) or "text",
                            "about": ast.unparse(about) if about is not None else ""})
    info = {"choices": choices}
    return {c["id"] for c in (_smart_choice(info, n) for n in names) if c}


def trim_added(source: str, prompt: str = "") -> Tuple[str, List[str]]:
    """More than MAX_ADDED details the user didn't ask for: the extras become fixed text (their
    first seed), so the prompt reads the same and the choices stay few. A detail the user didn't
    ask for is any pick that isn't a user list, a {{wildcard}}, something a # line asks to vary,
    or hidden, marked added=True or not; one per person counts once (girl[1].hair, girl[2].hair).
    Picks the writer marked added go first, the latest first. A pick whose about= names another
    pick, or that keys on one (by=), stays: one fixed seed would be wrong for the other's values."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, []
    comments = _comment_lines(prompt)
    wild = _wildcard_ids(tree, prompt)
    extra: List[Tuple[ast.Call, str, bool, bool]] = []  # (call, detail, marked added, can freeze)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "pick"):
            continue
        pid = _const(node.args[0]) if node.args else _const(_kw(node, "id"))
        if not isinstance(pid, str):
            pid = ast.unparse(node.args[0]) if node.args else "?"
        if (_const(_kw(node, "source")) == "list" or _const(_kw(node, "hidden")) is True or pid in wild
                or _const(_kw(node, "line")) in comments):
            continue
        seed = _kw(node, "seed")
        about = _kw(node, "about")
        frozen_ok = (isinstance(seed, ast.List) and bool(seed.elts) and isinstance(seed.elts[0], ast.Constant)
                     and isinstance(seed.elts[0].value, str) and _kw(node, "by") is None
                     and not (isinstance(about, ast.JoinedStr)
                              and any(isinstance(v, ast.FormattedValue) for v in about.values)))
        extra.append((node, _detail(pid), _const(_kw(node, "added")) is True, frozen_ok))
    details = list(dict.fromkeys(d for _, d, _, _ in extra))
    if len(details) <= MAX_ADDED:
        return source, []
    # the details to make fixed: marked-added ones first, then unmarked, each the latest first
    order = sorted(details, key=lambda d: (not any(m for _, x, m, _ in extra if x == d),
                                           -min(n.lineno for n, x, _, _ in extra if x == d)))
    drop: Set[str] = set()
    for d in order:
        if len(details) - len(drop) <= MAX_ADDED:
            break
        if all(ok for _, x, _, ok in extra if x == d):
            drop.add(d)
    pos = _offsets(source)
    edits, notes = [], []
    for node, d, _, _ in extra:
        if d not in drop:
            continue
        value = _kw(node, "seed").elts[0].value  # type: ignore[union-attr]
        edits.append((pos(node.lineno, node.col_offset), pos(node.end_lineno, node.end_col_offset),
                      json.dumps(value, ensure_ascii=False)))
        name = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else d
        notes.append(f'pick("{name}") made fixed text: more than {MAX_ADDED} added details')
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source, notes


# --------------------------------------------------------------------------- what the user stated

# English function words: grammar, not something the user stated about the image.
_STATED_STOP = {"a", "an", "the", "and", "or", "but", "nor", "so", "of", "in", "on", "at", "to", "for", "with", "by",
                "from", "into", "onto", "over", "under", "about", "through", "near", "off", "up", "down", "out",
                "is", "are", "was", "were", "be", "been", "being", "has", "have", "had", "do", "does", "did",
                "her", "his", "its", "their", "our", "my", "your", "she", "he", "they", "it", "we", "you", "him", "them",
                "this", "that", "these", "those", "there", "here", "as", "than", "then", "very", "some", "each",
                "while", "who", "which", "whose", "where", "when", "not", "no", "all", "any", "both", "such"}
# Words only English uses this way. A prompt with none of them (or with letters English
# doesn't use) can't be told apart into stated words and grammar, so nothing is frozen.
_ENGLISH_MARKERS = {"a", "an", "the", "and", "with", "in", "on", "of", "at", "to", "by", "for", "her", "his",
                    "she", "he", "their", "this", "that", "is", "are", "wearing", "who", "which", "from", "into"}
# Grammar words of other languages that English prompts don't use: one of these means the
# prompt's function words are unknown, so nothing is treated as stated.
_FOREIGN_MARKERS = {"der", "das", "und", "ein", "eine", "einer", "einem", "einen", "mit", "von", "ist", "sie",
                    "le", "la", "les", "et", "une", "des", "du", "avec", "el", "los", "las", "y", "con", "una",
                    "il", "di", "che", "och", "het", "een"}


def _stem(word: str) -> str:
    """A crude stem, enough to match "thirties"/"thirty" and "rainy"/"rain"."""
    w = word.lower()
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        w = w[:-1]
    for suffix in ("ing", "ed", "y"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            return w[: -len(suffix)]
    return w


def _stems(text: str) -> Set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())}


def _english(text: str) -> bool:
    """Whether a prompt reads as English, so its function words are known."""
    words = re.findall(r"[^\W\d_]+", text.lower())
    if sum(1 for w in words if not w.isascii()) * 10 > len(words):  # letters English doesn't use
        return False
    found = set(words)
    return len(found & _ENGLISH_MARKERS) >= 2 and not found & _FOREIGN_MARKERS


def stated_words(prompt: str) -> Dict[str, str]:
    """stem → word for what the user stated: their words outside {a|b} lists, {{name}}
    wildcards, [protected text] and # lines. These stay fixed in every image."""
    text = "\n".join(ln for ln in prompt.splitlines() if not ln.lstrip().startswith("#"))
    text = re.sub(r"\{\{[^{}]*\}\}|\{[^{}]*\}|\[[^\[\]]*\]", " ", text)
    out: Dict[str, str] = {}
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w not in _STATED_STOP and len(w) > 1:
            out.setdefault(_stem(w), w)
    return out


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


def _requested(call: ast.Call, prompt: str) -> bool:
    """A pick the user asked for: a {{name}} wildcard, a list, or variety a # line asks for."""
    if _const(_kw(call, "source")) == "list":
        return True
    if _const(_kw(call, "line")) in _comment_lines(prompt):
        return True
    pid = _const(call.args[0]) if call.args else _const(_kw(call, "id"))
    label = _const(_kw(call, "label"))
    names = {smart_id(n) for n in smart_wildcards(prompt)}
    return (isinstance(pid, str) and smart_id(pid) in names) or (isinstance(label, str) and smart_id(label) in names)


def _seeds(call: ast.Call) -> List[str]:
    seed = _kw(call, "seed")
    if not isinstance(seed, ast.List):
        return []
    return [str(e.value) for e in seed.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def lost_stated(source: str, prompt: str, enhanced: str) -> Dict[str, str]:
    """stem → word for words the user stated (and the example kept) that the program's
    fixed text never says: a pick swallowed them, or they were dropped. Words a user
    list or a pick the user asked for covers don't count."""
    if not uses_draws(source) or not _english(prompt):  # unclassifiable words: report nothing
        return {}
    stated = stated_words(prompt)
    if not stated:
        return {}
    from prompt_programs.draws import fixed_text
    try:
        fixed = fixed_text(source)
        tree = ast.parse(source)
    except (ProgramError, SyntaxError, RecursionError):
        return {}
    have = _stems(re.sub(r"\[[^\[\]]*\]", " ", fixed))
    comments = _comment_lines(prompt)
    for _, call in _pick_assigns(tree):
        # A user list's options, and what a # line asked to vary, may carry the user's
        # words. A {{name}} wildcard covers only its own spot: words around it stay fixed.
        if _const(_kw(call, "source")) == "list" or _const(_kw(call, "line")) in comments:
            opts = call.args[1] if len(call.args) > 1 else _kw(call, "options")
            texts = _seeds(call) + ([str(e.value) for e in opts.elts if isinstance(e, ast.Constant)]
                                    if isinstance(opts, ast.List) else [])
            for t in texts:
                have |= _stems(t)
    example = _stems(re.sub(r"\[\{.*?\}\]", " ", enhanced)) if enhanced else set(stated)
    return {k: w for k, w in stated.items() if k in example and k not in have}


def fix_stated(source: str, prompt: str, enhanced: str) -> Tuple[str, List[str]]:
    """A pick the writer added (or hid) whose example holds something the user stated
    ("in her thirties" made an age pick) turns back into fixed text, its first seed:
    what the user wrote is never drawn away."""
    stated = stated_words(prompt)
    if not stated or not uses_draws(source) or not _english(prompt):  # never freeze words it can't classify
        return source, []
    lost = lost_stated(source, prompt, enhanced)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, []
    # Fixed text each variable is emitted next to: a seed of the user's words standing
    # there too means the pick repeats them, and its other values would contradict them.
    beside: Dict[str, str] = {}
    for call in ast.walk(tree):
        if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "emit":
            text = " ".join(a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)).lower()
            for a in call.args:
                if isinstance(a, ast.Name):
                    beside[a.id] = beside.get(a.id, "") + " " + text
    pos = _offsets(source)
    edits: List[Tuple[int, int, str]] = []
    notes: List[str] = []
    fixed_vars: Dict[str, str] = {}
    for var, call in _pick_assigns(tree):
        seeds = _seeds(call)
        if _requested(call, prompt) or not seeds:
            continue
        mine = _stems(seeds[0]) & set(stated)
        repeated = bool(mine) and var is not None and len(seeds[0].split()) >= 2 and seeds[0].lower() in beside.get(var, "")
        if not (mine & set(lost) or repeated):
            continue
        edits.append((pos(call.lineno, call.col_offset), pos(call.end_lineno, call.end_col_offset),
                      json.dumps(seeds[0], ensure_ascii=False)))
        name = _const(call.args[0]) if call.args else var
        words = ", ".join(f'"{stated[k]}"' for k in sorted(mine))
        notes.append(f'pick("{name}") made fixed text: the user wrote {words}')
        if var:
            fixed_vars[var] = seeds[0]
    # The same words already standing in an emit() next to the variable: drop the variable there.
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and getattr(call.func, "id", None) == "emit"):
            continue
        text = " ".join(a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)).lower()
        for i, a in enumerate(call.args):
            if isinstance(a, ast.Name) and a.id in fixed_vars and fixed_vars[a.id].lower() in text and i > 0:
                prev = call.args[i - 1]
                edits.append((pos(prev.end_lineno, prev.end_col_offset), pos(a.end_lineno, a.end_col_offset), ""))
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source, notes


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
    fixed copy, unless it holds words the user wrote (the pick is what's wrong then).
    Returns the source and what changed."""
    stated = set(stated_words(prompt)) if prompt else set()
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
                    if stated and _stems(phrase) & stated:
                        continue  # the user's own words stay
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
        names = {smart_id(str(_const(node.args[0]) or "")), smart_id(str(_const(_kw(node, "label")) or ""))}
        if names & set(wild) or any(is_name_of(opts.elts[0].value, n) for n in wild.values()):
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


def _word_count(text: str) -> int:
    return len(re.findall(r"[\w'-]+", re.sub(r"\[\{.*?\}\]", " x ", text)))


# Words that only ever name models or LoRA kinds. Not ones that are also ordinary words
# ("XL" shirts, "pony", "in flux"): a LoRA named only that is left alone.
_MODEL_WORDS = {"krea", "sdxl", "lora", "loras", "qwen", "hunyuan", "ltx", "hidream", "lycoris", "locon"}


def _name_like(name: str) -> bool:
    """A LoRA name that can't be ordinary prompt text ("ultra real krea2", "KNP 000003000",
    "facial krea"), unlike one that is ("Dress", "Curtain bangs"): only these are cut or flagged."""
    words = re.findall(r"[A-Za-z0-9_.]+", name)
    return any(re.search(r"\d|_", w) or w.lower() in _MODEL_WORDS for w in words)


def _mentions(text: str, name: str) -> bool:
    return re.search(rf"(?i)(?<![\w]){re.escape(name)}(?![\w])", text) is not None


def drop_lora_names(text: str, loras: Sequence[LoraInfo], prompt: str) -> str:
    """LoRA names the example text picked up, cut out (unless the user wrote them): the
    writer copies that text, and every image would carry them."""
    for lo in sorted(loras, key=lambda x: -len(x.name)):
        if _name_like(lo.name) and not _mentions(prompt, lo.name):
            text = re.sub(rf"(?i)(?<![\w]){re.escape(lo.name)}(?![\w])", "", text)
    text = re.sub(r"\s*,(\s*,)+", ",", text)   # ", ," left where a name stood
    text = re.sub(r"\s+([,.])", r"\1", text)
    text = re.sub(r",([.;:!?])", r"\1", text)
    text = re.sub(r"^\s*,\s*", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


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


def _lora_marks(names: Sequence[str]) -> Set[str]:
    """The word that tells each LoRA of a set apart ("acups" in "KREA2 bodyshop acups v1"),
    with the words they all share left out."""
    words = [_words(n) for n in names]
    common = set.intersection(*words) if words else set()
    marks: Set[str] = set()
    for w in words:
        rest = w - common
        if len(rest) == 1:
            marks |= rest
    return marks


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
    if uses_draws(source):  # phases and dependencies, checked on the code (raises ProgramError)
        analyze(source, strict=True)
        draw(source, 11, None, loras, params)  # and the draw path runs it
    info = discover(source, loras, params)
    samples = [run(source, s, None, loras, params) for s in (11, 23, 37, 51)]
    problems: List[str] = []   # broken or visibly wrong: one repair, as line edits
    notes: List[str] = []      # quality hints: logged and shown in dev mode, never a retry
    if enhanced:
        want = _word_count(enhanced)
        got = min(_word_count(realized_text(r.prompt)) for r in samples)
        if elaborate and want >= 20 and got < 0.6 * want:
            notes.append(f"The prompts your program emits are too short ({got} words; the enhanced prompt has {want}). "
                            "Copy the enhanced prompt's full text into emit() and only swap the parts that vary.")
        if not elaborate:  # kept words: every word of the example outside the picks survives
            in_options = set().union(*(_words(o) for c in info["choices"] for o in c.get("options") or []), set())
            fixed = _words(re.sub(r"\[\{.*?\}\]", " ", enhanced)) - in_options
            emitted = set().union(*(_words(r.prompt) for r in samples))
            lost = sorted(fixed - emitted)
            if lost:
                notes.append("Keep the user's words: these are missing from what you emit: "
                                + ", ".join(f'"{w}"' for w in lost) + ". Copy the prompt's text into emit() as written.")
    if any(re.search(r"<<<|>>>|^\s*[\"']{3}", r.prompt) for r in samples):
        problems.append("Emit only the prompt text itself, with no quote marks or <<< >>> around it.")
    if any(re.search(r"\{[^{}]*\|[^{}]*\}", r.prompt) or "[{" in r.prompt for r in samples):
        problems.append("Replace every {a|b} list with its pick's value; never emit the braces.")
    if elaborate:
        lost = lost_stated(source, prompt, enhanced)
        if lost:
            words = ", ".join(f'"{w}"' for w in lost.values())
            notes.append(f"The user wrote {words}, but the text your program always emits doesn't say it: it is "
                            "inside a pick, or left out. What the user states stays fixed text in emit(), in their "
                            "words; make picks only of what the user's prompt leaves open.")
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
    for r in samples:  # a choice that never reaches the prompt does nothing
        text = r.prompt.lower()
        for d in r.draws:
            if d.kind == "pick" and not d.hidden and d.value and str(d.value).lower() not in text:
                missing.setdefault(d.id, str(d.value))
    for r in samples:  # LoRAs work by being on; a name in the text is noise to the image model
        text = r.prompt.lower()
        named = [n for n in dict.fromkeys([lu.name for lu in r.loras] + [lo.name for lo in loras])
                 if _name_like(n) and _mentions(text, n) and not _mentions(prompt, n)]
        if named:
            problems.append(f'Don\'t write LoRA names into the prompt ("{named[0]}"). pick_lora() already turns the LoRA on; '
                            "emit only words that describe the image.")
            break
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
        marks = _lora_marks(names)
        for c in info["choices"]:
            if c["id"] in named:
                continue
            opts = {o.lower().strip() for o in c.get("options") or []}
            # a list made of the LoRAs' own names (acups, torpedo, tuberous…), not one that
            # happens to share a word or two with them ("long", "short")
            if c.get("kind") == "pick" and len(opts) >= 3 and opts <= marks:
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
        for d in r.draws:
            v = str(d.value or "").lower().strip()
            if d.kind == "pick" and not d.hidden and len(v.split()) >= 2 and text.count(v) > 1:
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
            problems.append(f'{{{{{name}}}}} is a smart wildcard: make it pick("{smart_id(name)}", about=..., seed=[1 to 3 examples], label=<one or two words>, phase=..., line=...) and emit its value where {{{{{name}}}}} stands.')
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
            c = _smart_choice(info, name)
            if c and c["id"] in listed:
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
    return {"info": info, "problems": list(dict.fromkeys(problems)), "notes": list(dict.fromkeys(notes))}


def normalize_sources(info: Dict[str, Any], prompt: str) -> None:
    """Weak models mark things the user asked for as added. If a choice's name appears in
    the user's text, it came from the text, and gets the line it appears on."""
    lines = [ln.lower() for ln in prompt.splitlines()]
    for name in smart_wildcards(prompt):  # the user's own {{name}}: from their text, on its line
        c = _smart_choice(info, name)
        if c:
            c["source"], c["wildcard"] = "text", name
            c["line"] = next((i + 1 for i, ln in enumerate(lines) if "{{" + name.lower() in ln.replace("{{ ", "{{")), c.get("line"))
    for c in info["choices"]:
        if c.get("source") == "list":
            continue
        keys = {c["label"].lower(), (c.get("attr") or c["id"]).replace("_", " ").lower()}
        keys |= {k[:-1] for k in keys if k.endswith("s")}  # hairstyles → hairstyle
        for i, ln in enumerate(lines):
            if any(re.search(rf"\b{re.escape(k)}", ln) for k in keys if len(k) > 2):
                c["source"] = "text"
                c.setdefault("line", i + 1)
                break


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


async def ensure_program(*, prompt: str, tool_id: str, ctx: Dict[str, Any], instructions: str,
                         lora_items: Sequence[Dict[str, Any]], project_id: Optional[int],
                         profile_id: Optional[str], cache_only: bool = False, force: bool = False,
                         elaborate: bool = True, lora_notes: bool = True,
                         base_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The prepared program for these inputs, from cache or by asking the model.
    elaborate (Enhance on): the per-model enhancer writes a rich example first and the
    program keeps it. Off: the program keeps the user's own words. base_key: the program
    the editor showed before this prompt (an edit continues from it when it fits)."""
    from prompt_pipeline import _profile_wildcards_and_segments

    wildcards, segments = _profile_wildcards_and_segments(profile_id)
    source_prompt = expand_named_lists(prompt, wildcards, segments).strip()
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
    lora_context = [{"name": lo.name, "trigger_words": [t.strip() for t in lo.trigger.split(",") if t.strip()],
                     "notes": notes.get(lo.name, "")} for lo in candidates if lo.on and (lo.trigger or notes.get(lo.name))]
    # The canvas only matters to layout formats (Ideogram), which have no programs;
    # leaving it out keeps a prepared program valid across sizes.
    enhance = {k: v for k, v in (ctx.get("enhance") or {}).items() if k not in ("width", "height")}
    parts = {
        "v": PREPARE_VERSION, "vocab": vocabulary().version, "tool": tool_id, "model": ctx.get("model"),
        "mode": ctx.get("mode"), "enhance": enhance, "instructions": instructions,
        # on/off reaches the key only through `notes` (the on LoRAs' trigger words and notes):
        # switching a plain LoRA on or off doesn't need a new program
        "params": sorted(params), "loras": [{k: v for k, v in vars(lo).items() if k != "on"} for lo in loras],
        "notes": lora_context,
        "lora_notes": {lo.name: notes[lo.name] for lo in loras if notes.get(lo.name)},  # what the writer reads
        "elaborate": bool(elaborate),
        "writer": await _writer_fingerprint(project_id),  # another writer model writes another program
    }
    key = program_key({**parts, "prompt": source_prompt})
    context = program_key(parts)  # the same editing context, whatever the prompt says
    store = _store(profile_id)
    cached = None if force else store.get(key)
    if cached and not cache_only and (store.recent(context) or [None])[0] != key:
        store.remember(context, key)  # back to this prompt: the next small edit patches it
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
                    profile_id=profile_id, elaborate=bool(elaborate), exact=exact)
        running = asyncio.ensure_future(_prepare(context=context, force=force, base_key=base_key, **args))
        _in_flight[flight] = running
        running.add_done_callback(lambda _t, k=flight: _in_flight.pop(k, None) if _in_flight.get(k) is _t else None)
    return await asyncio.shield(running)


_in_flight: Dict[Tuple[str, str, bool], "asyncio.Future[Dict[str, Any]]"] = {}


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


NARROW_RESERVE = 3.0   # seconds of the prepare deadline left for storing the entry after narrowing


async def _narrow(entry: Dict[str, Any], store: ProgramStore, project_id: Optional[int], started: float) -> None:
    """Bound picks narrowed by the user's words (where=, or a wildcard's own name): one
    cached model call per (list, words), see narrow.py. Never fails the prepare: it gets only
    what's left of the prepare's deadline, and with too little left the picks stay unnarrowed
    rather than the prepared program being lost to the timeout."""
    from prompt_programs.narrow import NARROW_SECONDS, NarrowCache, narrow_entry
    left = PREPARE_LIMIT_SECONDS - (time.monotonic() - started) - NARROW_RESERVE
    if left < 2.0:
        log.info("[prompt-program] no time left to narrow the bound picks; they draw from their whole lists")
        return
    t0 = time.monotonic()
    notes = await narrow_entry(entry, NarrowCache(store.root / "narrow"), _ask_model, project_id,
                               seconds=min(NARROW_SECONDS, left))
    if entry.get("filters"):
        entry.setdefault("timing", {})["narrow"] = round(time.monotonic() - t0, 2)
        entry["warnings"] = list(entry.get("warnings") or []) + notes


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
            entry["context"] = context
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
    entry = None
    if base is not None:
        try:
            entry = await _prepare_patch(base=base, **args)
        except StartOver as e:
            log.info(f"[prompt-program] starting over: {e}")
            base = None  # a new prompt: its own program, lineage and options
        except ProgramError as e:
            log.info(f"[prompt-program] patch from {base.get('key')} failed: {e}")
    if entry is None:
        # A small edit whose patch didn't hold is still the same prompt's next version: the
        # writer sees the old program and keeps what didn't change, and its options stay.
        entry = await _prepare_new(prev=base, **args)
    entry["context"] = context
    await _narrow(entry, store, args["project_id"], started if started is not None else time.monotonic())
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
    or None (prepare anew)."""
    if old == new:
        return "same"
    f0, l0 = _lists_and_frame(old)
    f1, l1 = _lists_and_frame(new)
    if f0 == f1 and len(l0) == len(l1):
        return "lists"
    # Whether a text change is an edit of this prompt or a different prompt is the patch
    # writer's call (it can answer START OVER). Here only prompts that share nothing much
    # are ruled out, so an unrelated prompt never costs a patch call.
    changes = prompt_changes(old, new)
    a, b = set(_prompt_words(old)), set(_prompt_words(new))
    if changes and a and b and len(a & b) / len(a | b) >= 0.3:
        return "text"
    return None


def _patch_base(store: ProgramStore, context: str, prompt: str, base_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The program this prompt is an edit of. The one the editor says it showed (base_key)
    when it was prepared in this context and this prompt is an edit of it; otherwise the
    recent program in this context whose prompt is closest to this one (a guess: it can
    pick a sibling the user wasn't looking at)."""
    if base_key:
        e = store.get(base_key)
        if (e and e.get("context") == context and e.get("version") == PREPARE_VERSION and e.get("program")
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


_STOP = {"a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "with", "by", "from", "is", "are", "her",
         "his", "its", "their", "very"}


def stale_words(source: str, old: str, new: str, loras: Sequence[LoraInfo], params: Set[str]) -> List[str]:
    """Words the edit took out of the prompt that the patched program still writes
    ("an axe" became "a sword", but the seed still says axe)."""
    gone = set().union(*(_words(removed) for removed, _ in prompt_changes(old, new)), set()) - _words(new) - _STOP
    gone = {w for w in gone if len(w) > 2 and not w.startswith("exact")}
    if not gone:
        return []
    written = set()
    for s in (11, 23, 37, 51):
        written |= _words(run(source, s, None, loras, params).prompt)
    still = sorted(gone & written)
    return [f'The prompt no longer says "{w}", but the program still writes it. Change or remove it to match the '
            "edited prompt." for w in still]


async def _ask_patch(messages: List[Dict[str, Any]], project_id: Optional[int], max_tokens: int = 1024) -> str:
    """Edits that carry a prompt edit into its program (its own name for timing)."""
    return await _ask_model(messages, project_id, max_tokens=max_tokens)


async def _prepare_patch(*, base: Dict[str, Any], key: str, store: ProgramStore, tool_id: str, ctx: Dict[str, Any],
                         instructions: str, source_prompt: str, params: Dict[str, Any], loras: List[LoraInfo],
                         notes: Dict[str, str], lora_context: List[Dict[str, Any]], project_id: Optional[int],
                         profile_id: Optional[str], elaborate: bool = True,
                         exact: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Carry a small prompt edit into the program it was prepared from: no enhancer, a
    short model call for a text edit (none for list items or [exact text]), and at most
    one repair. None (prepare anew) when the patch doesn't validate."""
    started = time.monotonic()
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
        guide, images = (await writer_style(new, ctx, instructions, lora_context, project_id, profile_id)
                         if elaborate else ("", []))
        messages = [
            *writer_messages(old, guide, images, ctx.get("model"), ctx.get("mode") or "prose",
                             params, loras, notes, elaborate, instructions),
            {"role": "assistant", "content": f"```python\n{program}```"},
            {"role": "user", "content": PATCH_NOTE.format(prompt=_numbered(new), changes=_describe_changes(changes),
                                                           numbered=_numbered_program(program))},
        ]
        t0 = time.monotonic()
        reply = await _ask_patch(messages, project_id, max_tokens=_repair_cap(program))
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
        source, more = fix_patched(source, new, enhanced if elaborate else "")
        fixed += more
        check(source)
        checked = validate(source, new, loras, set(params), enhanced if elaborate else plain_example(new), elaborate)
        problems = checked["problems"] + (stale_words(source, old, new, loras, set(params)) if kind == "text" else [])
        if not problems:
            break
        log.info(f"[prompt-program] patch ({kind}) rejected: {' '.join(problems)[:300]}")
        if kind != "text" or round_:
            return None
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": REPAIR_NOTE.format(problems="\n".join(problems),
                                                                     numbered=_numbered_program(source))}]
        t0 = time.monotonic()
        reply = await _ask_repair(messages, project_id, max_tokens=_repair_cap(source))
        edited = apply_line_edits(source, reply)
        calls.append({"kind": "repair", "seconds": round(time.monotonic() - t0, 2), "chars": len(reply or ""),
                      "applied": edited is not None and edited != source})
        if edited is None or edited == source:
            return None
        source = edited
    entry = _entry(key=key, tool_id=tool_id, ctx=ctx, elaborate=elaborate, prompt=new, enhanced=enhanced,
                   exact=exact, source=source, checked=checked, params=params, loras=loras)
    entry.update({
        "attempts": len(calls), "repairs": fixed, "patched_from": base.get("key"), "patch": kind,
        "lineage": base.get("lineage") or base.get("key"),
        "seconds": round(time.monotonic() - started, 2), "upsample_seconds": 0.0,
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
                       profile_id: Optional[str], elaborate: bool = True,
                       exact: Optional[Dict[str, str]] = None, prev: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """source_prompt arrives with [exact text] already masked (see mask_exact). `prev`: the
    previous version of this prompt's program (a small edit whose patch didn't hold).

    One write, then fixes in place: phases and doubled phrases are fixed in code, and
    other problems go back as numbered-line edits instead of a full rewrite. If a repair
    doesn't settle it, the writer rewrites, told what was wrong. At most MAX_ATTEMPTS
    model calls."""
    started = time.monotonic()
    # One model call writes the program, its text already in this model's style: the
    # enhancer's per-model guide is the writer's own instructions, not a separate step.
    guide, images = (await writer_style(source_prompt, ctx, instructions, lora_context, project_id, profile_id)
                     if elaborate else ("", []))
    # What validation compares the program with: the user's own words (kept-words mode).
    enhanced = "" if elaborate else plain_example(source_prompt)
    upsampled_at = time.monotonic()
    base = writer_messages(source_prompt, guide, images, ctx.get("model"), ctx.get("mode") or "prose",
                           params, loras, notes, elaborate, instructions)
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
    while True:
        out_of_time = best is not None and time.monotonic() - started > PREPARE_SOFT_SECONDS
        if source is None:  # write the program (again)
            if len(calls) >= MAX_ATTEMPTS or out_of_time:
                break
            t0 = time.monotonic()
            msgs = base + ([{"role": "assistant", "content": retry[0]}, {"role": "user", "content": retry[1]}]
                           if retry else [])
            reply = await _ask_model(msgs, project_id, max_tokens=cap)
            calls.append({"kind": "write", "seconds": round(time.monotonic() - t0, 2), "chars": len(reply or "")})
            if _truncated(reply):
                last_error = "The reply was cut off: it was far too long."
                retry = (reply[:2000], "Your reply was cut off because it was far too long. Write the program "
                         "again, short: write the text once in emit() and give each pick 1 to 3 seeds.")
                continue
            source, repaired = drop_name_options(extract_code(reply), source_prompt), False
        source, fixed = fix_written(source, source_prompt, enhanced, loras)
        fixes += fixed
        try:
            check(source)
            checked = validate(source, source_prompt, loras, set(params), enhanced, elaborate)
        except ProgramError as e:
            problems = [str(e)]
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
        reply = await _ask_repair(base + [{"role": "assistant", "content": f"```python\n{source}```"},
                                          {"role": "user", "content": REPAIR_NOTE.format(
                                              problems=last_error, numbered=_numbered_program(source))}],
                                  project_id, max_tokens=_repair_cap(source))
        edited = apply_line_edits(source, reply)
        if edited is None and "```" in (reply or "") and "emit(" in reply and not _LINE_EDIT.search(reply):
            edited = extract_code(reply)  # it wrote the whole program instead: take it
        if edited == source:
            edited = None
        calls.append({"kind": "repair", "seconds": round(time.monotonic() - t0, 2), "chars": len(reply or ""),
                      "applied": edited is not None})
        source, repaired = (drop_name_options(edited, source_prompt), True) if edited is not None else (None, False)
    if best is None:
        raise ProgramError(f"Couldn't prepare this prompt: {last_error}")
    source, checked = best
    entry = _entry(key=key, tool_id=tool_id, ctx=ctx, elaborate=elaborate, prompt=source_prompt, enhanced=enhanced,
                   exact=exact, source=source, checked=checked, params=params, loras=loras)
    entry.update({
        "attempts": len(calls), "repairs": fixes,
        "lineage": (prev.get("lineage") or prev.get("key")) if prev else key,
        "seconds": round(time.monotonic() - started, 2), "upsample_seconds": round(upsampled_at - started, 2),
        "timing": {"enhance": round(upsampled_at - started, 2), "calls": calls},
    })
    log.info(f"[prompt-program] prepared {key} ({entry['mode']}) in {entry['seconds']}s "
             f"(upsample {entry['upsample_seconds']}s, model calls {[c['kind'] for c in calls]}, "
             f"{len(entry['choices'])} choices, {len(fixes)} fixed in code)")
    return entry


def fix_written(source: str, prompt: str, enhanced: str, loras: Sequence[LoraInfo]) -> Tuple[str, List[str]]:
    """The fixes in code a written (or repaired) program gets before validation, in order.
    Returns the source and what changed."""
    notes: List[str] = []
    for fix in (fix_quotes, fix_generated_refs, lambda x: fix_one_item_lists(x, prompt),
                lambda x: fix_list_sources(x, prompt), fix_phases, fix_unplaced, fix_brackets,
                lambda x: fix_requested(x, prompt), lambda x: fix_stated(x, prompt, enhanced),
                lambda x: fix_duplicates(x, prompt), lambda x: trim_added(x, prompt),
                lambda x: fix_trigger_words(x, loras, prompt)):
        source, more = fix(source)
        notes += more
    return source, notes


def fix_patched(source: str, prompt: str, stated_example: str) -> Tuple[str, List[str]]:
    """The fixes in code a program patched for a prompt edit gets (fewer than a fresh write:
    what the edit didn't touch was already fixed)."""
    source = drop_name_options(source, prompt)
    notes: List[str] = []
    for fix in (fix_generated_refs, lambda x: fix_one_item_lists(x, prompt), lambda x: fix_list_sources(x, prompt),
                fix_phases, lambda x: fix_requested(x, prompt), lambda x: fix_stated(x, prompt, stated_example)):
        source, more = fix(source)
        notes += more
    return source, notes


def _entry(*, key: str, tool_id: str, ctx: Dict[str, Any], elaborate: bool, prompt: str, enhanced: str,
           exact: Optional[Dict[str, str]], source: str, checked: Dict[str, Any], params: Dict[str, Any],
           loras: Sequence[LoraInfo]) -> Dict[str, Any]:
    info = checked["info"]
    normalize_sources(info, prompt)
    return {
        "key": key, "version": PREPARE_VERSION, "prompt": prompt, "tool_id": tool_id,
        "mode": ctx.get("mode"), "elaborate": bool(elaborate), "enhanced": enhanced, "exact": exact or {},
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
            revision: Optional[Dict[str, Any]] = None, runtime: Any = None) -> RunResult:
    """One generation's prompt from a prepared program. Programs with pick specs draw
    with generated options and the configured judge (prompt_programs.fluent); pass a
    recorded `revision` to replay its pools and knobs, or a `runtime` to draw with a
    given options service and judge (evaluations, tests)."""
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
        from prompt_programs.judge import JudgeUnavailable
        rt = runtime or runtime_for(entry, edits=clean_edits, profile_id=profile_id, project_id=project_id,
                                    revision=revision)

        def _draw(rt: Any) -> RunResult:
            return draw(entry["program"], seed, clean_pins, loras, params, fixed or None, clean_edits or None,
                        options=rt.options, judge=rt.judge, rarity=rt.rarity, wrong_cut=rt.wrong_cut,
                        keep=getattr(rt, "keep", "cut"), legacy=legacy_program(entry),
                        typicality=getattr(rt, "typicality", None))
        try:
            result = _draw(rt)
        except JudgeUnavailable as e:
            if revision or runtime is not None:  # an exact replay or an evaluation: say so
                raise ProgramError(str(e)) from None
            # The judge went away mid-session: this image draws without one, and its
            # revision records the null judge.
            log.warning(f"[prompt-program] {e}; drawing without the judge")
            from prompt_programs.draws import NullJudge
            result = _draw(runtime_for(entry, edits=clean_edits, profile_id=profile_id, project_id=project_id,
                                       judge=NullJudge()))
    else:
        result = run(entry["program"], seed, clean_pins, loras, params, fixed or None, clean_edits or None)
    if entry.get("exact"):  # the user's [exact text], straight to the image model
        result.prompt = unmask_exact(result.prompt, entry["exact"])
    return result


_OPTIONS_PROMPT = """You write options for one choice in an image prompt. Each image draws one option and
puts it in the prompt where the choice stands.

Write exactly {count} new options for "{label}"{about}. Each option:
- is a concrete, visual phrase that reads naturally in place of the example below,
- matches the existing options in style and length{keep},
- differs for real from every other option and from the existing ones (no synonyms),
- fits the rest of the prompt,
- says what to show, never what to leave out (no "no", "not", "without").

Reply with only a JSON list of strings."""


def _parse_options(reply: str) -> List[str]:
    import json
    text = re.sub(r"^```\w*\s*|\s*```$", "", (reply or "").strip())
    m = re.search(r"\[.*\]", text, re.S)
    try:
        items = json.loads(m.group(0)) if m else []
    except ValueError:
        items = []
    if not items:  # one per line, bullets or numbers stripped
        items = [re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", ln).strip().strip('",') for ln in text.splitlines()]
    return [str(x).strip() for x in items if isinstance(x, (str, int, float)) and str(x).strip()]


async def suggest_options(entry: Dict[str, Any], choice_id: str, existing: Sequence[str], count: int,
                          project_id: Optional[int]) -> List[str]:
    """New options for one choice of a prepared program, in the style of its others.
    Called by the choice card (More like these, Reroll all); never during a run."""
    choice = next((c for c in entry.get("choices") or [] if c.get("id") == choice_id), None)
    if not choice or choice.get("kind") != "pick":
        raise ProgramError(f"No choice {choice_id} to write options for.")
    count = max(1, min(24, int(count)))
    wildcard = choice.get("wildcard")
    system = _OPTIONS_PROMPT.format(
        count=count, label=choice.get("label") or choice_id,
        about=f' (the user wrote {{{{{wildcard}}}}})' if wildcard and wildcard.lower() != str(choice.get("label", "")).lower() else "",
        keep="; short, a few words, like the user's own wording" if entry.get("elaborate") is False else "",
    )
    have = list(dict.fromkeys(str(x) for x in existing if str(x).strip()))
    user = "\n".join([
        f"User's prompt:\n{entry.get('prompt', '')}",
        "",
        f"Example prompt:\n{entry.get('example') or entry.get('enhanced') or ''}",
        "",
        "Existing options (don't repeat these):",
        *[f"- {o}" for o in have],
    ])
    seen = {o.lower() for o in have}
    out: List[str] = []
    for _ in range(2):  # one retry if the model repeats itself
        reply = await _ask_model([{"role": "system", "content": system}, {"role": "user", "content": user}], project_id)
        for o in _parse_options(reply):
            if o.lower() not in seen and len(out) < count:
                seen.add(o.lower())
                out.append(o)
        if len(out) >= count:
            break
    if not out:
        raise ProgramError("The model didn't write any new options.")
    return out


__all__ = ["ensure_program", "realize", "draw_seed", "realized_text", "tidy_text", "suggest_options", "ProgramError",
           "DrawAborted"]
