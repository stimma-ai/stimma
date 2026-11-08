"""Judges for draws: a decision model that tiers each candidate value in context.

A decision model reads a state (the prompt so far, later picks masked as [Label]) and
typed questions, and returns a probability per answer in one non-generative pass. Each
question asks how well one pick's candidate value fits, over four described levels
(wrong / unusual / plausible / typical); the draw loop turns those into keep rates.

Backends behind the draws.Judge protocol:

- `LocalJudge`: the model in this process, on CPU by default. Needs torch and
  transformers, which the app doesn't ship yet; without them it isn't available and
  draws use the null judge. Weights download on first use into the app cache dir
  (`<cache>/models/fluent-judge`), never into the repo.
- `HttpJudge`: the same questions sent to a judge server, for evaluations on a GPU box:
  `python -m prompt_programs.judge serve --model d3-edge --device cuda --port 8790`.
- `CachedJudge`: wraps either; a judgment is computed once per (state, question, value,
  judge version) and reused across draws (in memory, and on disk when given a path).

Configuration (config.yaml `fluent:`, or environment for evaluations):
    judge: none | local | http        STIMMA_FLUENT_JUDGE
    judge_model: d3-edge               STIMMA_FLUENT_JUDGE_MODEL
    judge_url: http://host:8790        STIMMA_FLUENT_JUDGE_URL
    judge_threads: 0 (torch default)   STIMMA_FLUENT_JUDGE_THREADS
    (weights cache dir)                STIMMA_FLUENT_JUDGE_CACHE
    rarity: 0.3                        STIMMA_FLUENT_RARITY      (keep rate of an unusual value, keep: tiers)
    wrong_cut: 0.5                     STIMMA_FLUENT_WRONG_CUT   (P(wrong) above this keeps nothing)
    keep: cut | tiers                  STIMMA_FLUENT_KEEP        (cut: only the wrong cut acts; the default
                                                                  until the lower tiers are calibrated)
    generate_options: true             STIMMA_FLUENT_GENERATE    (background option generation)
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger
from prompt_programs.draws import DEFAULT_RARITY, TIERS, WRONG_CUT, NullJudge, Question

log = get_logger(__name__)

QUESTION_VERSION = "q1"   # the wording below; part of every judge's version

# Score levels in ascending fit; index i of a score answer is SCORE_ORDER[i].
SCORE_ORDER = ("wrong", "unusual", "plausible", "typical")
LEVELS = {
    "wrong": "wrong: it contradicts something the prompt states (or an earlier filled-in detail), "
             "or it is not the kind of thing this spot names",
    "unusual": "unusual: rare or surprising, but real and possible; nothing the prompt states rules it out",
    "plausible": "plausible: a common, normal choice here, though not the most expected one",
    "typical": "typical: what you would expect here if the prompt didn't say",
}
RULE = "Rare is never wrong: only a contradiction with what the prompt states, or nonsense for this spot, is wrong."

# name -> (repo, pinned revision, family). Pinned so the remote code we run is the code
# that was read; a new revision is a deliberate change (and a new judge version).
# Sizes: edge 0.59B, lite 0.85B, nano 2B (CPU candidates); mini ~4B, flash ~9B (GPU only).
MODELS: Dict[str, Tuple[str, str, str]] = {
    "d3-edge": ("vllm-sr/d3-edge", "bee5e872f75b9c5d1405767bf244a6948b95c0af", "d3"),
    "d3-lite": ("vllm-sr/d3-lite", "6c01fba14e74f63b70e1ef442b0b6d1b934339d5", "d3"),
    "d3-nano": ("vllm-sr/d3-nano", "8198c9f763b046605b2f4827b4999971fa2c92c4", "d3"),
    "d3-mini": ("vllm-sr/d3-mini", "df99bf4ca4418bc6908ee68e9b7479af1f3b8800", "d3"),
    "d3-flash": ("vllm-sr/d3-flash", "67e03e1bc157961c582ee7c6a35d9b15fada3dec", "d3"),
}


def score_question(q: Question) -> Dict[str, Any]:
    """One candidate as a System One score question (the step-0 spike's wording)."""
    spot = f"[{q.label}]" + (f" ({q.about})" if q.about and q.about.strip().lower() != q.label.strip().lower() else "")
    return {"type": "score",
            "instructions": f'In this image prompt, the spot {spot} is filled with "{q.value}". '
                            f"How well does this value fit that spot, given everything the prompt states? {RULE}",
            "criteria": [LEVELS[t] for t in SCORE_ORDER]}


def tiers_from_levels(p: Sequence[float]) -> Dict[str, float]:
    s = float(sum(p)) or 1.0
    by = {t: float(x) / s for t, x in zip(SCORE_ORDER, p)}
    return {t: round(by[t], 5) for t in TIERS}


def tiers_from_answer(ans: Dict[str, Any]) -> Dict[str, float]:
    if "error" in ans:
        raise RuntimeError(f"judge answer error: {ans['error']}")
    probs = ans["probabilities"]
    return tiers_from_levels([float(probs[str(i)]) for i in range(len(probs))])


# --------------------------------------------------------------------------- backends

class JudgeUnavailable(RuntimeError):
    pass


class LocalJudge:
    """A System One decision model in this process (CPU by default)."""
    null = False

    def __init__(self, name: str = "d3-edge", device: str = "cpu", threads: int = 0, cache_dir: Optional[Path] = None):
        if name not in MODELS:
            raise JudgeUnavailable(f"unknown judge model {name!r}")
        try:
            import torch
            from transformers import AutoModel
        except ImportError as e:
            raise JudgeUnavailable(f"the judge needs torch and transformers ({e})") from None
        from huggingface_hub import snapshot_download
        repo, revision, family = MODELS[name]
        if threads:
            torch.set_num_threads(int(threads))
        cache = Path(cache_dir) if cache_dir else _model_cache_dir()
        started = time.monotonic()
        path = snapshot_download(repo, revision=revision, cache_dir=str(cache),
                                 ignore_patterns=["assets/*", "eval/*", "*.mp4"])
        self.revision = Path(path).name
        device = "cuda:0" if device == "cuda" else device  # the d3 loader wants an indexed device
        self.model = AutoModel.from_pretrained(path, trust_remote_code=True, device=device)
        if device == "cpu":
            # The runtime loads bf16; CPUs without bf16 matmul units are far faster in fp32.
            self.model.runtime.backbone.float()
            _fast_depthwise_conv()
        self.name, self.device, self.family = name, device, family
        self.version = f"{name}@{self.revision[:8]}/{QUESTION_VERSION}"
        self.load_seconds = round(time.monotonic() - started, 1)
        self._lock = threading.Lock()  # one pass at a time; torch uses the threads
        log.info(f"[fluent-judge] loaded {self.version} on {device} in {self.load_seconds}s")

    def judge(self, state: str, questions: Sequence[Question]) -> List[Dict[str, float]]:
        if not questions:
            return []
        qs = {f"q{i}": score_question(q) for i, q in enumerate(questions)}
        with self._lock:
            answers = self.model.system_one(state=state, questions=qs)["answers"]
        return [tiers_from_answer(answers[f"q{i}"]) for i in range(len(questions))]


def _fast_depthwise_conv() -> None:
    """CPU fix: Qwen3.5's linear-attention layers run a 4-tap depthwise causal conv through
    F.conv1d(groups=channels), which PyTorch's CPU backend runs as one tiny conv per
    channel (most of a small model's pass). The same math as k shifted multiply-adds is
    3-4x faster end to end (max |dP| about 1e-5)."""
    import torch.nn.functional as F
    from transformers.models.qwen3_5 import modeling_qwen3_5 as mq

    def causal_conv1d_fn(hidden_states, weight, bias=None, activation=None, **kwargs):
        k = weight.shape[-1]
        n = hidden_states.shape[-1]
        x = F.pad(hidden_states.to(weight.dtype), (k - 1, 0))
        out = x[:, :, 0:n] * weight[:, 0][None, :, None]
        for j in range(1, k):
            out = out + x[:, :, j:j + n] * weight[:, j][None, :, None]
        if bias is not None:
            out = out + bias[None, :, None]
        if activation is not None:
            out = mq.ACT2FN[activation](out)
        return out.to(hidden_states.dtype)

    mq.causal_conv1d_fn = causal_conv1d_fn


class AdapterJudge:
    """A judge from an evaluation adapter module: `module.load(name, device)` returning an
    object with `judge(state, [(label, about, value), ...], form=...) -> [tiers]`. Lets the
    judge server run the eval board's adapters (its question wording and model fixes)."""
    null = False

    def __init__(self, module: str, name: str, device: str = "cuda", form: str = "score"):
        import importlib
        self.obj = importlib.import_module(module).load(name, device=device)
        self.form = form
        rev = str(getattr(self.obj, "revision", "") or "")[:8]
        self.version = f"{name}@{rev}/adapter-{form}"

    def judge(self, state: str, questions: Sequence[Question]) -> List[Dict[str, float]]:
        if not questions:
            return []
        got = self.obj.judge(state, [(q.label, q.about, q.value) for q in questions], form=self.form)
        return [{t: float(p.get(t, 0.0)) for t in TIERS} for p in got]


class HttpJudge:
    """Questions sent to a judge server (`serve` below). The server reports its
    version, which becomes this judge's version."""
    null = False

    def __init__(self, url: str, timeout: float = 30.0):
        import httpx
        self.url = url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)
        try:
            info = self._client.get(f"{self.url}/info").json()
        except Exception as e:
            raise JudgeUnavailable(f"judge server at {self.url} isn't answering ({e})") from None
        self.version = str(info["version"])

    def judge(self, state: str, questions: Sequence[Question]) -> List[Dict[str, float]]:
        if not questions:
            return []
        body = {"state": state, "questions": [{"pick_id": q.pick_id, "label": q.label, "about": q.about, "value": q.value}
                                               for q in questions]}
        r = self._client.post(f"{self.url}/judge", json=body)
        r.raise_for_status()
        out = r.json()
        if out.get("version") != self.version:
            raise RuntimeError(f"judge server changed version ({self.version} -> {out.get('version')})")
        return [{t: float(p.get(t, 0.0)) for t in TIERS} for p in out["tiers"]]


