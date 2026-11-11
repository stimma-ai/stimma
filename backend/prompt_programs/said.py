"""said=: a pick that stands for a thing the user named keeps their words.

    car = pick("car", said="yellow ferrari", about="the car", seed=["red lamborghini"], label="Car", phase=1)

"cinematic shot of a yellow ferrari" drawn as a Volkswagen Beetle is the product replacing what
the user named. A pick with said= draws the user's words, exactly as written, in every image,
until the user ticks other options in its card (runtime.said_value); its other options are
alternatives they may widen to, never a replacement chosen for them.

The writer marks such picks itself (instructions.md), and validation holds said= to an exact
stretch of the prompt (prepare._said_problems). Writers forget, so after a program is written
one reading call asks, for each pick the writer added, whether it stands in place of something
the user named, given the user's prompt and the program's text with its picks shown as [Label].
An answer is kept only when it is a stretch of the user's own words as written and the program's
fixed text doesn't already say it (the words are gone from what every image reads): code never
judges which words "count". Each pick kept that way gets said= in its program, so it behaves as
if the writer had marked it.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger

log = get_logger(__name__)

SAID_VERSION = "said-1"

_SYSTEM = """You compare an image prompt a user wrote with a program's version of it. In the program's version,
the parts that change from image to image are shown as [Label]; each image puts one option there.

For each part, decide whether it stands in place of something the user named: the user's own words for
that thing are missing from the program's version, and the part's options put a thing of that kind
there instead (the user wrote "a yellow ferrari" and the part draws other cars; "a birthday cake" and
the part draws other cakes or foods). Then copy the user's words for that thing, character for
character, as they wrote them ("yellow ferrari", "birthday cake").

Give null for a part that adds a detail the user left open (her hairstyle when they said nothing about
hair, the weather, which model of Ferrari when they wrote "a Ferrari"), and for a part whose thing the
program's version still names in its own words.

Reply with only a JSON object mapping each part's id to the user's words or null."""


def candidates(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The picks to ask about: the writer's picks with a spec, whether it marked them added or
    from the user's text, but not the user's lists, wildcards or #-line requests; shown to the
    user, not marked said. A pick bound to a list is asked about only when the writer took it
    from the user's text (not added): a stated value it forgot to mark ("emerald eyes" as an eye
    pick) would otherwise be narrowed to the list's nearest kind and their word lost."""
    from prompt_programs.prepare import _comment_lines
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    comments = _comment_lines(str(entry.get("prompt") or ""))
    return [c for c in entry.get("choices") or []
            if c.get("kind", "pick") == "pick" and c.get("source") != "list" and not c.get("hidden")
            and not (c.get("source") != "added" and c.get("line") in comments)
            and not c.get("said") and not c.get("wildcard")
            and (vocab.get(c.get("cls")) is None or c.get("source") != "added")
            and str(c.get("about") or "").strip()]


