"""What a run does when its prompt couldn't be prepared: it goes ahead anyway.

The user pressed Generate; they get images. A prepare that fails (the chat model too slow,
unreachable or out of balance, a program it couldn't get right, a prompt too long to read)
costs variety, never the run. The ladder, best first:

1. a program from this prepare: valid, or kept with problems that cost variety only (the
   ones prepare.validate calls blocking never are: emitting text that isn't prompt, losing
   the user's [exact text], lists or {{wildcards}});
2. ``previous``: a program prepared for exactly the same prompt text under other settings
   (Detail level, LoRA choices, instructions), when the settings changed and the new
   prepare failed. Never a program for other words: an edited prompt is never run as the
   prompt it was;
3. ``words``: the prompt as written (and the only rung for a prompt the chat model declined), handled the Direct way (lists vary, saved wildcards
   and segments fill, [brackets] unwrap, # lines drop). A {{name}} that is no saved
   wildcard stands as its own words ("{{stormy sky}}" reads "stormy sky"): the closest
   thing to what the user asked that needs no model, while the prepare is retried in the
   background (prepare.retry_failed) and later runs pick its program up.

Rungs 2 and 3 record which they were (`fallback` on the run's record), so Generation
details can say so and "Same draws, new seed" never claims draws it doesn't have.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Sequence

from core.logging import get_logger

log = get_logger(__name__)

RUNGS = ("previous", "words")


def failure_code(e: BaseException) -> Optional[str]:
    """The code of a prepare failure a run degrades on instead of stopping, else None (a
    bug, or a run-time problem the user must fix, like a pinned value nothing fits)."""
    from llm_resolver import LLMNotConfiguredError, LLMUnavailableError
    from prompt_programs.draws import DrawAborted
    from prompt_programs.prepare import PrepareDeclined, PrepareFailed, PrepareTimeout, PromptTooLong, writer_failure

    if isinstance(e, DrawAborted):
        return None
    e = writer_failure(e) or e
    if isinstance(e, PrepareTimeout):
        return "prepare_timeout"
    if isinstance(e, (PrepareFailed, PrepareDeclined, PromptTooLong)):
        return e.code
    if isinstance(e, LLMNotConfiguredError):
        return "llm_not_configured"
    if isinstance(e, LLMUnavailableError):
        return getattr(e, "code", None) or "llm_unavailable"
    return None


_SMART = re.compile(r"\{\{([^{}]+)\}\}")


def words_as_written(prompt: str, profile_id: Optional[str]) -> str:
    """The prompt for the Direct pipeline, with each {{name}} that is no saved wildcard or
    segment as its own words. Saved ones stay for the pipeline to fill."""
    from prompt_pipeline import _profile_wildcards_and_segments
    wildcards, segments = _profile_wildcards_and_segments(profile_id)
    known = {str(w.get("name", "")).strip().lower() for w in wildcards} | \
            {str(s.get("name", "")).strip().lower() for s in segments}

    def repl(m: re.Match) -> str:
        name = m.group(1).strip()
        return m.group(0) if name.lower() in known else name

    return _SMART.sub(repl, prompt)


def fallback_note(rung: str, code: Optional[str], message: str = "") -> Dict[str, Any]:
    """What a run's record says about its rung (stored with the image)."""
    return {"rung": rung, "code": code or "program_failed", **({"message": message[:300]} if message else {})}


def words_record(code: Optional[str], *, level: str, message: str = "") -> Dict[str, Any]:
    """The record of a run made from the words as written: no program, no draws."""
    return {"key": None, "enhance": level, "elaborate": level == "expand", "draws": [], "choices": [],
            "fallback": fallback_note("words", code, message)}


def previous_program(prompt: str, *, tool_id: str, profile_id: Optional[str],
                     lora_items: Sequence[Dict[str, Any]], code: Optional[str]) -> Optional[Dict[str, Any]]:
    """Rung 2, or None. A prompt too long to read has no program under any settings, and a
    prompt the chat model declined runs as written (Direct), whatever was prepared before."""
    if code in ("prompt_too_long", "prepare_declined"):
        return None
    from prompt_programs.prepare import previous_for_text
    try:
        return previous_for_text(prompt=prompt, tool_id=tool_id, profile_id=profile_id, lora_items=lora_items)
    except Exception as e:  # a lookup for a fallback never fails the run
        log.warning(f"[prompt-program] looking up an earlier program for this prompt failed: {e}")
        return None


# What an agent's vary result says when a fallback ran (plain, and what to do about it).
_AGENT_WHY = {
    "prepare_timeout": "the chat model took too long to read it",
    "llm_unavailable": "the chat model couldn't be reached",
    "llm_insufficient_balance": "the chat model has no balance left",
    "llm_not_configured": "no chat model is set up in Settings",
    "prompt_too_long": "it is too long to read (shorten it to vary it)",
}


def agent_note(note: Dict[str, Any]) -> str:
    if note.get("code") == "prepare_declined":
        return ("The chat model declined this prompt, so no choices were varied: it ran with its words as written "
                "(its own {a|b} lists still vary). The same prompt gets the same answer; reword it to try again.")
    why = _AGENT_WHY.get(str(note.get("code")), "the chat model couldn't read it")
    if note.get("rung") == "previous":
        return (f"The prompt couldn't be read with these settings ({why}), so it ran with the choices it was read "
                "with before. It is being read again in the background.")
    return (f"The prompt couldn't be read for varied choices ({why}), so it ran with its words as written: its "
            "own {a|b} lists still vary. It is being read again in the background; later generations pick that up.")


__all__ = ["RUNGS", "agent_note", "failure_code", "fallback_note", "previous_program", "words_as_written",
           "words_record"]
