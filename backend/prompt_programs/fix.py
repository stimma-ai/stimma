"""Optimistic-then-fix draws: a small local judge checks each finished draw.

A draw is made as usual. Then every varying pick is scored in full context: the
finished prompt with only that pick masked as [Label], plus the user's own prompt,
asked as one batch. The worst pick whose P(wrong) is above the cut is rerolled: the
draw runs again on a new seed with every other value kept (`fixed`) and the rejected
values removed (`edits`). A pick whose pool depends on the rerolled one is redrawn by
the engine when its kept value isn't in its new pool, and phases keep their order
because the whole program runs again. Up to `rounds` rerolls; when a draw is still
flagged after that, the best draw seen ships (fewest flagged picks, then the lowest
worst score) and the run record says it is unresolved.

The judge (`OnnxJudge`) is a classifier exported to ONNX (int8 is the expected build)
with a fast tokenizer, run on CPU with onnxruntime. A model directory holds:

    model.int8.onnx       (or model_quantized.onnx / model.onnx, or judge.json "model")
    tokenizer.json        a Hugging Face fast tokenizer (tokenizer_config.json names its pad token)
    io.json               optional, written by the exporter: {"kind": "enc"|"dec", "maxlen": N, "cut": x, "output": ...}
    judge.json            optional overrides of everything below

An encoder ("enc") reads (first, second) as a tokenizer pair, truncating only the first;
a decoder classifier ("dec") reads one string, first + "\n\nDetail: " + second. An
output named like "probs" is already a distribution; anything else is softmaxed. The
answer is P(wrong); a pick is flagged at P(wrong) > cut.

judge.json keys (all optional):
    model         ONNX file name
    kind          enc | dec (io.json's, else enc)
    max_length    tokens per input (io.json's maxlen, else 512)
    output        probs | logits (by the output's name when unset)
    first         the first text's template, with the user's prompt  ("The user wrote: {user_prompt}\\n\\nPrompt: {state}")
    first_bare    the same without a user prompt ("{state}")
    second        the second text's template ("{head}: {value}"; head is "Label (about)", or
                  "Label" when about is empty or the same as the label)
    user_prompt   whether the model reads the user's prompt (true)
    labels        output classes in order (["fine", "odd", "wrong"]); a single logit is P(wrong)
    wrong         the class that means wrong ("wrong")
    cut           P(wrong) above this rerolls a pick (io.json's, else 0.5); the fix_cut setting overrides it
    pad_id        padding token id (else the tokenizer's [PAD] / <pad>, else 0)
    name          a short name for the run record (the directory name)
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Sequence, Tuple

from core.logging import get_logger

log = get_logger(__name__)

MODEL_FILES = ("model.int8.onnx", "model_quantized.onnx", "model_int8.onnx", "model.onnx")
DECODER_JOIN = "\n\nDetail: "
DEFAULTS: Dict[str, Any] = {
    "kind": "enc",
    "max_length": 512,
    "first": "The user wrote: {user_prompt}\n\nPrompt: {state}",
    "first_bare": "{state}",
    "second": "{head}: {value}",
    "user_prompt": True,
    "labels": ["fine", "odd", "wrong"],
    "wrong": "wrong",
    "cut": 0.5,
}
REROLL_STRIDE = 10007   # reroll r draws on seed + stride * r
DEFAULT_ROUNDS = 4
MAX_BATCH = 64          # pairs per model call; a bigger pass runs as several


class FixJudgeUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Item:
    """One pick to score: the finished prompt with this pick masked, and the pick."""
    state: str
    label: str
    about: str
    value: str
    user_prompt: str = ""


def head(label: str, about: str) -> str:
    about = (about or "").strip()
    return label + (f" ({about})" if about and about.lower() != label.lower() else "")


def locate(prompt: str, value: str, first: bool = False) -> Optional[int]:
    """Where a pick's value stands in the finished prompt: its one occurrence, else its one
    whole-word occurrence (short values like "10"), else (`first`) the first whole-word
    one. None when it isn't found that way. The judge masks this span, and the
    generation details highlight it."""
    hits = [m.start() for m in re.finditer(re.escape(value), prompt, re.I)]
    if len(hits) != 1:
        hits = [m.start() for m in re.finditer(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", prompt, re.I)]
        if not hits or (len(hits) > 1 and not first):
            return None
    return hits[0]


def mask(prompt: str, value: str, label: str, first: bool = False) -> Optional[str]:
    """The finished prompt with this pick's value shown as [label], every other pick
    filled. None when the value's text isn't found exactly once. `first`: a user-list
    value that generated text repeats masks its first occurrence, where the user's
    template put it."""
    i = locate(prompt, value, first)
    if i is None:
        return None
    return prompt[:i] + f"[{label}]" + prompt[i + len(value):]


def shown_picks(result: Any) -> List[Any]:
    """The picks a reader sees in the prompt: visible, drawn, with text."""
    return [d for d in result.draws
            if d.kind == "pick" and not d.hidden and d.value is not None and str(d.value).strip()]


def prompt_view(result: Any) -> Dict[str, Any]:
    """A draw as the generation details show it: the prompt the image model read, where
    each visible pick's value stands in it ([start, end, id], in order, never
    overlapping), and each visible pick's value."""
    from prompt_programs.prepare import realized_text
    text = realized_text(result.prompt)
    found: List[Tuple[int, int, str]] = []
    picks = shown_picks(result)
    # longer values first, so one that contains another keeps its whole span
    for d in sorted(picks, key=lambda d: -len(str(d.value))):
        v = str(d.value)
        i = locate(text, v, first=d.source == "list")
        if i is None or any(i < e and s < i + len(v) for s, e, _ in found):
            continue
        found.append((i, i + len(v), d.id))
    return {"text": text, "spans": [list(x) for x in sorted(found)],
            "values": {d.id: str(d.value) for d in picks}}


