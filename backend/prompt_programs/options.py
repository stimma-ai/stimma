"""Options for picks with specs: user lists as written, writer seeds, generated options.

A pick with `about=` that isn't a user list draws from a pool that grows. The pool is
the writer's seeds (and any literal options on its branch), then options an LLM wrote
for the pick's spec in a short context ("hairstyles for a 1920s jazz club"). Those are
cached on disk in the profile, append-only and keyed by their inputs, so another prompt
with the same spec and context reuses them and no call is ever made twice.

    service = GeneratedOptions(store, program=ProgramContext.of(entry), filler=filler)
    pool = service.get(spec, {"era": "1920s"})      # seeds + whatever has been generated
    service.request_more(spec, {"era": "1920s"}, "high")

Generation never runs inside a draw. `get()` queues a low-priority fill for a pool that
has never been generated and a high-priority one for a pool that has run thin; the
filler works through the queue on the event loop, high priority first. A pool with a
fill queued or running says `more_coming`, so the UI can show it.

User lists (`source="list"`) and LoRA picks are never expanded: their options are the
user's, exactly, with uniform weights.
"""

from __future__ import annotations

import asyncio
import hashlib
import heapq
import itertools
import json
import os
import dataclasses
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger
from prompt_programs.fill import RANK_DECAY, LiteralOptions, PickSpec, Pool, context_suffix, owns, person_of, pool_key
from prompt_programs.vocab import (
    AGE_LIST, OPEN_SHARE, TIER_WEIGHTS, Leaf, fill, given_families, minor_ages, tags_match, template_matches,
    vocabulary,
)

log = get_logger(__name__)

OPTIONS_VERSION = "opts-6"     # bump to invalidate every generated pool on purpose. opts-6: a slot's pools by zone (kinds of its words, things instead), each option in the form of the slot's words. opts-5: options name their things, no description added. opts-4: US words. opts-3: US spelling
FIRST_OPTIONS_VERSION = "opts-1"   # what a revision that records no options version drew with
OPTIONS_VERSIONS = (FIRST_OPTIONS_VERSION, "opts-2", "opts-3", "opts-4", "opts-5", OPTIONS_VERSION)   # versions a recorded revision can replay
BATCH_SIZE = 12                # options asked for per generation call
GEN_DECAY = 0.96               # rank decay across generated options (gentler than the writer's lists)
THIN = 6                       # a generated pool with fewer usable options asks for more, high priority
MAX_ROUNDS = 8                 # generation calls per pool, at most
PRIORITY = {"high": 0, "low": 1}


def generated_pick(spec: PickSpec) -> bool:
    """Whether a pick's pool grows: it has a spec and isn't the user's list or a LoRA.
    A pick bound to a closed vocabulary list never grows: the list is its pool."""
    if spec.kind != "pick" or spec.source == "list":
        return False
    leaf = bound(spec)
    if leaf is not None:
        return not leaf.closed
    return bool(spec.about.strip())


def bound(spec: PickSpec) -> Optional[Leaf]:
    """The vocabulary leaf a pick is bound to, or None."""
    return vocabulary().get(spec.cls) if spec.cls else None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())




# --------------------------------------------------------------------------- program context

@dataclass(frozen=True)
class ProgramContext:
    """What generation needs to know about the prompt a pick sits in.

    signature: the short context that keys the cross-prompt cache. The writer may give
      one (entry["context"], e.g. "a 1920s jazz club portrait"); without it, the prompt
      template is the signature, which only matches the same template.
    template: the prompt with every pick masked as [Label], shown to the generator.
    """
    key: str = ""
    signature: str = ""
    template: str = ""
    mode: str = "prose"
    elaborate: bool = True
    lists: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = ()   # (id, label, options) of the user's lists
    tool: str = ""
    # The program's edit lineage: a prompt edit patched into a program keeps its lineage,
    # so every pick the edit didn't touch keeps its options.
    lineage: str = ""
    # the user's words for a pick (a slot's words, where= on picks), by pick id: what that
    # pick's options must stay within
    intents: Tuple[Tuple[str, str], ...] = ()
    # a bound pick's list narrowed by where= (narrow.py), by pick id; an empty subset means
    # nothing in the list fits and the pick draws unbound
    filters: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    # a pick's facet filter (where={...}), as text, by pick id: part of its pools' identity, never
    # shown to the generator
    facets: Tuple[Tuple[str, str], ...] = ()
    # the program's editing context (prepare's context key): background work for a program
    # the user has since edited away from is dropped
    context_key: str = ""
    # (person, ages under 18) for each person who may be a minor: an age pick narrowed to such
    # ages, or the age the prompt states for a person with no age pick (narrow.py, entry["ages"])
    minors: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    # (list pick, ((value, ages under 18), ...)) for the user's list values that read as an age
    # under 18 (narrow.py, entry["list_ages"]): a draw of one makes its person a minor
    list_ages: Tuple[Tuple[str, Tuple[Tuple[str, Tuple[str, ...]], ...]], ...] = ()
    # What the prompt states for a context-giving list (narrow.py, entry["stated_context"]):
    # (person, or None for the scene, list, subset), and what the user's list values read as on
    # such a list (entry["list_context"]): (list pick, value, list, subset)
    stated: Tuple[Tuple[Optional[str], str, Tuple[str, ...]], ...] = ()
    list_context: Tuple[Tuple[str, str, str, Tuple[str, ...]], ...] = ()
    # (pick id, signature) for the picks of a slot: the prompt its reading's options were first
    # written for (slots.py, the slot's "seen"). A slot's pools are keyed by it, so they follow
    # its reading (its own line and the notes), not the whole prompt: an edit elsewhere, or one
    # the edit check says leaves the slot as it was, keeps them
    kept: Tuple[Tuple[str, str], ...] = ()

    @classmethod
    def of(cls, entry: Dict[str, Any]) -> "ProgramContext":
        template = str(entry.get("template") or "")
        signature = str(entry.get("context") or "").strip() or template
        lists = tuple((str(c.get("id")), str(c.get("label") or c.get("id")), tuple(str(o) for o in c.get("options") or []))
                      for c in entry.get("choices") or []
                      if c.get("source") == "list" and c.get("kind", "pick") == "pick" and c.get("options"))
        def words(c: Dict[str, Any]) -> str:  # the user's own words for a choice (never a facet filter)
            where = c.get("where")
            return str(c.get("where_words") or (where if isinstance(where, str) else "") or "")
        intents = tuple((str(c.get("id")), words(c)) for c in entry.get("choices") or [] if words(c))
        # A slot's own words (slots.py) for a pick with no list: the rule its kinds are written within.
        listed = {str(c.get("id")) for c in entry.get("choices") or [] if c.get("cls")}
        intents += tuple((str(k), str(v)) for k, v in (entry.get("slot_words") or {}).items()
                         if str(v).strip() and str(k) not in listed and str(k) not in dict(intents))
        filters = tuple((str(k), tuple(str(x) for x in v)) for k, v in (entry.get("filters") or {}).items()
                        if isinstance(v, list))
        facets = tuple((str(c.get("id")), str(c["where"])) for c in entry.get("choices") or []
                       if isinstance(c.get("where"), dict) and c["where"])
        return cls(str(entry.get("key") or ""), signature, template, str(entry.get("mode") or "prose"),
                   entry.get("elaborate") is not False, lists, str(entry.get("tool_id") or ""),
                   str(entry.get("lineage") or ""), intents, filters, facets, str(entry.get("context_key") or ""),
                   minors=program_minors(entry),
                   list_ages=tuple((str(k), tuple((str(v), tuple(a)) for v, a in vals.items()))
                                   for k, vals in (entry.get("list_ages") or {}).items() if isinstance(vals, dict)),
                   stated=tuple((s.get("of") if isinstance(s.get("of"), str) else None, str(s.get("cls") or ""),
                                 tuple(str(x) for x in s.get("values") or []))
                                for s in entry.get("stated_context") or [] if isinstance(s, dict)),
                   list_context=tuple((str(k), str(v), str(cls), tuple(str(x) for x in sub))
                                      for k, vals in (entry.get("list_context") or {}).items() if isinstance(vals, dict)
                                      for v, by in vals.items() if isinstance(by, dict)
                                      for cls, sub in by.items() if isinstance(sub, list)),
                   kept=tuple((str(d), str(s["seen"]["template"])) for s in entry.get("slots") or []
                              if isinstance(s.get("seen"), dict) and str(s["seen"].get("template") or "").strip()
                              for d in s.get("details") or []))


