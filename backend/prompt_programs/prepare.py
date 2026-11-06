"""Prepare: turn a prompt into a program with one LLM call, then cache it.

Everything that shapes the program is part of its cache key, so asking again with the
same prompt, tool, LoRAs and parameters never calls the model. Realizing (running the
program for one generation) needs no model at all.
"""

from __future__ import annotations

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

PREPARE_VERSION = "pp-6"
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


def build_user_message(prompt: str, model_name: Optional[str], params: Dict[str, Dict[str, Any]],
                       loras: Sequence[LoraInfo], notes: Dict[str, str]) -> str:
    parts = [f"Prompt (lines numbered):\n{_numbered(prompt)}", ""]
    if model_name:
        parts.append(f"Image model: {model_name}.")
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


def _verbatim_segments(prompt: str) -> List[str]:
    return [m.group(1).strip() for m in _VERBATIM.finditer(prompt) if m.group(1).strip()]


def realized_text(prompt: str) -> str:
    """What the image model would see (protected text unwrapped)."""
    return re.sub(r"\s+", " ", _VERBATIM.sub(lambda m: m.group(1), prompt)).strip()


def validate(source: str, prompt: str, loras: Sequence[LoraInfo], params: Set[str]) -> Dict[str, Any]:
    info = discover(source, loras, params)
    samples = [run(source, s, None, loras, params) for s in (11, 23, 37, 51)]
    problems: List[str] = []
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
    for cid, value in missing.items():
        problems.append(f'pick("{cid}") drew "{value}" but it never appears in the emitted prompt. Pass its result to emit(...).')
    for m in _INLINE_LIST.finditer(prompt):
        opts = [o.strip() for o in m.group(1).split("|")]
        if not any(c["options"][: len(opts)] == opts and c.get("source") == "list" for c in info["choices"]):
            problems.append(f'The user list {{{m.group(1)}}} must be a pick with exactly these options in order and source="list".')
    return {"info": info, "problems": list(dict.fromkeys(problems))}


def normalize_sources(info: Dict[str, Any], prompt: str) -> None:
    """Weak models mark things the user asked for as added. If a choice's name appears in
    the user's text, it came from the text, and gets the line it appears on."""
    lines = [ln.lower() for ln in prompt.splitlines()]
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


async def ensure_program(*, prompt: str, tool_id: str, model_name: Optional[str], schema_props: Dict[str, Any],
                         lora_items: Sequence[Dict[str, Any]], project_id: Optional[int],
                         profile_id: Optional[str], cache_only: bool = False, force: bool = False) -> Optional[Dict[str, Any]]:
    """The prepared program for these inputs, from cache or by asking the model."""
    from prompt_pipeline import _profile_wildcards_and_segments

    wildcards, segments = _profile_wildcards_and_segments(profile_id)
    source_prompt = expand_named_lists(prompt, wildcards, segments).strip()
    params = tool_param_specs(schema_props)
    candidates, notes = await lora_candidates(tool_id, lora_items, profile_id)
    loras = match_loras(source_prompt, candidates)
    key = program_key({
        "v": PREPARE_VERSION, "prompt": source_prompt, "tool": tool_id, "model": model_name,
        "params": sorted(params), "loras": [vars(lo) for lo in loras],
        "notes": {lo.name: notes.get(lo.name, "") for lo in loras},
    })
    store = _store(profile_id)
    cached = None if force else store.get(key)
    if cached or cache_only:
        return cached

    started = time.monotonic()
    messages = [
        {"role": "system", "content": _INSTRUCTIONS},
        {"role": "user", "content": build_user_message(source_prompt, model_name, params, loras, notes)},
    ]
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        reply = await _ask_model(messages, project_id)
        source = extract_code(reply)
        try:
            check(source)
            checked = validate(source, source_prompt, loras, set(params))
        except ProgramError as e:
            last_error = str(e)
        else:
            if not checked["problems"] or attempt == MAX_ATTEMPTS:
                info = checked["info"]
                normalize_sources(info, source_prompt)
                entry = {
                    "key": key, "version": PREPARE_VERSION, "prompt": source_prompt, "tool_id": tool_id,
                    "program": source, "choices": info["choices"], "groups": info["groups"],
                    "params": {n: params[n] for n in info["params"] if n in params},
                    "loras": [vars(lo) for lo in loras],
                    "lora_choices": {c["id"]: c["options"] for c in info["choices"] if c["kind"] == "lora"},
                    "example": realized_text(info["example"]),
                    "warnings": checked["problems"], "attempts": attempt,
                    "seconds": round(time.monotonic() - started, 2), "created_at": time.time(),
                }
                store.put(key, entry)
                log.info(f"[prompt-program] prepared {key} in {entry['seconds']}s ({attempt} attempt(s), {len(info['choices'])} choices)")
                return entry
            last_error = "\n".join(checked["problems"])
        log.info(f"[prompt-program] attempt {attempt} rejected: {last_error[:300]}")
        messages += [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": f"That program has a problem:\n{last_error}\nReply with the corrected program only."},
        ]
    raise ProgramError(f"Couldn't prepare this prompt: {last_error}")


def program_seed(seed: Any, batch_index: Any = None) -> int:
    try:
        s = int(seed)
    except (TypeError, ValueError):
        s = -1
    if s < 0:
        s = random.randrange(1, 2**31)
    try:
        b = int(batch_index or 0)
    except (TypeError, ValueError):
        b = 0
    return (s * 1_000_003 + b) % (2**31)


def realize(entry: Dict[str, Any], *, seed: int, pins: Optional[Dict[str, Any]] = None,
            fixed: Optional[Dict[str, Any]] = None, edits: Optional[Dict[str, Any]] = None) -> RunResult:
    loras = [LoraInfo(**lo) for lo in entry.get("loras") or []]
    clean_pins = {str(k): [str(x) for x in (v if isinstance(v, list) else [v])] for k, v in (pins or {}).items() if v}
    clean_edits = {str(k): v for k, v in (edits or {}).items() if isinstance(v, dict)}
    return run(entry["program"], seed, clean_pins, loras, set(entry.get("params") or {}) or None, fixed or None,
               clean_edits or None)


__all__ = ["ensure_program", "realize", "program_seed", "realized_text", "tidy_text", "ProgramError"]