# --------------------------------------------------------------------------- caching

class CachedJudge:
    """Judgments computed once per (state, question, value, judge version): repeat
    proposals, later draws of the same prompt and re-runs of an evaluation are free.
    Counts model passes and questions so evaluations can report judge cost."""

    def __init__(self, inner: Any, path: Optional[Path] = None, max_items: int = 100_000, batch: int = 32):
        self.inner = inner
        self.version = inner.version
        self.null = bool(getattr(inner, "null", False))
        self._mem: "OrderedDict[str, Dict[str, float]]" = OrderedDict()
        self._max = max_items
        self.batch = max(1, batch)   # questions per model pass (prefetching asks for many)
        self._lock = threading.Lock()
        self._db: Optional[sqlite3.Connection] = None
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("CREATE TABLE IF NOT EXISTS judgments (k TEXT PRIMARY KEY, tiers TEXT NOT NULL, at REAL)")
        self.passes = 0
        self.questions = 0
        self.hits = 0
        self.seconds = 0.0

    def _key(self, state: str, q: Question) -> str:
        blob = json.dumps([self.version, state, q.label, q.about, q.value], ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _get(self, k: str) -> Optional[Dict[str, float]]:
        with self._lock:
            v = self._mem.get(k)
            if v is not None:
                self._mem.move_to_end(k)
                return v
            if self._db is not None:
                row = self._db.execute("SELECT tiers FROM judgments WHERE k = ?", (k,)).fetchone()
                if row:
                    v = json.loads(row[0])
                    self._put_mem(k, v)
                    return v
        return None

    def _put_mem(self, k: str, v: Dict[str, float]) -> None:
        self._mem[k] = v
        if len(self._mem) > self._max:
            self._mem.popitem(last=False)

    def judge(self, state: str, questions: Sequence[Question]) -> List[Dict[str, float]]:
        keys = [self._key(state, q) for q in questions]
        out: List[Optional[Dict[str, float]]] = [self._get(k) for k in keys]
        todo = [i for i, v in enumerate(out) if v is None]
        self.hits += len(questions) - len(todo)
        for at in range(0, len(todo), self.batch):
            part = todo[at: at + self.batch]
            started = time.monotonic()
            got = self.inner.judge(state, [questions[i] for i in part])
            self.seconds += time.monotonic() - started
            self.passes += 1
            self.questions += len(part)
            with self._lock:
                for i, v in zip(part, got):
                    v = dict(v)
                    out[i] = v
                    self._put_mem(keys[i], v)
                    if self._db is not None:
                        self._db.execute("INSERT OR IGNORE INTO judgments VALUES (?, ?, ?)", (keys[i], json.dumps(v), time.time()))
        return [dict(v) for v in out]  # type: ignore[arg-type]

    def stats(self) -> Dict[str, Any]:
        return {"version": self.version, "passes": self.passes, "questions": self.questions, "hits": self.hits,
                "seconds": round(self.seconds, 3),
                "ms_per_pass": round(1000 * self.seconds / self.passes, 1) if self.passes else None}


# --------------------------------------------------------------------------- configuration

@dataclass(frozen=True)
class FluentSettings:
    judge: str = "none"
    judge_model: str = "d3-edge"
    judge_url: str = ""
    judge_threads: int = 0
    rarity: float = DEFAULT_RARITY
    wrong_cut: float = WRONG_CUT
    generate_options: bool = True
    keep: str = "cut"


def settings() -> FluentSettings:
    """config.yaml's `fluent:` section, with environment overrides for evaluations."""
    base: Dict[str, Any] = {}
    try:
        from config import get_settings
        cfg = getattr(get_settings(), "fluent", None)
        if cfg is not None:
            base = cfg.model_dump() if hasattr(cfg, "model_dump") else dict(cfg)
    except Exception:  # no config (scripts, tests): defaults
        base = {}
    fields = {f: base[f] for f in FluentSettings.__dataclass_fields__ if f in base}
    env = {"judge": "STIMMA_FLUENT_JUDGE", "judge_model": "STIMMA_FLUENT_JUDGE_MODEL", "judge_url": "STIMMA_FLUENT_JUDGE_URL",
           "judge_threads": "STIMMA_FLUENT_JUDGE_THREADS", "rarity": "STIMMA_FLUENT_RARITY", "wrong_cut": "STIMMA_FLUENT_WRONG_CUT",
           "keep": "STIMMA_FLUENT_KEEP"}
    for f, var in env.items():
        if os.environ.get(var):
            fields[f] = os.environ[var]
    if os.environ.get("STIMMA_FLUENT_GENERATE"):
        fields["generate_options"] = os.environ["STIMMA_FLUENT_GENERATE"].lower() not in ("0", "false", "no", "off")
    out = FluentSettings(**fields)
    keep = str(out.keep or "cut").lower()
    return FluentSettings(str(out.judge or "none").lower(), str(out.judge_model), str(out.judge_url or ""),
                          int(out.judge_threads or 0), float(out.rarity), float(out.wrong_cut), bool(out.generate_options),
                          keep if keep in ("cut", "tiers") else "cut")


def _model_cache_dir() -> Path:
    """Where judge weights download: the app cache dir, or STIMMA_FLUENT_JUDGE_CACHE
    (an evaluation box can point it at a Hugging Face cache it already has)."""
    if os.environ.get("STIMMA_FLUENT_JUDGE_CACHE"):
        return Path(os.environ["STIMMA_FLUENT_JUDGE_CACHE"])
    import app_dirs
    return app_dirs.get_cache_dir() / "models" / "fluent-judge"


def _judgment_db() -> Optional[Path]:
    try:
        import app_dirs
        return app_dirs.get_cache_dir() / "fluent-judgments.sqlite"
    except Exception:
        return None


_judges: Dict[Tuple[str, str, str, int], Any] = {}
_loading: Dict[Tuple[str, str, str, int], threading.Thread] = {}
_failed: Dict[Tuple[str, str, str, int], str] = {}
_lock = threading.Lock()


def build_judge(s: FluentSettings) -> Any:
    """The judge for these settings, built now (blocking). NullJudge for `none`."""
    if s.judge in ("", "none", "null", "off"):
        return NullJudge()
    if s.judge == "http":
        if not s.judge_url:
            raise JudgeUnavailable("judge: http needs judge_url")
        inner: Any = HttpJudge(s.judge_url)
    elif s.judge == "local":
        inner = LocalJudge(s.judge_model, "cpu", s.judge_threads)
    else:
        raise JudgeUnavailable(f"unknown judge backend {s.judge!r}")
    return CachedJudge(inner, _judgment_db())


def configured_judge(s: Optional[FluentSettings] = None, wait: bool = False) -> Any:
    """The configured judge if it's ready, else the null judge. A local model loads in
    the background on first use (draws use the null judge meanwhile, and their
    revision says so); a judge that can't load stays null and is logged once."""
    s = s or settings()
    if s.judge in ("", "none", "null", "off"):
        return NullJudge()
    k = (s.judge, s.judge_model, s.judge_url, s.judge_threads)
    with _lock:
        if k in _judges:
            return _judges[k]
        if k in _failed:
            return NullJudge()
        t = _loading.get(k)
        if t is None:
            def load():
                try:
                    j = build_judge(s)
                    with _lock:
                        _judges[k] = j
                except Exception as e:
                    with _lock:
                        _failed[k] = str(e)
                    log.warning(f"[fluent-judge] {s.judge} judge unavailable, drawing with the null judge: {e}")
                finally:
                    with _lock:
                        _loading.pop(k, None)
            t = threading.Thread(target=load, name="fluent-judge-load", daemon=True)
            _loading[k] = t
            t.start()
    if wait:
        t.join()
        with _lock:
            return _judges.get(k) or NullJudge()
    return NullJudge()


# --------------------------------------------------------------------------- judge server

def make_server(judge: Any, host: str, port: int, device: str = ""):
    """A minimal HTTP judge server around any judge (`GET /info`, `POST /judge`)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: Dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/info":
                self._send(200, {"version": judge.version, "device": device})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/judge":
                return self._send(404, {"error": "not found"})
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            qs = [Question(str(q.get("pick_id", "")), str(q.get("label", "")), str(q.get("about", "")), str(q["value"]))
                  for q in body.get("questions") or []]
            started = time.monotonic()
            with lock:
                tiers = judge.judge(str(body.get("state", "")), qs)
            self._send(200, {"version": judge.version, "tiers": tiers, "ms": round(1000 * (time.monotonic() - started), 1)})

        def log_message(self, *a):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def serve(model: str, device: str, host: str, port: int, threads: int = 0, adapter: str = "",
          form: str = "score") -> None:  # pragma: no cover - manual tool
    """Run an HTTP judge server, for evaluations on a GPU box: LocalJudge, or an
    evaluation adapter module (`--adapter fluent_draws.judge.adapters`)."""
    judge: Any = AdapterJudge(adapter, model, device, form) if adapter else LocalJudge(model, device, threads)
    print(f"judge server: {judge.version} on {device}, port {port}", file=sys.stderr)
    make_server(judge, host, port, device).serve_forever()


def _main(argv: Optional[Sequence[str]] = None) -> None:  # pragma: no cover - manual tool
    import argparse
    ap = argparse.ArgumentParser(prog="python -m prompt_programs.judge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("serve", help="run an HTTP judge server")
    sv.add_argument("--model", default="d3-edge")
    sv.add_argument("--device", default="cuda")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8790)
    sv.add_argument("--threads", type=int, default=0)
    sv.add_argument("--adapter", default="", help="an adapter module with load(name, device), e.g. fluent_draws.judge.adapters")
    sv.add_argument("--form", default="score", help="the adapter's question form")
    bench = sub.add_parser("bench", help="time judge passes in this process")
    bench.add_argument("--model", default="d3-edge")
    bench.add_argument("--device", default="cpu")
    bench.add_argument("--threads", type=int, default=0)
    bench.add_argument("--n", type=int, nargs="+", default=[1, 8, 16])
    bench.add_argument("--reps", type=int, default=5)
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        serve(a.model, a.device, a.host, a.port, a.threads, a.adapter, a.form)
        return
    j = LocalJudge(a.model, a.device, a.threads)
    state = ("A cinematic portrait of a [Role] in the 1920s, a woman of about 30 with [Hair], wearing [Outfit], "
             "standing in a smoky speakeasy under [Light], shot on a medium-format film camera.")
    vals = [("Role", "her job", "jazz singer"), ("Hair", "her hairstyle", "short finger waves"),
            ("Outfit", "what she wears", "a beaded flapper dress"), ("Light", "the lighting", "a warm spotlight")]
    for n in a.n:
        qs = [Question(p, p, ab, v) for p, ab, v in (vals * (n // len(vals) + 1))[:n]]
        j.judge(state, qs)  # warm
        times = []
        for _ in range(a.reps):
            t = time.monotonic()
            j.judge(state, qs)
            times.append(1000 * (time.monotonic() - t))
        times.sort()
        print(json.dumps({"model": j.version, "device": a.device, "threads": a.threads, "n": n,
                          "p50_ms": round(times[len(times) // 2], 1), "max_ms": round(times[-1], 1)}))


if __name__ == "__main__":  # pragma: no cover
    _main()


__all__ = [
    "AdapterJudge", "CachedJudge", "FluentSettings", "HttpJudge", "JudgeUnavailable", "LocalJudge", "MODELS", "QUESTION_VERSION",
    "build_judge", "configured_judge", "make_server", "score_question", "settings", "tiers_from_answer",
]