def _presentation(where_text: str) -> str:
    """The presentation a pick's facet filter names ("{'presentation': 'masculine'}" as ProgramContext
    keeps it), or "" when it names none or more than one."""
    import ast
    try:
        got = ast.literal_eval(where_text)
    except (ValueError, SyntaxError):
        return ""
    want = got.get("presentation") if isinstance(got, dict) else None
    return want if isinstance(want, str) and want in ("feminine", "masculine") else ""


def program_minors(entry: Dict[str, Any]) -> Tuple[Tuple[str, Tuple[str, ...]], ...]:
    """Who in a prepared program may be under 18, and at which ages: a person whose age pick
    was narrowed to ages under 18 (the user's words asked for them: where=, or narrowing), or
    a person with no age pick whose stated age reads under 18 (narrow.py's entry["ages"]).
    An age pick left unnarrowed draws adults, so its person is an adult."""
    vocab = vocabulary()
    out: Dict[str, List[str]] = {}
    filters = entry.get("filters") or {}
    read = entry.get("ages") or {}
    for c in entry.get("choices") or []:
        leaf = vocab.resolve(c.get("cls")) if c.get("cls") else None
        if leaf is None or leaf.id != AGE_LIST:
            continue
        if isinstance(filters.get(c.get("id")), list):
            young = minor_ages(filters[c["id"]])
        elif c.get("said") and person_of(str(c["id"])) not in read:
            # The age is the user's own words and always drawn (said=), and nothing narrowed or
            # read it: one of the list's ages counts as itself; anything else isn't known to be
            # an adult's, so the person's pools are a minor's until a reading says otherwise.
            said = str(c["said"])
            young = minor_ages([said]) if any(v.text == said for v in leaf.values) \
                else tuple(v.text for v in leaf.values if v.minor)
        else:
            continue
        if young:
            out.setdefault(person_of(str(c["id"])), []).extend(young)
    for person, ages in (entry.get("ages") or {}).items():
        young = minor_ages(ages if isinstance(ages, list) else [])
        if young:
            out.setdefault(str(person), []).extend(young)
    return tuple((p, tuple(dict.fromkeys(a))) for p, a in sorted(out.items()))


# --------------------------------------------------------------------------- the on-disk cache

