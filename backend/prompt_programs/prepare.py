"""Prepare: turn a prompt into a program with one LLM call, then cache it.

Everything that shapes the program is part of its cache key, so asking again with the
same prompt, tool, LoRAs and parameters never calls the model. Realizing (running the
program for one generation) needs no model at all.
"""

from __future__ import annotations

import ast
import asyncio
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from core.logging import get_logger
from prompt_programs.runtime import (
    LoraInfo, ProgramError, RunResult, check, discover, extract_code, run, tidy_text,
)
from prompt_programs.store import ProgramStore, program_key

log = get_logger(__name__)

PREPARE_VERSION = "pp-18"
MAX_ATTEMPTS = 3
_INSTRUCTIONS = (Path(__file__).parent / "instructions.md").read_text("utf-8")

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


def build_user_message(prompt: str, enhanced: str, model_name: Optional[str], mode: str,
                       params: Dict[str, Dict[str, Any]], loras: Sequence[LoraInfo], notes: Dict[str, str],
                       elaborate: bool = True) -> str:
    parts = [f"User's prompt (lines numbered):\n{_numbered(prompt)}", ""]
    smart = smart_wildcards(prompt)
    if elaborate:
        parts.append(
            f"Enhanced prompt (one example image, written for {model_name or 'the image model'} in its "
            f"\"{mode}\" style). Copy this text and its format into emit(); vary only what should vary:")
    else:
        parts.append(
            "Prompt to emit: the user's own words, joined into one example image with nothing added. "
            "The user wants their wording kept: copy it into emit() as written. Options you write are "
            "short phrases (a few words) in the same register as the user's words. Add no extra picks "
            "(no added=True).")
        if mode == "keyword":
            parts.append("This model reads comma-separated tags: write options as tags.")
    parts += ["", enhanced.strip(), "", "(End of the enhanced prompt.)" if elaborate else "(End of the prompt.)", ""]
    if smart and (elaborate or "[{{" not in enhanced):
        names = ", ".join("{{" + n + "}}" for n in smart)
        parts += [f"Smart wildcards: {names}. The prompt above wrote one example of each where it stood; "
                  "find that phrase, make it the first option, and put the pick in its place.", ""]
    if params:
        desc = ", ".join(
            f"{n} ({p.get('minimum', '?')}–{p.get('maximum', '?')})" for n, p in sorted(params.items()))
        parts.append(f"Parameters you may vary, only when the prompt asks: {desc}.")
    else:
        parts.append("This tool has no parameters you may vary.")
    if loras:
        parts.append("LoRA list (name — trigger — notes):")
        for lo in loras:
            parts.append(f"- {lo.name} — {lo.trigger or '(none)'} — {notes.get(lo.name, '')}".rstrip(" —"))
    else:
        parts.append("LoRA list: none. Don't use pick_lora.")
    return "\n".join(parts)


_PLACEHOLDER_NOTE = (
    "This prompt will become a template: some details vary from image to image. Keep every "
    "[...] placeholder exactly where it belongs in the sentence. Words in angle brackets, like "
    "\u27e8hairstyle\u27e9, name something that changes from image to image: write one concrete, "
    "vivid example of each in its place, without the brackets, and describe it only there. "
    "Where the prompt asks for something to vary, write one concrete example of it."
)


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
    out = await _improve_with_verbatim_protection(
        db, protect_variable_spots(_for_enhancer(prompt)),
        instructions="\n".join(x for x in (instructions, _PLACEHOLDER_NOTE) if x),
        model=ctx.get("model"), project_id=project_id, lora_context=lora_context, **ctx["enhance"],
    )
    return out.replace("\u27e8", "").replace("\u27e9", "")


async def _ask_model(messages: List[Dict[str, str]], project_id: Optional[int]) -> str:
    from llm import llm_complete_text
    from llm_correlation import llm_correlation_context
    from llm_resolver import get_effective_llm_config

    cfg = await get_effective_llm_config("tool_assistant", project_id)
    with llm_correlation_context("prompt-program"):
        return await llm_complete_text(config=cfg, messages=messages, max_tokens=4096, temperature=0.3)


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
    return None


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
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for ln in lines:
        offsets.append(offsets[-1] + len(ln))

    def pos(lineno: int, col: int) -> int:  # ast columns count UTF-8 bytes
        return offsets[lineno - 1] + len(lines[lineno - 1].encode()[:col].decode("utf-8", "ignore"))

    cuts = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "pick" and node.args
                and isinstance(node.args[0], ast.Constant) and node.args[0].value in names):
            continue
        opts = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "options"), None)
        if not isinstance(opts, ast.List):
            continue
        name = names[node.args[0].value]
        keep = [e for e in opts.elts if not (isinstance(e, ast.Constant) and str(e.value).strip().lower() == name)]
        if len(keep) < 2 or len(keep) == len(opts.elts):
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


def _verbatim_segments(prompt: str) -> List[str]:
    return [m.group(1).strip() for m in _VERBATIM.finditer(prompt) if m.group(1).strip()]


