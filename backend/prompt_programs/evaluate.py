"""Evaluation hook: draw a prepared program N times with a given judge and options.

For the eval board, which computes wrong rate, diversity, unresolved rate and latency
from what this returns. Nothing here is used by the app.

    from prompt_programs.evaluate import draw_many, fill_options
    await fill_options(entry, store)                     # generate pools now (cached on disk)
    out = draw_many(entry, 20, judge=judge, store=store)
    out["draws"][0]  -> {"seed", "prompt", "values", "unresolved", "judge_passes", "ms", ...}
    out["stats"]     -> {"draws", "aborted", "unresolved_draws", "ms_p50", "judge": {...}, ...}

CLI (one prepared entry as JSON, rows as JSONL):
    uv run python -m prompt_programs.evaluate --entry e.json --n 20 \\
        [--judge none|local|http://host:8790] [--options-dir DIR] [--fill] [--rarity 0.3]
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from prompt_programs.draws import DrawAborted, NullJudge
from prompt_programs.fluent import Runtime, runtime_for, start_options
from prompt_programs.judge import CachedJudge, FluentSettings, settings
from prompt_programs.options import Generator, OptionFiller, OptionStore, llm_generator
from prompt_programs.runtime import ProgramError


def _cfg(rarity: Optional[float], wrong_cut: Optional[float], generate: bool) -> FluentSettings:
    base = settings()
    return FluentSettings(base.judge, base.judge_model, base.judge_url, base.judge_threads,
                          base.rarity if rarity is None else float(rarity),
                          base.wrong_cut if wrong_cut is None else float(wrong_cut), generate)


def draw_many(entry: Dict[str, Any], n: int = 20, *, judge: Any = None, seeds: Optional[Sequence[int]] = None,
              pins: Optional[Dict[str, Any]] = None, edits: Optional[Dict[str, Any]] = None,
              rarity: Optional[float] = None, wrong_cut: Optional[float] = None,
              store: Optional[OptionStore] = None) -> Dict[str, Any]:
    """Draw `n` times (seeds 0..n-1 unless given) and return every draw plus totals.
    Pools are read from `store` as they are; nothing is generated while drawing."""
    from prompt_programs.prepare import realize
    judge = judge if judge is not None else NullJudge()
    cfg = _cfg(rarity, wrong_cut, generate=False)
    seeds = list(seeds) if seeds is not None else list(range(n))
    rows: List[Dict[str, Any]] = []
    times: List[float] = []
    for seed in seeds:
        rt = runtime_for(entry, edits=edits, judge=judge, store=store, cfg=cfg)
        rt = Runtime(rt.options, judge, cfg.rarity, cfg.wrong_cut)
        started = time.perf_counter()
        try:
            r = realize(entry, seed=seed, pins=pins, edits=edits, runtime=rt)
        except DrawAborted as e:
            rows.append({"seed": seed, "aborted": e.to_dict()})
            continue
        except ProgramError as e:
            rows.append({"seed": seed, "error": str(e)})
            continue
        ms = 1000 * (time.perf_counter() - started)
        times.append(ms)
        d = r.to_dict()
        rows.append({
            "seed": seed, "prompt": r.prompt, "ms": round(ms, 2),
            "values": {x["id"]: x["value"] for x in d["draws"] if x.get("kind") == "pick"},
            "draws": d["draws"], "unresolved": d.get("unresolved", []), "judge_passes": getattr(r, "judge_passes", 0),
            "proposals": getattr(r, "stats", {}).get("proposals", 0), "rejected": getattr(r, "stats", {}).get("rejected", 0),
            "revision": d.get("draw_revision"),
        })
    ok = [r for r in rows if "prompt" in r]
    times.sort()
    stats: Dict[str, Any] = {
        "draws": len(rows), "aborted": sum(1 for r in rows if "aborted" in r), "errors": sum(1 for r in rows if "error" in r),
        "unresolved_draws": sum(1 for r in ok if r["unresolved"]),
        "ms_p50": round(statistics.median(times), 2) if times else None,
        "ms_p99": round(times[min(len(times) - 1, int(0.99 * len(times)))], 2) if times else None,
        "judge_passes_per_draw": round(sum(r["judge_passes"] for r in ok) / len(ok), 2) if ok else None,
        "rejected_per_draw": round(sum(r["rejected"] for r in ok) / len(ok), 2) if ok else None,
        "rarity": cfg.rarity, "wrong_cut": cfg.wrong_cut,
        "judge": judge.stats() if isinstance(judge, CachedJudge) else {"version": getattr(judge, "version", "?")},
    }
    return {"draws": rows, "stats": stats}


async def fill_options(entry: Dict[str, Any], store: OptionStore, *, generator: Generator = llm_generator,
                       judge: Any = None, rounds: int = 1) -> Dict[str, Any]:
    """Generate this program's pools now (every call cached in `store`), running the
    bad-pool check when a judge is given. `rounds` > 1 asks each pool for more."""
    from prompt_programs.draws import draw
    filler = OptionFiller(store, generator)
    queued = start_options(entry, store=store, filler=filler, judge=judge or NullJudge(), cfg=_cfg(None, None, True))
    await filler.drain()
    for _ in range(max(0, rounds - 1)):
        rt = runtime_for(entry, store=store, filler=filler, judge=NullJudge(), cfg=_cfg(None, None, True))
        for seed in range(8):
            try:
                draw(entry["program"], seed, options=rt.options, judge=NullJudge())
            except ProgramError:
                pass
        for spec, context in rt.options.seen_specs():
            rt.options.request_more(spec, context, "low")
        await filler.drain()
    return {"queued": len(set(queued)), "calls": filler.calls, "failures": filler.failures, "checks": filler.checks}


def _main(argv: Optional[Sequence[str]] = None) -> None:  # pragma: no cover - manual tool
    import argparse
    import asyncio
    ap = argparse.ArgumentParser(prog="python -m prompt_programs.evaluate")
    ap.add_argument("--entry", required=True, help="a prepared program entry (JSON)")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--judge", default="none", help="none | local | http://host:port")
    ap.add_argument("--judge-model", default="d3-edge")
    ap.add_argument("--options-dir", default="", help="option cache dir (default: none, seeds only)")
    ap.add_argument("--judgments", default="", help="judgment cache (sqlite) to reuse across runs")
    ap.add_argument("--fill", action="store_true", help="generate pools first with the configured LLM")
    ap.add_argument("--rarity", type=float, default=None)
    ap.add_argument("--wrong-cut", type=float, default=None)
    ap.add_argument("--out", default="", help="write draws as JSONL here; stats go to stdout")
    a = ap.parse_args(argv)
    from prompt_programs.judge import HttpJudge, LocalJudge
    entry = json.loads(Path(a.entry).read_text("utf-8"))
    store = OptionStore(Path(a.options_dir)) if a.options_dir else None
    judge: Any = NullJudge()
    if a.judge.startswith("http"):
        judge = HttpJudge(a.judge)
    elif a.judge == "local":
        judge = LocalJudge(a.judge_model)
    if not getattr(judge, "null", False):
        judge = CachedJudge(judge, Path(a.judgments) if a.judgments else None)
    if a.fill and store is not None:
        print(json.dumps({"fill": asyncio.run(fill_options(entry, store, judge=judge))}), file=sys.stderr)
    out = draw_many(entry, a.n, judge=judge, rarity=a.rarity, wrong_cut=a.wrong_cut, store=store)
    if a.out:
        Path(a.out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out["draws"]), "utf-8")
    print(json.dumps(out["stats"], indent=1))


if __name__ == "__main__":  # pragma: no cover
    _main()


__all__ = ["draw_many", "fill_options"]