def gen_key(spec: PickSpec, context: Dict[str, Any], signature: str, mode: str, elaborate: bool,
            lists: Sequence[Tuple[str, str, Sequence[str]]] = (), version: str = OPTIONS_VERSION,
            lineage: str = "", intent: str = "", cls: str = "", minor: Sequence[str] = (), said: str = "",
            zone: str = "") -> str:
    """The generated pool's identity across prompts: what the pick is, the values of the
    picks it depends on, the context signature, the user's lists it is shown (those it
    doesn't depend on), and the style options are written in. `version` names an older
    pool (a replay): opts-1 showed the generator no lists."""
    shown = sorted([label, list(opts)] for cid, label, opts in lists if cid not in context and cid != spec.id)
    if version == FIRST_OPTIONS_VERSION:
        shown = []
    blob = json.dumps({
        "v": version, "about": _norm(spec.about or spec.label), "deps": sorted((k, str(v)) for k, v in context.items()),
        # a program's edit lineage when it has one (so untouched picks keep their options
        # through prompt edits), else the prompt's context signature
        **({"lineage": lineage} if lineage else {"context": _norm(signature)}),
        **({"intent": _norm(intent)} if intent else {}),
        **({"cls": cls} if cls else {}),   # a bound pick's generated options extend its list
        **({"minor": sorted(minor)} if minor else {}),   # written for a person under 18
        **({"said": _norm(said)} if said else {}),   # alternatives to the user's own words
        **({"zone": zone} if zone else {}),   # a slot's pool: kinds of its words, or things instead
        "mode": mode, "elaborate": bool(elaborate), **({"lists": shown} if shown else {}),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class OptionStore:
    """Generated options, one append-only JSONL file per pool: one line per generation
    call, `{"round", "inputs", "options", "model", "at"}`. Nothing is rewritten or
    deleted; a pool is its lines' options in order, first occurrence wins."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._mem: Dict[str, Tuple[int, List[Dict[str, Any]]]] = {}

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.jsonl"

    @property
    def pools(self) -> Any:
        """The vocabulary pools draws recorded, each kept once (compact.py)."""
        from prompt_programs.compact import PoolStore
        return PoolStore(self.root / "pools")

    def records(self, key: str) -> List[Dict[str, Any]]:
        p = self._path(key)
        try:
            size = p.stat().st_size
        except OSError:
            return []
        hit = self._mem.get(key)
        if hit and hit[0] == size:
            return hit[1]
        out: List[Dict[str, Any]] = []
        try:
            text = p.read_text("utf-8")
        except OSError:
            return []
        for ln in text.splitlines():
            try:
                rec = json.loads(ln)
            except ValueError:
                continue  # a line another process is still writing
            if isinstance(rec, dict):
                out.append(rec)
        self._mem[key] = (size, out)
        return out

    def options(self, key: str) -> List[str]:
        seen, out = set(), []
        for rec in self.records(key):
            for o in rec.get("options") or []:
                if _norm(o) not in seen:
                    seen.add(_norm(o))
                    out.append(str(o))
        return out

    def rounds(self, key: str) -> int:
        return len(self.records(key))

    def has_round(self, key: str, round_: int) -> bool:
        return any(r.get("round") == round_ for r in self.records(key))

    def append(self, key: str, record: Dict[str, Any]) -> None:
        p = self._path(key)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            self._mem.pop(key, None)

    # Per-program flags (a pick whose shared pool failed the bad-pool check gets options
    # written for this prompt's own text).
    def _flags_path(self, program_key: str) -> Path:
        return self.root / "programs" / f"{program_key}.json"

    def specific(self, program_key: str) -> List[str]:
        if not program_key:
            return []
        try:
            return list(json.loads(self._flags_path(program_key).read_text("utf-8")).get("specific") or [])
        except (OSError, ValueError):
            return []

    def mark_specific(self, program_key: str, pick_id: str) -> None:
        if not program_key:
            return
        with self._lock:
            have = self.specific(program_key)
            if pick_id in have:
                return
            p = self._flags_path(program_key)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({"specific": have + [pick_id]}), "utf-8")
            os.replace(tmp, p)


# --------------------------------------------------------------------------- generation

@dataclass
class OptionJob:
    key: str                       # gen_key: where the options are stored
    spec: PickSpec
    context: Dict[str, Any]
    program: ProgramContext
    signature: str
    round: int
    existing: List[str] = field(default_factory=list)
    avoid: List[str] = field(default_factory=list)   # options judged wrong here (bad-pool check)
    project_id: Optional[int] = None
    removed: List[str] = field(default_factory=list)  # what the user deleted from this choice
    examples: List[str] = field(default_factory=list)  # a bound pick's list values shown as examples (vocab.py)


Generator = Callable[[OptionJob], Awaitable[Tuple[List[str], str]]]

_GEN_SYSTEM = """You write options for one detail of an image prompt. Each image draws one option and puts
it where the detail stands, so every option must fit the whole prompt.

Write {count} options for {what}. Order them from the most typical for this prompt to the least.
- The first ones are what you'd expect if the prompt didn't say; then common alternatives; the
  last two or three are unusual but real (rare, never impossible).
- Never contradict anything the prompt states{given}.
- Each is a concrete, visual phrase that reads naturally in place of [{label}]{style}.
- Each differs for real from the others and from the existing options (no synonyms).
- Say what to show, never what to leave out (no "no", "not", "without").
- Use US English spelling and words ("color", "gray", "pajamas", "sneakers").
- Each string is the option itself, exactly as it goes in the prompt: no numbering, notes or
  remarks.

{reply}"""

_REPLY_TEXT = "Reply with only a JSON list of strings, like [\"a first option\", \"a second option\"]."
_REPLY_TOOL = "Give the options with the write_options tool."

# Option generation's structured reply: a tool call where the endpoint makes tool calls, else a
# reply that must be exactly a JSON list of strings. Nothing is picked out of free text.
OPTIONS_TOOL = {"type": "function", "function": {
    "name": "write_options", "description": "Give the options for the detail.",
    "parameters": {"type": "object", "properties": {"options": {
        "type": "array", "description": "The options, most typical first.",
        "items": {"type": "string", "description": "One option, exactly as it goes in the prompt."}}},
        "required": ["options"]}}}


def generation_messages(job: OptionJob, count: int = BATCH_SIZE, tool: bool = False) -> List[Dict[str, str]]:
    spec, prog = job.spec, job.program
    what = f'"{spec.label}" ({spec.about})' if spec.about and _norm(spec.about) != _norm(spec.label) else f'"{spec.label}"'
    given = ""
    if job.context:
        given = " or these details already chosen: " + "; ".join(f"{k} = {v}" for k, v in job.context.items())
    style = "; tags, a few words each" if prog.mode == "keyword" else (
        "; short, a few words, like the user's own wording" if not prog.elaborate else "; match the examples' length and style")
    system = _GEN_SYSTEM.format(count=count, what=what, given=given, label=spec.label, style=style,
                                reply=_REPLY_TOOL if tool else _REPLY_TEXT)
    lines = [f"The prompt, with the details that vary shown as [Label]:\n{prog.template or job.signature}"]
    if job.signature and job.signature != prog.template:
        lines += ["", f"In short: {job.signature}"]
    open_lists = [(label, opts) for cid, label, opts in prog.lists if cid not in job.context and cid != spec.id]
    if open_lists:  # a pool shared across a list's values: cover each of them
        lines += ["", "These details are the user's own lists; each image draws one option. Write options that "
                      "suit each of them (an image keeps only the ones that fit what it drew):",
                  *[f"- [{label}]: {', '.join(opts[:12])}{' …' if len(opts) > 12 else ''}" for label, opts in open_lists]]
    if job.examples:  # a vocabulary list's spread: how wide the range is, in the form each option takes
        lines += ["", "Examples from a curated list, to show the form and how wide the range is (write new ones, "
                      "as varied as these):", *[f"- {o}" for o in job.examples]]
    else:
        examples = list(dict.fromkeys([*spec.seeds, *spec.literal]))
        if examples:
            lines += ["", "Examples of the style (you may include them):", *[f"- {o}" for o in examples]]
    if job.existing:
        lines += ["", "Existing options (don't repeat these):", *[f"- {o}" for o in job.existing]]
    if job.avoid:
        lines += ["", "These were judged to contradict this prompt; write options that fit it instead:",
                  *[f"- {o}" for o in job.avoid]]
    intent = dict(job.program.intents).get(job.spec.id)
    if intent and job.spec.zone == "instead":
        lines += ["", f'The user wrote "{intent}" here. Write other options they might choose instead: other things '
                      "that could stand in the same place in the prompt, each a specific one, in the same form as "
                      "their words."]
    elif intent:
        lines += ["", f'The user asked for this detail in their own words: "{intent}". That is a rule, not an example: '
                      "every option must be within it (\"1970s or 1980s cars\" means only cars from those two decades). "
                      "Each option is one of the things their words name, named the way a person would say it, and "
                      "nothing added: for \"country\", \"Japan\", never \"Japan, with misty mountains and temples\"."]
    if job.spec.zone:
        lines += ["", f"Each option replaces exactly [{spec.label}] in the prompt: the same form as the user's words, "
                      "no article unless they have one."]
    if job.removed:
        lines += ["", "The user deleted these: never write them or any wording of them:", *[f"- {o}" for o in job.removed]]
    if job.spec.said:
        lines += ["", f'The user wrote "{job.spec.said}" for this detail, and every image shows it unless they choose '
                      "another option. Write other options they might choose instead: the same kind of thing, each a "
                      "specific one, in the same form as their words."]
    if job.spec.minor:
        lines += ["", f"This detail is for a person under 18 ({minor_words(job.spec.minor)}), as the prompt asks: "
                      "every option must be what someone that age would ordinarily wear, do or look like."]
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(lines)}]


def minor_words(ages: Sequence[str]) -> str:
    """A minor person's possible ages, for the generator: "13–14 or 15–17 years old"."""
    spans = [a[: -len("-year-old")] if a.endswith("-year-old") else a for a in ages]
    return (", ".join(spans[:-1]) + " or " + spans[-1] if len(spans) > 1 else spans[0]) + " years old"


def read_options(reply: str) -> Optional[List[str]]:
    """The options in a text reply that is exactly a JSON list of strings (or an object with
    an "options" list), optionally in one code fence. None for anything else: a reply with
    text around its list, or a list of anything but strings, is asked again, never mined."""
    text = (reply or "").strip()
    fenced = re.fullmatch(r"```[A-Za-z]*\s*(.*?)\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        got = json.loads(text)
    except ValueError:
        return None
    return _string_list(got)


def _string_list(got: Any) -> Optional[List[str]]:
    if isinstance(got, dict):
        got = got.get("options")
    if isinstance(got, list) and all(isinstance(x, str) for x in got):
        return list(got)
    return None


def parse_options(reply: str, limit: int = 2 * BATCH_SIZE) -> List[str]:
    """The usable options of a text reply (see read_options); [] when it isn't a JSON list."""
    return [o for o in (clean_option(x) for x in read_options(reply) or []) if o][:limit]


_MARKUP = re.compile(r"<\||\|>|</?[A-Za-z][A-Za-z0-9]*>|\*\*")


def torn(o: Any) -> bool:
    """A string that a tool-call parser tore out of a model's reply, not one option the model
    wrote: it carries a line break, an unpaired double quote, the model's own string delimiters
    or other markup. A quantized local model's tool calls come back like this often
    ('a maroon red door<|"|>', 'fear: [\n  "a weary look'), and its neighbors in that list are
    then pieces of options split at their commas, which nothing can tell from whole ones."""
    s = str(o).strip()
    quotes = len(re.findall(r'(?<!\d)"', s))   # 12" is inches, not a quotation mark
    return "\n" in s or quotes % 2 == 1 or bool(_MARKUP.search(s))


def clean_option(o: Any) -> Optional[str]:
    """One option as it goes in a pool, or None when it can't be one: empty, longer than a
    phrase, no letters, code-like (brackets, a trailing colon or question mark) or torn."""
    o = str(o).strip()
    if len(o) >= 2 and o[0] == o[-1] == '"':
        o = o[1:-1].strip()
    if (not o or len(o) > 120 or len(o.split()) > 16 or not re.search(r"[^\W\d_]", o)
            or o.startswith(("`", "[", "{")) or o.endswith((":", "?")) or torn(o)):
        return None
    return o


_RETRY_TEXT = ("That reply wasn't a JSON list of strings, so none of it could be used. Reply with only the JSON "
               "list of the options, nothing before or after it.")

# endpoints (api base, model) whose option calls made no tool call even when offered one: text from then on
_TEXT_ONLY: set = set()
# endpoints whose tool calls came back torn, and how often; at TORN_LIMIT they get the text form too
_TORN: Dict[Tuple[str, str], int] = {}
TORN_LIMIT = 2


async def _ask_options(messages: List[Dict[str, Any]], project_id: Optional[int],
                       tool: bool) -> Tuple[str, Optional[str]]:
    """One option-writing call: (text content, the write_options call's arguments or None).
    With tool=False, a plain completion (the writer's _ask_model). Raises what the call raises."""
    from prompt_programs import program as prep
    if not tool:
        return await prep.ask_model(messages, project_id, max_tokens=2000), None
    from agent.v2.llm_options import agent_llm_options
    from llm import llm_completion
    from llm_correlation import llm_correlation_context
    cfg, _ = await prep.model_endpoint(project_id)
    with llm_correlation_context("prompt-program"):
        resp = await llm_completion(cfg, messages, tools=[OPTIONS_TOOL], max_tokens=2000, temperature=0.3,
                                    **agent_llm_options(enable_thinking=False))
    call = next((c for c in resp.tool_calls or [] if c.name == "write_options"), None)
    return resp.content or "", (call.arguments if call is not None else None)


async def _endpoint(project_id: Optional[int]) -> Tuple[Tuple[str, str], bool]:
    """(endpoint id, whether to offer the write_options tool): unless the writer's endpoint is
    known to speak text only (prepare's protocol) or ignored the tool before."""
    from prompt_programs import program as prep
    try:
        cfg, protocol = await prep.model_endpoint(project_id)
        endpoint = prep.endpoint_id(cfg)
    except Exception:  # no config to look at: plain text
        return ("", ""), False
    return endpoint, protocol == "tools" and endpoint not in _TEXT_ONLY


async def write_options(job: OptionJob, count: int = BATCH_SIZE) -> List[str]:
    """Options for a job as structured output: the write_options tool where the endpoint
    makes tool calls, else a reply that is exactly a JSON list of strings. At most two calls:
    after a broken or missing tool call the second asks for the plain JSON list, after an
    unreadable text reply it is told what was wrong. [] if neither is readable."""
    from prompt_programs import program as prep
    endpoint, tool = await _endpoint(job.project_id)
    messages: List[Dict[str, Any]] = generation_messages(job, count, tool)
    for attempt in range(2):
        try:
            content, args = await _ask_options(messages, job.project_id, tool)
        except Exception as e:
            if not (tool and prep.no_tools_error(e)):
                raise
            prep.PROTOCOL[endpoint] = "text"  # the endpoint takes no tools: text from now on
            tool, messages = False, generation_messages(job, count, False)
            content, args = await _ask_options(messages, job.project_id, False)
        if args is not None:
            try:
                got = _string_list(json.loads(args) if isinstance(args, str) else args)
            except ValueError:
                got = None
            if got is not None and any(torn(x) for x in got):
                # the parser tore this call: none of its strings can be trusted (see torn())
                log.info(f"[fluent-options] torn tool call for {job.spec.label!r} (try {attempt + 1}): {str(args)[:120]!r}")
                _TORN[endpoint] = _TORN.get(endpoint, 0) + 1
                if _TORN[endpoint] >= TORN_LIMIT:  # it keeps happening: this endpoint gets the text form
                    _TEXT_ONLY.add(endpoint)
                got = None
        else:
            got = read_options(content)
            if tool:  # offered the tool and answered in text: this endpoint gets the text form
                _TEXT_ONLY.add(endpoint)
        if got is not None:
            return [o for o in (clean_option(x) for x in got) if o][: 2 * count]
        log.info(f"[fluent-options] unreadable reply for {job.spec.label!r} (try {attempt + 1}): {content[:120]!r}")
        if args is not None or tool:  # a broken or missing tool call: the retry asks for the plain JSON list
            tool, messages = False, generation_messages(job, count, False)
        else:
            messages = messages + [{"role": "assistant", "content": content or "(no reply)"},
                                   {"role": "user", "content": _RETRY_TEXT}]
    return []


async def suggest_options(entry: Dict[str, Any], choice_id: str, existing: Sequence[str], count: int,
                          project_id: Optional[int], zone: Optional[str] = None) -> List[str]:
    """New options for one choice of a prepared program (the card's More like these and
    Reroll all), written the way background generation writes them. Never during a run.
    `zone`: one of a slot choice's zones (choices.py), written as that zone's pool is."""
    from prompt_programs.choices import bound_zones, free_zones
    from prompt_programs.fill import ProgramError
    choice = next((c for c in entry.get("choices") or [] if c.get("id") == choice_id), None)
    if not choice or choice.get("kind") != "pick":
        raise ProgramError(f"No choice {choice_id} to write options for.")
    count = max(1, min(24, int(count)))
    have = list(dict.fromkeys(str(x) for x in existing if str(x).strip()))
    seeds = [str(o) for o in (choice.get("options") or [])[:3]]
    zoned: Dict[str, List[str]] = free_zones(entry, choice_id) or dict(zip(("kinds", "instead"), bound_zones(entry, choice_id) or ()))
    if zone and zone not in zoned:
        raise ProgramError(f"{choice.get('label') or choice_id} has no {zone} options to write.")
    if zone:
        seeds = list(zoned[zone])[:3]
    spec = PickSpec(str(choice_id), str(choice.get("label") or choice_id), str(choice.get("about") or ""),
                    int(choice.get("phase") or 1), str(choice.get("source") or "text"), "pick",
                    seeds=seeds, cls=str(choice.get("cls") or ""), zone=zone or "")
    program = ProgramContext.of(entry)
    if spec.cls != AGE_LIST:
        p = person_of(spec.id)
        spec.minor = tuple(dict.fromkeys(a for who, ages in program.minors if owns(who, p) for a in ages))
    job = OptionJob(key="", spec=spec, context={}, program=program, signature=program.signature, round=0,
                    existing=have, project_id=project_id)
    seen = {_norm(o) for o in have}
    out: List[str] = []
    for _ in range(2):  # one retry if the model repeats itself
        for o in await write_options(job, count):
            if _norm(o) not in seen and len(out) < count:
                seen.add(_norm(o))
                out.append(o)
        if len(out) >= count:
            break
        job.existing = have + out
    if not out:
        raise ProgramError("The model didn't write any new options.")
    return out


_CHECK_SYSTEM = """You check options written for one detail of an image prompt. Each image draws one option and puts it where the detail stands, shown as [its label] in the prompt.

Give each numbered option one of three answers:

- "no": it is wrong here. It is not the kind of thing the detail asks for, or lies outside a limit the detail's own words set ("long red hair hairstyle" is long and red, "1920s evening wear" is from the 1920s); or it contradicts something the prompt states or undoes what the prompt says is happening; or it brings in a place, a time or a thing that cannot be where the prompt is set.
- "rare": nothing is wrong, but it is a stretch for this prompt.
- "yes": it fits.

Unusual is welcome. When unsure between "rare" and "yes", say "yes". Keep "no" for what is actually wrong.

Reply with one JSON object per line and nothing else, in the form {"id": 1, "answer": "yes"}."""
_CHECK_ANSWER = re.compile(r'"id"\s*:\s*(\d+)[^{}]*"answer"\s*:\s*"(yes|rare|no)"')


async def check_options(job: OptionJob, options: List[str]) -> List[str]:
    """The options that fit, as one more model call reads them against the prompt and the
    detail's own words: a "no" is left out, a "rare" goes last (a pool weighs its options by
    their order). A list is read once, when it is written, so a draw never pays for it. Any
    failure keeps the options as written: the check never costs a pool its options."""
    if not options:
        return options
    from prompt_programs import program as prep
    spec, prog = job.spec, job.program
    what = f'"{spec.label}" ({spec.about})' if spec.about and _norm(spec.about) != _norm(spec.label) else f'"{spec.label}"'
    lines = [f"The prompt, with the details that vary shown as [Label]:\n{prog.template or job.signature}", "",
             f"The detail: {what}"]
    if job.context:
        lines.append("Already chosen: " + "; ".join(f"{k} = {v}" for k, v in job.context.items()))
    lines += ["", "The options:", *[f"{i + 1}. {o}" for i, o in enumerate(options)]]
    try:
        reply = await prep.ask_model([{"role": "system", "content": _CHECK_SYSTEM},
                                       {"role": "user", "content": "\n".join(lines)}], job.project_id, 40 * len(options) + 80)
    except Exception as e:
        log.info(f"[fluent-options] the check of {spec.label!r} failed, keeping its options as written: {e}")
        return options
    got = {int(m.group(1)): m.group(2) for m in _CHECK_ANSWER.finditer(reply or "")}
    if len(got) * 2 < len(options):   # an answer that covers too little says nothing
        return options
    kept = [o for i, o in enumerate(options) if got.get(i + 1, "yes") == "yes"]
    rare = [o for i, o in enumerate(options) if got.get(i + 1) == "rare"]
    dropped = [o for i, o in enumerate(options) if got.get(i + 1) == "no"]
    if dropped:
        log.info(f"[fluent-options] {spec.label!r}: left out {dropped}")
    return (kept + rare) or options


async def llm_generator(job: OptionJob) -> Tuple[List[str], str]:
    """Options from the configured chat model (the same role and plumbing as prepare), read
    once more against the prompt before they are kept (check_options)."""
    return await check_options(job, await write_options(job)), "tool_assistant"


YIELD_POLL = 0.25   # seconds between looks while the filler gives way to a prepare


class OptionFiller:
    """Background generation: a priority queue worked on the event loop, high first.
    `submit()` is safe from any thread (realize() may run in a worker thread). A pool
    has at most one job queued or running; asking again at high priority promotes it.

    It is background work on the same chat model a prepare waits on: while `paused()` (a
    prepare in flight) no job starts, and a queued low-priority job whose program isn't
    `current()` (the user has edited the prompt since) is dropped; a later draw of that
    program queues its pools again."""

    def __init__(self, store: OptionStore, generator: Generator = llm_generator, workers: int = 2,
                 paused: Optional[Callable[[], bool]] = None, current: Optional[Callable[[OptionJob], bool]] = None):
        self.store, self.generator, self.workers = store, generator, workers
        self.paused = paused or (lambda: False)
        self.current = current or (lambda job: True)
        self.dropped = 0
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._heap: List[Tuple[int, int, str]] = []
        self._jobs: Dict[str, Tuple[int, OptionJob]] = {}
        self._running: Dict[str, OptionJob] = {}   # key -> the job holding it
        self._seq = itertools.count()
        self._lock = threading.Lock()
        self._wake: Optional[asyncio.Event] = None
        self._tasks: List[asyncio.Task] = []
        self.calls = 0
        self.failures = 0

    # -- state the options service reads
    def busy(self, key: str) -> bool:
        with self._lock:
            return key in self._jobs or key in self._running

    def _release(self, job: OptionJob) -> None:
        """Give up `job`'s hold on its pool (callers hold the lock). Only the job that
        took the pool can release it: a later round may already have taken it."""
        if self._running.get(job.key) is job:
            del self._running[job.key]

    # -- queueing
    def submit(self, job: OptionJob, priority: str = "low") -> bool:
        rank = PRIORITY.get(priority, 1)
        with self._lock:
            if job.key in self._running:
                return False
            have = self._jobs.get(job.key)
            if have is not None and have[0] <= rank:
                return False
            if have is not None and not job.avoid:
                job.avoid = have[1].avoid
            self._jobs[job.key] = (rank, job)
            heapq.heappush(self._heap, (rank, next(self._seq), job.key))
        self._poke()
        return True

    def attach(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Start working on `loop` (the running one by default). Jobs queued before a
        loop was attached start then."""
        loop = loop or asyncio.get_running_loop()
        if self.loop is loop and self._tasks and not all(t.done() for t in self._tasks):
            return
        self.loop = loop
        self._wake = asyncio.Event()
        self._tasks = [loop.create_task(self._worker()) for _ in range(self.workers)]
        self._wake.set()

    def _poke(self) -> None:
        loop, wake = self.loop, self._wake
        if loop is None or wake is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            wake.set()
        else:
            loop.call_soon_threadsafe(wake.set)

    def _next(self) -> Optional[OptionJob]:
        with self._lock:
            while self._heap:
                rank, _, key = heapq.heappop(self._heap)
                have = self._jobs.get(key)
                if have is None or have[0] != rank:
                    continue  # promoted or already taken
                del self._jobs[key]
                if rank == PRIORITY["low"] and not self._is_current(have[1]):
                    self.dropped += 1
                    continue
                self._running[key] = have[1]
                return have[1]
        return None

    def _is_current(self, job: OptionJob) -> bool:
        try:
            return bool(self.current(job))
        except Exception:
            return True

    def _paused(self) -> bool:
        try:
            return bool(self.paused())
        except Exception:
            return False

    async def _worker(self) -> None:
        assert self._wake is not None
        while True:
            if self._paused():  # a prepare is waiting on the same chat model: let it go first
                await asyncio.sleep(YIELD_POLL)
                continue
            job = self._next()
            if job is None:
                self._wake.clear()
                if self._heap:
                    continue
                await self._wake.wait()
                continue
            try:
                await self.run(job)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # one pool failing never stops the queue
                self.failures += 1
                log.warning(f"[fluent-options] generating {job.spec.label!r} failed: {e}")
            finally:
                with self._lock:
                    self._release(job)

    async def run(self, job: OptionJob) -> List[str]:
        """Generate one round for a pool and append it (unless that round exists)."""
        if not self.store.has_round(job.key, job.round):
            started = time.monotonic()
            options, model = await self.generator(job)
            self.calls += 1
            have = {_norm(o) for o in job.existing}
            cleaned = [c for c in (clean_option(x) for x in options) if c]
            gone = {_norm(x) for x in job.removed}
            fresh = [o for o in dict.fromkeys(cleaned) if _norm(o) not in have and _norm(o) not in gone]
            self.store.append(job.key, {
                "round": job.round, "options": fresh, "model": model, "at": time.time(),
                "seconds": round(time.monotonic() - started, 2),
                "inputs": {"about": job.spec.about, "label": job.spec.label, "context": job.context,
                           "signature": job.signature, "mode": job.program.mode, "elaborate": job.program.elaborate,
                           "seeds": job.spec.seeds, "avoid": job.avoid},
            })
        with self._lock:
            self._release(job)
        return self.store.options(job.key)

    async def drain(self) -> None:
        """Run every queued job now, in priority order (for evaluation and tests)."""
        while True:
            job = self._next()
            if job is None:
                return
            try:
                await self.run(job)
            except Exception as e:
                self.failures += 1
                log.warning(f"[fluent-options] generating {job.spec.label!r} failed: {e}")
            finally:
                with self._lock:
                    self._release(job)


# --------------------------------------------------------------------------- the options service

class GeneratedOptions:
    """The options service for realize(): user lists exactly, everything else seeds plus
    generated options. Each pool is read once per instance (one draw), so a fill landing
    mid-draw can't change it; `limits` truncates pools to a recorded revision's lengths."""

    def __init__(self, store: Optional[OptionStore], program: ProgramContext,
                 edits: Optional[Dict[str, Dict[str, Any]]] = None, filler: Optional[OptionFiller] = None,
                 limits: Optional[Dict[str, Any]] = None,
                 project_id: Optional[int] = None, generate: bool = True,
                 version: Optional[str] = None, context: bool = True,
                 mine: Optional[Dict[str, Sequence[str]]] = None, zones: Optional[Dict[str, Sequence[str]]] = None):
        self.store, self.program, self.filler = store, program, filler
        # The zones chosen per slot pick (drawn from together); a pick with none chosen draws its kinds.
        self.zones = {str(k): [str(z) for z in v] for k, v in (zones or {}).items()}
        # The user's own options kept for each vocabulary list (additions.py), offered by every
        # choice bound to that list; and, per choice read, which of them its pool holds and
        # whether each is drawn only once ticked (the picker shows those apart).
        self.mine = {str(k): [str(x) for x in v] for k, v in (mine or {}).items()}
        self.mine_shown: Dict[str, Dict[str, bool]] = {}
        # The pools' options version: a replay reads the version its revision drew from,
        # and never writes to an older one.
        self.version = version or OPTIONS_VERSION
        generate = generate and self.version == OPTIONS_VERSION
        self.edits = edits or {}
        self.literal = LiteralOptions(self.edits)
        self.limits = limits or {}
        self.project_id = project_id
        self.generate = generate and store is not None
        self.specific = set(store.specific(program.key)) if store is not None else set()
        self.filters = {k: v for k, v in program.filters}
        self.minor_ages = dict(program.minors)    # read by the draw engine (draws._Engine._minors)
        self.list_ages = {k: dict(v) for k, v in program.list_ages}   # read by the draw engine too
        # Context (vocab.py), read by the draw engine: off to replay a revision drawn before it.
        self.context = context
        self.stated_context: Dict[Optional[str], Dict[str, Tuple[str, ...]]] = {}
        for who, cls, sub in program.stated:
            for f, fam in given_families(cls, sub).items():
                have = self.stated_context.setdefault(who if vocabulary().scope(f) == "person" else None, {})
                have[f] = tuple(sorted(set(have.get(f, ())) | set(fam)))
        # How a person presents, as the program says it (person(presentation=...) puts it on their face
        # and build picks as where={"presentation": ...}): context for that person's other details, so a
        # man isn't drawn a sundress. From the picks' own filters, never from the user's words.
        for cid, text in program.facets:
            said = _presentation(text)
            if said and vocabulary().scope("presentation") == "person":
                self.stated_context.setdefault(person_of(cid), {})["presentation"] = (said,)
        self.list_context: Dict[str, Dict[str, Dict[str, Tuple[str, ...]]]] = {}
        for cid, value, cls, sub in program.list_context:
            for f, fam in given_families(cls, sub).items():
                have = self.list_context.setdefault(cid, {}).setdefault(value, {})
                have[f] = tuple(sorted(set(have.get(f, ())) | set(fam)))
        self._pools: Dict[str, Pool] = {}
        self.requests: List[Tuple[str, str]] = []
        self.queued: List[str] = []
        self._seen: Dict[str, Tuple[PickSpec, Dict[str, Any]]] = {}

    @property
    def revision_version(self) -> Optional[str]:
        """The options version a draw's revision records (none for the first, so revisions
        drawn before versions were recorded keep their ids)."""
        return None if self.version == FIRST_OPTIONS_VERSION else self.version

    def seen_specs(self) -> List[Tuple[PickSpec, Dict[str, Any]]]:
        """Every generated pick and dependency context read through this service."""
        return list(self._seen.values())

    def drawn_context(self, cid: str) -> List[Tuple[Tuple[str, Tuple[str, ...]], ...]]:
        """The context (vocab.py) each pool of pick `cid` read since the last reset() was drawn in."""
        return [self._seen[k][0].context for k in self._pools if k in self._seen and self._seen[k][0].id == cid]

    def reset(self) -> None:
        """Forget the pools read so far (the next get() reads the cache again)."""
        self._pools.clear()

    # -- identity
    # -- the vocabulary, as narrowed for this program (where=)
    def _leaf(self, spec: PickSpec) -> Optional[Leaf]:
        """The list a pick draws from: its bound leaf, unless where= left nothing of it."""
        leaf = bound(spec)
        if leaf is not None and self.filters.get(spec.id) == ():
            return None
        return leaf

    def _allowed(self, spec: PickSpec) -> Optional[Tuple[str, ...]]:
        """The narrowed subset of a bound pick's list, or None when it isn't narrowed."""
        return self.filters.get(spec.id) or None

    def _grows(self, spec: PickSpec) -> bool:
        """generated_pick, with where= taken into account: a closed list left empty by its
        words draws unbound, so it grows like any generated pick."""
        if spec.kind != "pick" or spec.source == "list":
            return False
        leaf = self._leaf(spec)
        if leaf is not None:
            return not leaf.closed
        return bool(spec.about.strip())

    def _where(self, spec: PickSpec, context: Dict[str, Any]) -> Tuple[str, str, str]:
        """(revision pool key, storage key, signature) for a generated pick."""
        specific = spec.id in self.specific and self.program.template != self.program.signature
        signature = self.program.template if specific else self.program.signature
        key = pool_key(spec, context) + (" | written for this prompt" if specific else "")
        if spec.cls:  # a revision records the bound pool itself, so the key needn't name a version
            key += f" | {spec.cls}"
            if spec.restrict:
                key += " restrict " + ";".join(f"{f}={','.join(v)}" for f, v in spec.restrict)
        # A pool's identity names the user's words and any facet filter (the same text pools were
        # keyed by before the words and the filter were told apart, so recorded revisions still match).
        intent = " ".join(x for x in (dict(self.program.intents).get(spec.id, ""),
                                      dict(self.program.facets).get(spec.id, "")) if x)
        if spec.cls and spec.id in self.filters:  # narrowed by where= (an empty subset: drawn without the list)
            key += f" where {intent}"
        if spec.minor:  # a person under 18: adult-only values out, options written for that age
            key += " | under 18"
        if spec.said:  # alternatives to the user's own words
            key += f" | said {spec.said}"
        if spec.context and self._leaf(spec) is not None:   # last: a replay finds its recorded context
            recorded = [k for k in self.limits if k.startswith(key + " | context ")]
            key = recorded[0] if len(recorded) == 1 else key + context_suffix(spec)
        lineage = "" if specific else self.program.lineage
        # A slot's pools follow its reading: stored under the prompt it was first read in, still
        # written for the prompt as it is now.
        stored = signature if specific else dict(self.program.kept).get(spec.id, signature)
        return key, gen_key(spec, context, stored, self.program.mode, self.program.elaborate,
                            self.program.lists, self.version, lineage, intent, spec.cls, spec.minor,
                            spec.said, spec.zone), signature

    def get(self, spec: PickSpec, context: Dict[str, Any]) -> Pool:
        if spec.zones and not spec.zone:
            return self._zoned(spec, context)
        if not self._grows(spec) and self._leaf(spec) is None and not isinstance(self.limits.get(self._where(spec, context)[0]), list):
            return self.literal.get(spec, context)
        key, skey, signature = self._where(spec, context)
        if key in self._pools:
            return self._pools[key]
        self._seen.setdefault(key, (spec, dict(context)))
        pool, items, rounds = self._read(spec, context, key, skey)
        if self.generate and key not in self.limits and rounds < MAX_ROUNDS and self._grows(spec):
            if rounds == 0:
                self._submit(spec, context, skey, signature, "low", items)
            elif len(pool.items) < THIN:
                self._submit(spec, context, skey, signature, "high", items)
        pool.more_coming = bool(self.filler is not None and self.filler.busy(skey))
        self._pools[key] = pool
        return pool

    def zone_specs(self, spec: PickSpec) -> List[PickSpec]:
        """A slot pick's chosen zones, each as the spec its pool is read with: kinds when none is chosen."""
        have = dict(spec.zones)
        chosen = [z for z in self.zones.get(spec.id, ()) if z in have] or (["kinds"] if "kinds" in have else list(have)[:1])
        return [dataclasses.replace(spec, zone=z, seeds=list(have[z]), zones=()) for z in dict.fromkeys(chosen)]

    def _zoned(self, spec: PickSpec, context: Dict[str, Any]) -> Pool:
        """One pool from the chosen zones' pools. Several zones together are recorded whole
        on a revision (the zones grow apart), and a replay reads that record."""
        parts = self.zone_specs(spec)
        if len(parts) == 1:
            return self.get(parts[0], context)
        key = pool_key(spec, context) + " | " + "+".join(p.zone for p in parts)
        if key in self._pools:
            return self._pools[key]
        if isinstance(self.limits.get(key), list):
            pool = self._read(spec, context, key, "")[0]
        else:
            items: List[str] = []
            weights: List[float] = []
            own: set = set()
            held: Dict[str, float] = {}
            more = False
            for p in parts:
                got = self.get(p, context)
                for o, w in zip(got.items, got.weights):
                    if o not in items:
                        items.append(o)
                        weights.append(w)
                own |= set(got.own)
                held.update(got.held)
                more = more or got.more_coming
            pool = Pool(key, items, weights, more, True, own=frozenset(own), held=held)
        self._pools[key] = pool
        return pool

    def fresh_pool(self, spec: PickSpec, context: Dict[str, Any]) -> Pool:
        """The pool as the cache holds it now (no memo, no requests)."""
        key, skey, _ = self._where(spec, context)
        return self._read(spec, context, key, skey)[0]

    def rewrite_for_prompt(self, spec: PickSpec, context: Dict[str, Any], avoid: Sequence[str]) -> None:
        """The bad-pool fix: options written for this prompt's own text, at high
        priority. A pool keyed by a shared signature switches this pick to a pool keyed
        by the prompt itself; a pool already keyed by the prompt gets a new round told
        which options didn't fit. A closed vocabulary list is never rewritten."""
        if not self._grows(spec):
            return
        if self.program.template != self.program.signature and spec.id not in self.specific:
            if self.store is not None:
                self.store.mark_specific(self.program.key, spec.id)
            self.specific.add(spec.id)
            self._pools.clear()
            avoid = ()
        key, skey, signature = self._where(spec, context)
        existing = self.store.options(skey) if self.store is not None else []
        self._submit(spec, context, skey, signature, "high", existing, avoid)

    def _read(self, spec: PickSpec, context: Dict[str, Any], key: str, skey: str) -> Tuple[Pool, List[str], int]:
        recorded = self.limits.get(key)
        if isinstance(recorded, list):  # a revision's whole bound pool, even for a list since removed
            roles = {str(e[0]): dict(e[2]) for e in recorded if len(e) > 2 and isinstance(e[2], dict)}
            # Opt-in values not asked for now stand by at weight 0, as in a fresh pool (an old
            # record held them at a positive weight); a kept or pinned value still draws.
            leaf = self._leaf(spec)
            # (A narrowed pool's rest was recorded at weight 0 already; its subset keeps its weights.)
            allowed = self._allowed(spec)
            stand = leaf.pool_values(allowed, bool(spec.minor))[1] if leaf else []
            zero = {v.text for v in stand} if allowed is None else set()
            own = frozenset(str(x) for x in [*((self.edits.get(spec.id) or {}).get("add") or []), *self._mine_of(spec)])
            return Pool(key, [str(e[0]) for e in recorded],
                        [0.0 if str(e[0]) in zero else float(e[1]) for e in recorded], False, True, roles,
                        own=own, held={v.text: v.weight for v in stand}), [], 0
        leaf = self._leaf(spec)
        if leaf is not None:
            return self._read_bound(spec, leaf, key, skey)
        written = list(dict.fromkeys([*spec.seeds, *spec.literal]))
        edit = self.edits.get(spec.id) or {}
        adds = [str(x) for x in edit.get("add") or [] if str(x).strip()]
        generated = self.store.options(skey) if self.store is not None else []
        items: List[str] = []
        seen = set()
        for o in [*written, *adds, *generated]:
            if _norm(o) not in seen:
                seen.add(_norm(o))
                items.append(o)
        weights = [_weight(i, len(written) + len(adds)) for i in range(len(items))]
        gone = {_norm(x) for x in edit.get("remove") or []}
        kept = [(o, w) for o, w in zip(items, weights) if _norm(o) not in gone]
        own = {o for o in adds}
        # A bound pick its words left nothing of (where=) draws unbound: the user's kept options
        # for its list are offered, drawn only once ticked (after the rest, so a replay's
        # recorded length leaves them out as it found them).
        have = {_norm(o) for o, _ in kept} | gone
        extra = [o for o in self._mine_of(spec) if _norm(o) not in have]
        if extra:
            kept += [(o, 0.0) for o in extra]
            own |= set(extra)
            self.mine_shown[spec.id] = {o: True for o in extra}
        # A slot's own words lead its kinds, drawn only when chosen ("as written" is a pin of them).
        words = dict(self.program.intents).get(spec.id, "") if spec.zone == "kinds" else ""
        held: Dict[str, float] = {}
        if words.strip() and _norm(words) not in {_norm(o) for o, _ in kept} | gone:
            kept.insert(0, (words, 0.0))
            held[words] = 1.0
        if isinstance(self.limits.get(key), (int, float)):  # replaying a recorded revision
            kept = kept[: int(self.limits[key])]
        pool = Pool(key, [o for o, _ in kept], [w for _, w in kept], False, own=frozenset(own), held=held)
        rounds = self.store.rounds(skey) if self.store is not None else 0
        return pool, items, rounds

    def _read_bound(self, spec: PickSpec, leaf: Leaf, key: str, skey: str) -> Tuple[Pool, List[str], int]:
        """A bound pick's pool: its list's eligible values weighted by tier, the user's
        additions, and for an open list the options generated to extend it, which share
        the pool's weight with the list. The writer's seeds aren't used: the list replaces
        them. Returns (pool, the generated options, generation rounds)."""
        recorded = self.limits.get(key)
        edit = self.edits.get(spec.id) or {}
        seen = {_norm(x) for x in edit.get("remove") or []}   # removed, then each option once

        def unique(pairs: List[Tuple[str, float]]) -> List[Tuple[str, float]]:
            out = []
            for o, w in pairs:
                if _norm(o) not in seen:
                    seen.add(_norm(o))
                    out.append((o, w))
            return out
        allowed = self._allowed(spec)
        # Opt-in values (ages under 18) not asked for, and the rest of a narrowed list, stand by
        # at weight 0: the picker offers them and a pin draws them. A person under 18 has no
        # adult-only values (vocab.py).
        values, standby = leaf.pool_values(allowed, bool(spec.minor))
        if leaf.slots:  # a removal names the filled look a draw showed: it removes its template
            gone = [str(x) for x in edit.get("remove") or []]
            values = [v for v in values if not any(template_matches(v.text, g) for g in gone)]
        if spec.restrict:  # a palette pick: only the palettes its template allows (all, if none would be left)
            want = {f: list(vals) for f, vals in spec.restrict}
            values = [v for v in values if tags_match(v.tags, want)] or values
        # The user's own words (said=) lead a bound pick's pool, like an unbound pick's seeds.
        adds = [(str(x), 1.0) for x in edit.get("add") or [] if str(x).strip()]
        listed = unique(([(spec.said, 1.0)] if spec.said else []) + [(v.text, v.weight) for v in values] + adds)
        own = {o for o, _ in adds if _norm(o) not in {_norm(x) for x in edit.get("remove") or []}}
        # The user's options kept for this list (additions.py), after those added here: each as
        # one typical value, or drawn only once ticked where words decide (where=, said=) and
        # on the age list (no age drawn unasked). Their own: never dropped for a minor.
        held = bool(spec.said) or allowed is not None or leaf.id == AGE_LIST
        mine = unique([(o, 0.0 if held else TIER_WEIGHTS["typical"]) for o in self._mine_of(spec)])
        if mine:
            self.mine_shown[spec.id] = {o: w == 0 for o, w in mine}
            own |= {o for o, _ in mine}
        listed += [x for x in mine if x[1] > 0]
        if spec.context:  # weighted by what its scope drew (vocab.py); the user's additions keep theirs
            listed = leaf.weigh(listed, spec.context)
        generated = self.store.options(skey) if self.store is not None and not leaf.closed else []
        gen = unique([(o, GEN_DECAY ** i) for i, o in enumerate(generated)])
        if isinstance(recorded, (int, float)):  # a length recorded for this pool: truncate before weighting
            n = int(recorded)
            listed, gen = listed[:n], gen[: max(0, n - len(listed))]
        if gen and listed:
            lw, gw = sum(w for _, w in listed), sum(w for _, w in gen)
            listed = [(o, w * OPEN_SHARE / lw) for o, w in listed]
            gen = [(o, w * (1 - OPEN_SHARE) / gw) for o, w in gen]
        kept = [*listed, *gen, *[x for x in mine if x[1] == 0], *unique([(v.text, 0.0) for v in standby])]
        roles = {v.text: dict(v.roles) for v in values if v.roles}
        pool = Pool(key, [o for o, _ in kept], [w for _, w in kept], False, True, roles, own=frozenset(own),
                    held={v.text: v.weight for v in standby})
        rounds = self.store.rounds(skey) if self.store is not None and not leaf.closed else 0
        return pool, generated, rounds

    def _mine_of(self, spec: PickSpec) -> List[str]:
        """The user's kept options for the list a pick binds (none for a palette or no list)."""
        if not self.mine or not spec.cls or spec.source == "list":
            return []
        from prompt_programs.additions import list_id
        lid = list_id(spec.cls)
        return [o for o in self.mine.get(lid, []) if o.strip()] if lid else []

    def _examples(self, leaf: Leaf, spec: PickSpec, key: str) -> List[str]:
        """The generator's examples from a bound pick's list; templates are shown filled
        with a palette, so it writes whole looks, never slots."""
        got = leaf.examples(key, only=self._allowed(spec), minor=bool(spec.minor))
        palette = vocabulary().get(leaf.slots) if leaf.slots else None
        if palette is None or not palette.values:
            return got
        import random as _random
        rng = _random.Random(key)
        out = []
        for t in got:  # each template in a scheme it allows (a tuxedo is never shown in neon)
            tv = leaf.value(t)
            allowed = [p for p in palette.values if not (tv and tv.palette) or tags_match(p.tags, tv.palette)]
            out.append(fill(t, rng.choice(allowed or list(palette.values)).roles))
        return out

    def request_more(self, spec: PickSpec, context: Dict[str, Any], priority: str) -> None:
        if spec.zones and not spec.zone:
            for p in self.zone_specs(spec):
                self.request_more(p, context, priority)
            return
        if not self._grows(spec):
            return  # a user list is never expanded
        key, skey, signature = self._where(spec, context)
        self.requests.append((key, priority))
        if not self.generate or (self.store is not None and self.store.rounds(skey) >= MAX_ROUNDS):
            return
        have = self._pools.get(key)
        existing = have.items if have is not None else self.store.options(skey) if self.store is not None else []
        self._submit(spec, context, skey, signature, priority, existing)

    def _submit(self, spec: PickSpec, context: Dict[str, Any], skey: str, signature: str, priority: str,
                existing: Sequence[str], avoid: Sequence[str] = ()) -> None:
        if self.filler is None or self.store is None:
            return
        round_ = self.store.rounds(skey)
        leaf = self._leaf(spec)
        if leaf is not None:  # the list is deduplicated at read: the generator is shown what it wrote
            existing = self.store.options(skey)
        job = OptionJob(skey, spec, dict(context), self.program, signature, round_,
                        list(existing), list(avoid), self.project_id,
                        removed=[str(x) for x in (self.edits.get(spec.id) or {}).get("remove") or []],
                        examples=self._examples(leaf, spec, f"{skey}:{round_}") if leaf is not None else [])
        if self.filler.submit(job, priority):
            self.queued.append(skey)


def _weight(i: int, written: int) -> float:
    """Rank order: the writer's options decay like its lists always have; generated
    options continue from there more gently, so a grown pool keeps its support."""
    if i < written:
        return RANK_DECAY ** i
    base = RANK_DECAY ** max(0, written - 1) if written else 1.0
    return base * GEN_DECAY ** (i - written + 1)


# --------------------------------------------------------------------------- per profile

_stores: Dict[str, OptionStore] = {}
_fillers: Dict[str, OptionFiller] = {}


def store_for(profile_id: Optional[str]) -> OptionStore:
    import app_dirs
    from core.profile_context import get_current_profile
    pid = profile_id or get_current_profile()
    root = app_dirs.get_profile_dir(pid) / "prompt_programs" / "options"
    s = _stores.get(str(root))
    if s is None:
        s = _stores[str(root)] = OptionStore(root)
    return s


def filler_for(profile_id: Optional[str]) -> OptionFiller:
    store = store_for(profile_id)
    f = _fillers.get(str(store.root))
    if f is None:
        from prompt_programs.slots import preparing
        f = _fillers[str(store.root)] = OptionFiller(store, paused=preparing)
    try:
        f.attach()
    except RuntimeError:
        pass  # no running loop here: jobs wait until an async caller attaches one
    return f


__all__ = [
    "GeneratedOptions", "OptionFiller", "OptionJob", "OptionStore", "ProgramContext", "filler_for", "gen_key",
    "generated_pick", "generation_messages", "llm_generator", "parse_options", "program_minors", "read_options",
    "store_for", "write_options",
]