# --------------------------------------------------------------------------- the ONNX judge

def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        v = json.loads(path.read_text())
    except ValueError as e:
        raise FixJudgeUnavailable(f"{path.name} isn't valid JSON ({e})") from None
    return v if isinstance(v, dict) else {}


def _file_digest(path: Path) -> str:
    """A cheap fingerprint of a large file: its size and its first and last 4 MB."""
    h = hashlib.sha256()
    size = path.stat().st_size
    h.update(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(4 << 20))
        if size > 8 << 20:
            f.seek(-(4 << 20), os.SEEK_END)
            h.update(f.read())
    return h.hexdigest()[:12]


def default_threads() -> int:
    """onnxruntime threads for the judge when fix_threads is unset: up to 8 (past that,
    more threads cost one batch of a draw's picks more than they gave)."""
    return max(1, min(8, os.cpu_count() or 1))


@dataclass
class _Ask:
    todo: List[Tuple[str, str]]
    got: Dict[Tuple[str, str], float] = field(default_factory=dict)
    error: Optional[BaseException] = None
    done: bool = False
    lead: bool = False


class OnnxJudge:
    """P(wrong) for (masked prompt, pick) pairs from a cross-encoder in ONNX, on CPU."""

    def __init__(self, model_dir: str | os.PathLike, threads: int = 0, cache_items: int = 20_000):
        d = Path(os.path.expanduser(str(model_dir)))
        if not d.is_dir():
            raise FixJudgeUnavailable(f"no judge model directory at {d}")
        cfg = dict(DEFAULTS)
        io = _read_json(d / "io.json")
        if io.get("kind") in ("enc", "dec"):
            cfg["kind"] = io["kind"]
        if io.get("maxlen"):
            cfg["max_length"] = int(io["maxlen"])
        if isinstance(io.get("cut"), (int, float)) and not isinstance(io.get("cut"), bool):
            cfg["cut"] = float(io["cut"])
        if isinstance(io.get("output"), str):
            cfg["output"] = "probs" if io["output"].strip().lower().startswith("prob") else "logits"
        cfg.update(_read_json(d / "judge.json"))
        model = d / cfg["model"] if cfg.get("model") else next((d / f for f in MODEL_FILES if (d / f).exists()), None)
        if model is None or not model.exists():
            raise FixJudgeUnavailable(f"no ONNX model in {d} (looked for {', '.join(MODEL_FILES)})")
        if not (d / "tokenizer.json").exists():
            raise FixJudgeUnavailable(f"no tokenizer.json in {d}")
        try:
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as e:
            raise FixJudgeUnavailable(f"the judge needs onnxruntime and tokenizers ({e})") from None
        started = time.monotonic()
        self.np = np
        self.tok = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.tok.no_padding()
        self.kind = "dec" if cfg.get("kind") == "dec" else "enc"
        self.max_length = int(cfg["max_length"])
        self.tok.enable_truncation(self.max_length, strategy="only_first" if self.kind == "enc" else "longest_first")
        pad = cfg.get("pad_id")
        if pad is None:
            tc = _read_json(d / "tokenizer_config.json").get("pad_token")
            tc = tc.get("content") if isinstance(tc, dict) else tc
            pad = next((self.tok.token_to_id(t) for t in (tc, "[PAD]", "<pad>") if t and self.tok.token_to_id(t) is not None), 0)
        self.pad_id = int(pad)
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(threads) if threads else default_threads()
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(model), so, providers=["CPUExecutionProvider"])
        self.inputs = {i.name: (np.int32 if "int32" in i.type else np.int64) for i in self.session.get_inputs()}
        if "input_ids" not in self.inputs:
            raise FixJudgeUnavailable(f"{model.name} has no input_ids input")
        out_name = self.session.get_outputs()[0].name.lower()
        self.probs_out = (cfg["output"] == "probs") if cfg.get("output") in ("probs", "logits") else "prob" in out_name
        labels = [str(x) for x in cfg["labels"]]
        self.wrong_index = labels.index(str(cfg["wrong"])) if str(cfg["wrong"]) in labels else len(labels) - 1
        self.cfg = cfg
        self.cut = float(cfg["cut"])
        self.reads_user_prompt = bool(cfg["user_prompt"])
        name = str(cfg.get("name") or d.name)
        self.version = f"onnx:{name}@{_file_digest(model)}"
        self.load_seconds = round(time.monotonic() - started, 2)
        self._cache: "OrderedDict[Tuple[str, str], float]" = OrderedDict()
        self._cache_items = cache_items
        self._lock = threading.Lock()       # the cache
        # Passes asked for while one runs wait for it, then run together as the next one:
        # one pass uses every thread, and a batch costs far less than its parts run apart.
        self._turn = threading.Condition()
        self._waiting: List["_Ask"] = []
        self._busy = False
        self.passes = 0
        self.questions = 0
        self.hits = 0
        self.seconds = 0.0
        log.info(f"[fluent-fix] loaded {self.version} in {self.load_seconds}s")

    def texts(self, it: Item) -> Tuple[str, str]:
        """The input pair for one item, per the model directory's templates."""
        if self.reads_user_prompt and it.user_prompt:
            first = self.cfg["first"].format(user_prompt=it.user_prompt, state=it.state)
        else:
            first = self.cfg["first_bare"].format(user_prompt=it.user_prompt, state=it.state)
        second = self.cfg["second"].format(head=head(it.label, it.about), label=it.label, about=it.about or "",
                                           value=it.value)
        return first, second

    def _encode(self, pairs: Sequence[Tuple[str, str]]) -> List[Any]:
        if self.kind == "dec":
            return self.tok.encode_batch([a + DECODER_JOIN + b for a, b in pairs])
        try:
            return self.tok.encode_batch(list(pairs))
        except Exception:  # a second text too long for only_first: truncate both, one by one
            out = []
            for a, b in pairs:
                try:
                    out.append(self.tok.encode(a, b))
                except Exception:
                    self.tok.enable_truncation(self.max_length, strategy="longest_first")
                    try:
                        out.append(self.tok.encode(a, b))
                    finally:
                        self.tok.enable_truncation(self.max_length, strategy="only_first")
            return out

    def _run(self, pairs: Sequence[Tuple[str, str]]) -> List[float]:
        if self.kind == "dec" and len(pairs) > 1:  # last-token pooling: never pad a decoder
            return [p for pr in pairs for p in self._run([pr])]
        np = self.np
        enc = self._encode(pairs)
        n = max(len(e.ids) for e in enc)
        ids = np.full((len(enc), n), self.pad_id, dtype=np.int64)
        att = np.zeros((len(enc), n), dtype=np.int64)
        typ = np.zeros((len(enc), n), dtype=np.int64)
        for i, e in enumerate(enc):
            ids[i, : len(e.ids)] = e.ids
            att[i, : len(e.ids)] = 1
            typ[i, : len(e.ids)] = e.type_ids
        feed = {}
        for name, dt in self.inputs.items():
            src = ids if name == "input_ids" else att if name == "attention_mask" else typ if name == "token_type_ids" else None
            if src is None:
                raise FixJudgeUnavailable(f"the judge model wants an input this backend doesn't know: {name}")
            feed[name] = src.astype(dt)
        logits = np.asarray(self.session.run(None, feed)[0], dtype=np.float64)
        if logits.ndim == 1:
            logits = logits[:, None]
        if logits.shape[1] == 1:
            if self.probs_out:
                return [float(x) for x in logits[:, 0]]
            return [float(1.0 / (1.0 + math.exp(-x))) for x in logits[:, 0]]
        if self.probs_out:
            return [float(x) for x in logits[:, self.wrong_index]]
        z = logits - logits.max(axis=1, keepdims=True)
        p = np.exp(z)
        p /= p.sum(axis=1, keepdims=True)
        return [float(x) for x in p[:, self.wrong_index]]

    def p_wrong(self, items: Sequence[Item]) -> List[float]:
        """P(wrong) per item. Everything not cached is asked in one model pass, shared
        with any other thread's items asked meanwhile."""
        pairs = [self.texts(it) for it in items]
        out: List[Optional[float]] = []
        with self._lock:
            for k in pairs:
                v = self._cache.get(k)
                if v is not None:
                    self._cache.move_to_end(k)
                out.append(v)
        todo = list(dict.fromkeys(k for k, v in zip(pairs, out) if v is None))
        self.hits += len(pairs) - sum(1 for v in out if v is None)
        if todo:
            got = self._ask(todo)
            out = [got[k] if v is None else v for k, v in zip(pairs, out)]
        return [float(v) for v in out]  # type: ignore[arg-type]

    def _ask(self, todo: List[Tuple[str, str]]) -> Dict[Tuple[str, str], float]:
        """Score pairs in the next pass. A caller arriving while a pass runs waits; when it
        ends, the first waiting caller runs one pass for everyone who waited."""
        ask = _Ask(todo)
        with self._turn:
            self._waiting.append(ask)
            while self._busy and not ask.done and not ask.lead:
                self._turn.wait()
            if not ask.done:
                self._busy = True
                batch, self._waiting = self._waiting, []
        if not ask.done:
            pairs = list(dict.fromkeys(k for a in batch for k in a.todo))
            started = time.monotonic()
            got: Dict[Tuple[str, str], float] = {}
            error: Optional[BaseException] = None
            try:
                for i in range(0, len(pairs), MAX_BATCH):
                    chunk = pairs[i:i + MAX_BATCH]
                    got.update(zip(chunk, self._run(chunk)))
            except BaseException as e:  # every caller in the pass hears it
                error = e
            self.seconds += time.monotonic() - started
            self.passes += 1
            self.questions += len(pairs)
            if error is None:
                with self._lock:
                    for k, v in got.items():
                        self._cache[k] = v
                        while len(self._cache) > self._cache_items:
                            self._cache.popitem(last=False)
            with self._turn:
                for a in batch:
                    a.got, a.error, a.done = got, error, True
                if self._waiting:
                    self._waiting[0].lead = True
                else:
                    self._busy = False
                self._turn.notify_all()
        if ask.error is not None:
            raise ask.error
        return ask.got

    def stats(self) -> Dict[str, Any]:
        return {"version": self.version, "passes": self.passes, "questions": self.questions, "hits": self.hits,
                "ms_per_pass": round(1000 * self.seconds / self.passes, 1) if self.passes else None}