def messages(prompt: str, template: str, parts: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    lines = []
    for c in parts:
        examples = "; ".join(str(o) for o in (c.get("options") or [])[:3])
        what = str(c.get("about") or c.get("label") or c["id"])
        lines.append(f'- {c["id"]}, shown as [{c.get("label") or c["id"]}]: {what}' + (f" (for example: {examples})" if examples else ""))
    user = (f"The user's prompt:\n{prompt}\n\nThe program's version:\n{template}\n\nThe parts:\n" + "\n".join(lines))
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


def parse(reply: str, ids: Sequence[str], prompt: str, template: str) -> Optional[Dict[str, str]]:
    """{id: the user's words} from the reply's JSON object, keeping only answers that are a
    stretch of the user's own words as written and that the program's fixed text doesn't say;
    a stretch claimed by two parts goes to neither. None when the reply holds no JSON object."""
    from prompt_programs.narrow import _span
    from prompt_programs.prepare import users_spelling
    m = re.search(r"\{.*\}", reply or "", re.S)
    if not m:
        return None
    try:
        got = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(got, dict):
        return None
    # Weak models key the answer as the part was listed ("car, shown as [Car]", "car [Car]").
    got = {re.split(r",|\s\[|\s\(", str(k), maxsplit=1)[0].strip(): v for k, v in got.items()}
    fixed = re.sub(r"\[[^\[\]]*\]", " … ", template)  # the program's own words, picks left out
    out: Dict[str, str] = {}
    for cid in ids:
        v = got.get(cid)
        words = users_spelling(v.strip(" .,;:!"), prompt) if isinstance(v, str) else ""
        if words and not _span(words, fixed):
            out[cid] = words
    claimed: Dict[str, int] = {}
    for w in out.values():
        claimed[w.lower()] = claimed.get(w.lower(), 0) + 1
    return {cid: w for cid, w in out.items() if claimed[w.lower()] == 1}


async def read_said(entry: Dict[str, Any], cache: Any, ask: Any, project_id: Optional[int] = None,
                    seconds: float = 20.0) -> Optional[Dict[str, str]]:
    """{pick id: the user's words it stands for}, from one call per program (cached by the
    prompt, the program's text and the parts asked about). {} when there is nothing to ask;
    None when the call fails, times out or can't be read (never cached)."""
    from prompt_programs.draws import fixed_text
    from prompt_programs.runtime import LoraInfo, ProgramError
    parts = candidates(entry)
    prompt = str(entry.get("prompt") or "")
    if not parts or not prompt.strip():
        return {}
    try:
        loras = [LoraInfo(**lo) for lo in entry.get("loras") or []]
        template = fixed_text(entry["program"], loras, set(entry.get("params") or {}) or None)
    except (ProgramError, KeyError, TypeError) as e:
        log.info(f"[prompt-program] said: no program text to compare ({e})")
        return {}
    msgs = messages(prompt, template, parts)
    key = hashlib.sha256(json.dumps(["said", SAID_VERSION, msgs], ensure_ascii=False).encode()).hexdigest()[:32]
    if cache is not None:
        hit = cache.get_raw(key)
        if isinstance(hit, dict):
            return {str(k): str(v) for k, v in hit.items()}
    try:
        reply = await asyncio.wait_for(ask(msgs, project_id, 600), seconds)
    except Exception as e:  # the writer's endpoint failing here must not fail the prepare
        log.warning(f"[prompt-program] said: reading which picks stand for the user's words failed: {type(e).__name__}: {e}")
        return None
    got = parse(reply, [c["id"] for c in parts], prompt, template)
    if got is None:
        log.info("[prompt-program] said: no JSON object in the reply")
        return None
    if cache is not None:
        cache.put_raw(key, got)
    return got


def add_said(source: str, found: Dict[str, str]) -> Tuple[str, Dict[str, str]]:
    """The program with said="<words>" added to each pick in `found` whose id is written as a
    constant (a pick in a loop names each person's own detail; it is left as written). Returns
    the source and the picks it marked."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, {}
    from prompt_programs.prepare import _offsets
    pos = _offsets(source)
    edits: List[Tuple[int, str]] = []
    done: Dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "pick" and node.args
                and isinstance(node.args[0], ast.Constant) and node.args[0].value in found):
            continue
        cid = str(node.args[0].value)
        if cid in done or any(k.arg == "said" for k in node.keywords):
            continue
        last = max([*node.args, *(k.value for k in node.keywords)], key=lambda n: (n.end_lineno, n.end_col_offset))
        edits.append((pos(last.end_lineno, last.end_col_offset), f", said={json.dumps(found[cid], ensure_ascii=False)}"))
        done[cid] = found[cid]
    for at, text in sorted(edits, reverse=True):
        source = source[:at] + text + source[at:]
    return source, done


def apply_said(entry: Dict[str, Any], found: Dict[str, str]) -> List[str]:
    """Mark the picks `found` names with said= in the entry, in place: the program, its choices
    and its example. A pick whose marked program no longer runs, or no longer says the user's
    words, is left as it was. Returns notes for the log."""
    from prompt_programs.draws import analyze
    from prompt_programs.prepare import emitted_as, realized_text
    from prompt_programs.runtime import LoraInfo, ProgramError, check, run
    if not found:
        return []
    source, done = add_said(entry["program"], found)
    if not done:
        return []
    loras = [LoraInfo(**lo) for lo in entry.get("loras") or []]
    params = set(entry.get("params") or {}) or None
    try:
        check(source)
        analyze(source)
        sample = run(source, 11, None, loras, params)
    except (ProgramError, RecursionError, ValueError, TypeError, KeyError, IndexError) as e:
        log.info(f"[prompt-program] said: marking {sorted(done)} broke the program ({e}); left as written")
        return []
    text = realized_text(sample.prompt).lower()
    lost = [cid for cid, words in done.items() if emitted_as(words, text) is None]
    if lost:  # the pick isn't emitted where its words would read: leave those as written
        source, done = add_said(entry["program"], {k: v for k, v in done.items() if k not in lost})
        if not done:
            return []
        sample = run(source, 11, None, loras, params)
    entry["program"] = source
    entry.pop("template", None)
    entry["example"] = realized_text(sample.prompt)
    lines = [ln.lower() for ln in str(entry.get("prompt") or "").splitlines()]
    for c in entry.get("choices") or []:
        words = done.get(str(c.get("id")))
        if not words:
            continue
        c["said"], c["source"] = words, "text"
        c["options"] = list(dict.fromkeys([words, *(c.get("options") or [])]))
        # Their words, not a kind: a narrowing of the same pick (read beside this) no longer holds,
        # so the whole list is there to tick.
        if c.get("cls"):
            (entry.get("filters") or {}).pop(str(c.get("id")), None)
            (entry.get("narrow_pending") or {}).pop(str(c.get("id")), None)
            c.pop("where_words", None)
            if isinstance(c.get("where"), str):
                c.pop("where")
        c["line"] = next((i + 1 for i, ln in enumerate(lines) if words.lower() in re.sub(r"\s+", " ", ln)), c.get("line"))
    entry["said_read"] = dict(done)
    return [f'{cid}: keeps the user\'s "{w}"' for cid, w in done.items()]


__all__ = ["SAID_VERSION", "add_said", "apply_said", "candidates", "messages", "parse", "read_said"]