def realized_text(prompt: str) -> str:
    """What the image model would see (protected text unwrapped)."""
    return re.sub(r"\s+", " ", _VERBATIM.sub(lambda m: m.group(1), prompt)).strip()


def _word_count(text: str) -> int:
    return len(re.findall(r"[\w'-]+", re.sub(r"\[\{.*?\}\]", " x ", text)))


def validate(source: str, prompt: str, loras: Sequence[LoraInfo], params: Set[str],
             enhanced: str = "", elaborate: bool = True) -> Dict[str, Any]:
    info = discover(source, loras, params)
    samples = [run(source, s, None, loras, params) for s in (11, 23, 37, 51)]
    problems: List[str] = []
    if enhanced:
        want = _word_count(enhanced)
        got = min(_word_count(realized_text(r.prompt)) for r in samples)
        if elaborate and want >= 20 and got < 0.6 * want:
            problems.append(f"The prompts your program emits are too short ({got} words; the enhanced prompt has {want}). "
                            "Copy the enhanced prompt's full text into emit() and only swap the parts that vary.")
        if any(re.search(r"<<<|>>>|^\s*[\"']{3}", r.prompt) for r in samples):
            problems.append("Emit only the prompt text itself, with no quote marks or <<< >>> around it.")
        if any("[{" in r.prompt or "{{" in r.prompt for r in samples):
            problems.append("Replace every [{...}] placeholder with its pick's value; never emit the braces.")
        if not elaborate:  # kept words: every word of the example outside the picks survives
            in_options = set().union(*(_words(o) for c in info["choices"] for o in c.get("options") or []), set())
            fixed = _words(re.sub(r"\[\{.*?\}\]", " ", enhanced)) - in_options
            emitted = set().union(*(_words(r.prompt) for r in samples))
            lost = sorted(fixed - emitted)
            if lost:
                problems.append("Keep the user's words: these are missing from what you emit: "
                                + ", ".join(f'"{w}"' for w in lost) + ". Copy the prompt's text into emit() as written.")
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
        problems.append(f'pick("{cid}") appears more than once in the prompt ("{value}"). Emit each pick once, where its subject belongs.')
    for cid, value in missing.items():
        problems.append(f'pick("{cid}") drew "{value}" but it never appears in the emitted prompt. Pass its result to emit(...).')
    for name in smart_wildcards(prompt):
        if not _smart_choice(info, name):
            problems.append(f'{{{{{name}}}}} is a smart wildcard: make it pick("{smart_id(name)}", [6-12 options], label=<one or two words>, line=...) and emit its value where {{{{{name}}}}} stands.')
    for name in smart_wildcards(prompt):  # a descriptive name says what to write, it isn't an option
        c = _smart_choice(info, name)
        if c and name.lower() in (o.lower() for o in c["options"]):
            problems.append(f'{{{{{name}}}}} needs 6-12 different concrete options that each fit "{name}", not the name itself.')
    for c in info["choices"]:  # labels are pill names, not descriptions
        if len(c["label"]) > 24 or len(c["label"].split()) > 3:
            problems.append(f'label="{c["label"]}" is too long for {c["id"]}: use one or two words, like "Weather" or "Photo look".')
    if any("{{" in r.prompt for r in samples):
        problems.append("Don't emit {{...}}: replace each smart wildcard with its pick's value.")
    for m in _INLINE_LIST.finditer(prompt):
        opts = [o.strip() for o in m.group(1).split("|")]
        if not any(c["options"][: len(opts)] == opts and c.get("source") == "list" for c in info["choices"]):
            problems.append(f'The user list {{{m.group(1)}}} must be a pick with exactly these options in order and source="list".')
    return {"info": info, "problems": list(dict.fromkeys(problems))}


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
        out.append(LoraInfo(name=name, path=path, weight=weight, trigger=", ".join(triggers)))
        if note.get("notes"):
            notes[name] = str(note["notes"])[:300]
    return out, notes