_judges: Dict[Tuple[str, int, float], Any] = {}
_failed: Dict[Tuple[str, int, float], str] = {}
_load_lock = threading.Lock()


def fix_judge(model_dir: str, threads: int = 0) -> OnnxJudge:
    """The judge for a model directory, loaded once (blocking: call from a worker
    thread). A directory that fails to load fails fast until it changes on disk."""
    p = Path(os.path.expanduser(model_dir))
    try:
        stamp = max([p.stat().st_mtime] + [f.stat().st_mtime for f in p.iterdir()]) if p.is_dir() else 0.0
    except OSError:
        stamp = 0.0
    k = (str(p), int(threads), stamp)
    with _load_lock:
        if k in _judges:
            return _judges[k]
        if k in _failed:
            raise FixJudgeUnavailable(_failed[k])
        try:
            j = OnnxJudge(p, threads)
        except Exception as e:
            _failed[k] = str(e) if isinstance(e, FixJudgeUnavailable) else f"the judge model didn't load ({e})"
            log.warning(f"[fluent-fix] {_failed[k]}")
            raise FixJudgeUnavailable(_failed[k]) from None
        for old in [x for x in _judges if x[0] == k[0]]:
            _judges.pop(old, None)
        _judges[k] = j
        return j


# --------------------------------------------------------------------------- the fix loop

def judged_picks(result: Any, skip: Sequence[str] = (), rerolled: Sequence[str] = ()) -> List[Any]:
    """The picks a fix pass scores: visible picks that had a choice (or were rerolled
    down to one), not pinned, not kept by the user, with an id that appears once."""
    counts: Dict[str, int] = {}
    for d in result.draws:
        counts[d.id] = counts.get(d.id, 0) + 1
    skip_set, rerolled_set = set(skip), set(rerolled)
    return [d for d in result.draws
            if d.kind == "pick" and not d.hidden and not d.pinned and d.value is not None and str(d.value).strip()
            and (len(d.options) >= 2 or d.id in rerolled_set) and d.id not in skip_set and counts[d.id] == 1]


def _questions(result: Any, user_prompt: str, skip: Sequence[str] = (),
               rerolled: Sequence[str] = ()) -> Tuple[List[Item], List[str], Dict[str, Optional[float]]]:
    """What scoring a finished draw asks the judge: one item per judged pick that can be
    masked, their ids, and None for the ones that can't."""
    from prompt_programs.prepare import realized_text
    text = realized_text(result.prompt)
    items: List[Item] = []
    ids: List[str] = []
    out: Dict[str, Optional[float]] = {}
    for d in judged_picks(result, skip, rerolled):
        st = mask(text, str(d.value), d.label, first=d.source == "list")
        if st is None:
            out[d.id] = None
            continue
        items.append(Item(st, d.label, d.about or "", str(d.value), user_prompt))
        ids.append(d.id)
    return items, ids, out