async def ensure_program(*, prompt: str, tool_id: str, ctx: Dict[str, Any], instructions: str,
                         lora_items: Sequence[Dict[str, Any]], project_id: Optional[int],
                         profile_id: Optional[str], cache_only: bool = False, force: bool = False,
                         elaborate: bool = True) -> Optional[Dict[str, Any]]:
    """The prepared program for these inputs, from cache or by asking the model.
    elaborate (Enhance on): the per-model enhancer writes a rich example first and the
    program keeps it. Off: the program keeps the user's own words."""
    from prompt_pipeline import _profile_wildcards_and_segments

    wildcards, segments = _profile_wildcards_and_segments(profile_id)
    source_prompt = expand_named_lists(prompt, wildcards, segments).strip()
    params = tool_param_specs(ctx.get("schema_props") or {})
    candidates, notes = await lora_candidates(tool_id, lora_items, profile_id)
    loras = match_loras(source_prompt, candidates)
    lora_context = [{"name": lo.name, "trigger_words": [t.strip() for t in lo.trigger.split(",") if t.strip()],
                     "notes": notes.get(lo.name, "")} for lo in loras]
    # The canvas only matters to layout formats (Ideogram), which have no programs;
    # leaving it out keeps a prepared program valid across sizes.
    enhance = {k: v for k, v in (ctx.get("enhance") or {}).items() if k not in ("width", "height")}
    key = program_key({
        "v": PREPARE_VERSION, "prompt": source_prompt, "tool": tool_id, "model": ctx.get("model"),
        "mode": ctx.get("mode"), "enhance": enhance, "instructions": instructions,
        "params": sorted(params), "loras": [vars(lo) for lo in loras], "notes": lora_context,
        "elaborate": bool(elaborate),
    })
    store = _store(profile_id)
    cached = None if force else store.get(key)
    if cached or cache_only:
        return cached
    # One prepare per key: concurrent runs and the editor share it instead of each
    # asking the model.
    running = _in_flight.get(key)
    if running is None:
        running = asyncio.ensure_future(_prepare_new(
            key=key, store=store, tool_id=tool_id, ctx=ctx, instructions=instructions, source_prompt=source_prompt,
            params=params, loras=loras, notes=notes, lora_context=lora_context, project_id=project_id, profile_id=profile_id,
            elaborate=bool(elaborate),
        ))
        _in_flight[key] = running
        running.add_done_callback(lambda _t, k=key: _in_flight.pop(k, None) if _in_flight.get(k) is _t else None)
    return await asyncio.shield(running)


_in_flight: Dict[str, "asyncio.Future[Dict[str, Any]]"] = {}


async def _prepare_new(*, key: str, store: ProgramStore, tool_id: str, ctx: Dict[str, Any], instructions: str,
                       source_prompt: str, params: Dict[str, Any], loras: List[LoraInfo], notes: Dict[str, str],
                       lora_context: List[Dict[str, Any]], project_id: Optional[int],
                       profile_id: Optional[str], elaborate: bool = True) -> Dict[str, Any]:
    started = time.monotonic()
    enhanced = (await upsample(source_prompt, ctx, instructions, lora_context, project_id, profile_id)
                if elaborate else await keep_words(source_prompt, ctx.get("mode") or "prose", project_id))
    upsampled_at = time.monotonic()
    messages = [
        {"role": "system", "content": _INSTRUCTIONS},
        {"role": "user", "content": build_user_message(source_prompt, enhanced, ctx.get("model"), ctx.get("mode") or "prose",
                                                        params, loras, notes, elaborate)},
    ]
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        reply = await _ask_model(messages, project_id)
        source = drop_name_options(extract_code(reply), source_prompt)
        try:
            check(source)
            checked = validate(source, source_prompt, loras, set(params), enhanced, elaborate)
        except ProgramError as e:
            last_error = str(e)
        else:
            if not checked["problems"] or attempt == MAX_ATTEMPTS:
                info = checked["info"]
                normalize_sources(info, source_prompt)
                entry = {
                    "key": key, "version": PREPARE_VERSION, "prompt": source_prompt, "tool_id": tool_id,
                    "mode": ctx.get("mode"), "elaborate": bool(elaborate), "enhanced": enhanced,
                    "program": source, "choices": info["choices"], "groups": info["groups"],
                    "params": {n: params[n] for n in info["params"] if n in params},
                    "loras": [vars(lo) for lo in loras],
                    "lora_choices": {c["id"]: c["options"] for c in info["choices"] if c["kind"] == "lora"},
                    "example": realized_text(info["example"]),
                    "warnings": checked["problems"], "attempts": attempt,
                    "seconds": round(time.monotonic() - started, 2),
                    "upsample_seconds": round(upsampled_at - started, 2), "created_at": time.time(),
                }
                store.put(key, entry)
                log.info(f"[prompt-program] prepared {key} ({entry['mode']}) in {entry['seconds']}s "
                         f"(upsample {entry['upsample_seconds']}s, {attempt} attempt(s), {len(info['choices'])} choices)")
                return entry
            last_error = "\n".join(checked["problems"])
        log.info(f"[prompt-program] attempt {attempt} rejected: {last_error[:300]}")
        messages += [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": f"That program has a problem:\n{last_error}\nReply with the corrected program only."},
        ]
    raise ProgramError(f"Couldn't prepare this prompt: {last_error}")


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
            fixed: Optional[Dict[str, Any]] = None, edits: Optional[Dict[str, Any]] = None) -> RunResult:
    loras = [LoraInfo(**lo) for lo in entry.get("loras") or []]
    clean_pins = {str(k): [str(x) for x in (v if isinstance(v, list) else [v])] for k, v in (pins or {}).items() if v}
    clean_edits = {str(k): v for k, v in (edits or {}).items() if isinstance(v, dict)}
    return run(entry["program"], seed, clean_pins, loras, set(entry.get("params") or {}) or None, fixed or None,
               clean_edits or None)


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
    count = max(1, min(12, int(count)))
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


__all__ = ["ensure_program", "realize", "draw_seed", "realized_text", "tidy_text", "suggest_options", "ProgramError"]