def score_draw(judge: Any, result: Any, user_prompt: str, skip: Sequence[str] = (),
               rerolled: Sequence[str] = ()) -> Dict[str, Optional[float]]:
    """P(wrong) per judged pick of a finished draw (None when it can't be masked)."""
    items, ids, out = _questions(result, user_prompt, skip, rerolled)
    for cid, p in zip(ids, judge.p_wrong(items) if items else []):
        out[cid] = p
    return out


def _merge_edits(user: Dict[str, Any], removed: Dict[str, List[str]]) -> Dict[str, Any]:
    out = {k: dict(v) for k, v in user.items() if isinstance(v, dict)}
    for cid, vals in removed.items():
        e = out.setdefault(cid, {})
        e["remove"] = list(dict.fromkeys([*(e.get("remove") or []), *vals]))
    return out


Redraw = Callable[[int, Dict[str, Any], Dict[str, Any]], Any]
# One draw's fix loop, as steps: it yields the items it needs scored and is sent their
# scores, so several draws can share each judge pass. It returns (draw, record).
Fixer = Generator[List[Item], List[float], Tuple[Any, Dict[str, Any]]]


def _fixer(result: Any, *, judge: Any, redraw: Redraw, seed: int, user_prompt: str, cut: float,
           rounds: int = DEFAULT_ROUNDS, fixed: Optional[Dict[str, Any]] = None,
           edits: Optional[Dict[str, Any]] = None) -> Fixer:
    from prompt_programs.runtime import ProgramError
    started = time.monotonic()
    user_fixed = {str(k): v for k, v in (fixed or {}).items()}
    user_edits = {str(k): v for k, v in (edits or {}).items() if isinstance(v, dict)}
    skip = list(user_fixed)  # values the user asked to keep are never rerolled
    removed: Dict[str, List[str]] = {}
    history: List[Dict[str, Any]] = []
    cur = result
    best: Optional[Tuple[Tuple[int, float], int, Any]] = None
    stop = ""
    for rnd in range(rounds + 1):
        items, ids, scores = _questions(cur, user_prompt, skip, list(removed))
        got = (yield items) if items else []
        for cid, p in zip(ids, got):
            scores[cid] = p
        flagged = sorted(((p, cid) for cid, p in scores.items() if p is not None and p > cut), reverse=True)
        # Each roll's prompt and values: what the generation details show, row by row.
        step: Dict[str, Any] = {"scores": {cid: (None if p is None else round(p, 4)) for cid, p in scores.items()},
                                **prompt_view(cur)}
        history.append(step)
        key = (len(flagged), flagged[0][0] if flagged else 0.0)
        if best is None or key < best[0]:
            best = (key, rnd, cur)
        if not flagged or rnd == rounds:
            break
        target_id = flagged[0][1]
        target = next(d for d in cur.draws if d.id == target_id)
        removed.setdefault(target_id, []).append(str(target.value))
        keep = {**user_fixed, **{d.id: d.value for d in cur.draws if d.id != target_id and d.value is not None}}
        step["rerolled"] = {"id": target_id, "label": target.label, "value": str(target.value)}
        try:
            cur = redraw((seed + REROLL_STRIDE * (rnd + 1)) % (2**31), keep, _merge_edits(user_edits, removed))
        except ProgramError as e:  # nothing left to draw for that pick: keep the best so far
            step["rerolled"]["failed"] = True
            stop = str(e)[:200]
            break
    assert best is not None
    (n_flagged, _), chosen, out = best
    record: Dict[str, Any] = {
        "judge": getattr(judge, "version", type(judge).__name__),
        "cut": cut,
        "rerolls": sum(1 for h in history if "rerolled" in h and not h["rerolled"].get("failed")),
        "unresolved": n_flagged > 0,
        "chosen": chosen,
        "rounds": history,
        "ms": round(1000 * (time.monotonic() - started), 1),
    }
    if stop:
        record["stopped"] = stop
    return out, record


def _drive(judge: Any, fixers: Sequence[Fixer]) -> List[Any]:
    """Run fix loops in lockstep: each round, every loop still going asks its items in
    one shared judge pass. A loop's outcome is (draw, record), or the exception it (or
    its judge pass) raised. Each loop sees exactly the scores it would alone."""
    outcome: List[Any] = [None] * len(fixers)
    asks: Dict[int, List[Item]] = {}

    def advance(i: int, scores: Optional[List[float]]) -> None:
        try:
            asks[i] = fixers[i].send(scores)  # type: ignore[arg-type]
        except StopIteration as done:
            outcome[i] = done.value
            asks.pop(i, None)
        except Exception as e:
            outcome[i] = e
            asks.pop(i, None)

    for i in range(len(fixers)):
        advance(i, None)
    while asks:
        order = list(asks)
        flat = [it for i in order for it in asks[i]]
        try:
            ps = judge.p_wrong(flat)
        except Exception as e:
            for i in order:
                outcome[i] = e
                asks.pop(i, None)
            break
        at = 0
        for i in order:
            n = len(asks[i])
            got, at = ps[at:at + n], at + n
            advance(i, got)
    return outcome


def fix_draw(result: Any, *, judge: Any, redraw: Redraw, seed: int, user_prompt: str, cut: float,
             rounds: int = DEFAULT_ROUNDS, fixed: Optional[Dict[str, Any]] = None,
             edits: Optional[Dict[str, Any]] = None) -> Tuple[Any, Dict[str, Any]]:
    """Score a finished draw and reroll flagged picks. `redraw(seed, fixed, edits)` draws
    the program again. Returns the draw to ship and what the fix did, for the run record."""
    (out,) = _drive(judge, [_fixer(result, judge=judge, redraw=redraw, seed=seed, user_prompt=user_prompt, cut=cut,
                                   rounds=rounds, fixed=fixed, edits=edits)])
    if isinstance(out, Exception):
        raise out
    return out


def realize_and_fix(entry: Dict[str, Any], *, seed: int, pins: Optional[Dict[str, Any]] = None,
                    fixed: Optional[Dict[str, Any]] = None, edits: Optional[Dict[str, Any]] = None,
                    triggers: bool = True, profile_id: Optional[str] = None, project_id: Optional[int] = None,
                    revision: Optional[Dict[str, Any]] = None, cfg: Any = None,
                    judge: Any = None) -> Tuple[Any, Optional[Dict[str, Any]]]:
    """realize(), then the fix pass when a fix judge is set (fix_model) and the program
    has pick specs. An exact replay (`revision`) is never fixed. Returns the result and
    the fix record (None when no fix ran). Blocking: run it in a worker thread."""
    if revision:
        from prompt_programs.prepare import realize
        return realize(entry, seed=seed, pins=pins, fixed=fixed, edits=edits, triggers=triggers,
                       profile_id=profile_id, project_id=project_id, revision=revision), None
    out = realize_and_fix_many(entry, seeds=[seed], pins=pins, fixed=fixed, edits=edits, triggers=triggers,
                               profile_id=profile_id, project_id=project_id, cfg=cfg, judge=judge)[0]
    if isinstance(out, Exception):
        raise out
    return out


def realize_and_fix_many(entry: Dict[str, Any], *, seeds: Sequence[int], pins: Optional[Dict[str, Any]] = None,
                         fixed: Optional[Dict[str, Any]] = None, edits: Optional[Dict[str, Any]] = None,
                         triggers: bool = True, profile_id: Optional[str] = None, project_id: Optional[int] = None,
                         cfg: Any = None, judge: Any = None) -> List[Any]:
    """realize_and_fix() for several seeds of one program, their fix loops sharing each
    judge pass. Per seed: (result, fix record or None), exactly what realize_and_fix
    gives for that seed alone, or the exception its draw raised. Blocking."""
    from prompt_programs.draws import uses_draws
    from prompt_programs.judge import settings
    from prompt_programs.prepare import realize

    def draw_once(s: int, fx: Optional[Dict[str, Any]], ed: Optional[Dict[str, Any]]) -> Any:
        return realize(entry, seed=s, pins=pins, fixed=fx, edits=ed, triggers=triggers, profile_id=profile_id,
                       project_id=project_id)

    out: List[Any] = []
    for s in seeds:
        try:
            out.append(draw_once(s, fixed, edits))
        except Exception as e:
            out.append(e)
    drawn = [i for i, r in enumerate(out) if not isinstance(r, Exception)]
    if not uses_draws(entry.get("program") or ""):
        return [r if isinstance(r, Exception) else (r, None) for r in out]
    cfg = cfg or settings()
    if judge is None:
        if not cfg.fix_model:
            return [r if isinstance(r, Exception) else (r, None) for r in out]
        try:
            judge = fix_judge(cfg.fix_model, cfg.fix_threads)
        except FixJudgeUnavailable as e:
            return [r if isinstance(r, Exception) else (r, {"error": str(e)}) for r in out]
    cut = float(cfg.fix_cut) if cfg.fix_cut else float(getattr(judge, "cut", DEFAULTS["cut"]))
    user_prompt = str(entry.get("prompt") or "")
    fixers = [_fixer(out[i], judge=judge, redraw=draw_once, seed=seeds[i], user_prompt=user_prompt, cut=cut,
                     rounds=cfg.fix_rounds, fixed=fixed, edits=edits) for i in drawn]
    for i, res in zip(drawn, _drive(judge, fixers)):
        if isinstance(res, Exception):  # the judge failing must never cost the image: ship the draw as made
            log.warning(f"[fluent-fix] fix pass failed, keeping the draw as made: {res}")
            out[i] = (out[i], {"judge": getattr(judge, "version", ""), "error": f"the fix pass failed ({res})"})
        else:
            out[i] = res
    return out


__all__ = ["FixJudgeUnavailable", "Item", "OnnxJudge", "default_threads", "fix_draw", "fix_judge", "judged_picks",
           "locate", "mask", "prompt_view", "realize_and_fix", "realize_and_fix_many", "score_draw", "shown_picks"]
