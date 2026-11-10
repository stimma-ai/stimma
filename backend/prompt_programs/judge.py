"""Fluent settings: config.yaml's `fluent:` section, read the way the draw code uses it.

    generate_options: true             STIMMA_FLUENT_GENERATE    (background option generation)
    fix_model: default                 STIMMA_FLUENT_FIX_MODEL   (the small ONNX judge that checks each finished
                                                                  draw and rerolls flagged picks: "default" is the
                                                                  pinned pick judge, downloaded from launch
                                                                  (prompt_programs.pick_judge); "" or "off": off;
                                                                  anything else: a local model directory)
    fix_cut: 0 (the model's own)       STIMMA_FLUENT_FIX_CUT     (P(wrong) above this rerolls a pick)
    fix_rounds: 4                      STIMMA_FLUENT_FIX_ROUNDS  (rerolls per draw at most)
    fix_threads: 0 (up to 8)           STIMMA_FLUENT_FIX_THREADS

The judge itself is prompt_programs.fix. The environment overrides are for test rigs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class FluentSettings:
    generate_options: bool = True
    fix_model: str = "default"  # the fix judge (prompt_programs.fix.fix_mode): default | off | a model directory
    fix_cut: float = 0.0     # 0: the cut the model directory names
    fix_rounds: int = 4
    fix_threads: int = 0


_ENV = {"fix_model": "STIMMA_FLUENT_FIX_MODEL", "fix_cut": "STIMMA_FLUENT_FIX_CUT",
        "fix_rounds": "STIMMA_FLUENT_FIX_ROUNDS", "fix_threads": "STIMMA_FLUENT_FIX_THREADS"}


def settings() -> FluentSettings:
    """config.yaml's `fluent:` section, with the environment overrides above."""
    base: Dict[str, Any] = {}
    try:
        from config import get_settings
        cfg = getattr(get_settings(), "fluent", None)
        if cfg is not None:
            base = cfg.model_dump() if hasattr(cfg, "model_dump") else dict(cfg)
    except Exception:  # no config (scripts, tests): defaults
        base = {}
    fields = {f: base[f] for f in FluentSettings.__dataclass_fields__ if f in base}
    for f, var in _ENV.items():
        if os.environ.get(var):
            fields[f] = os.environ[var]
    if os.environ.get("STIMMA_FLUENT_GENERATE"):
        fields["generate_options"] = os.environ["STIMMA_FLUENT_GENERATE"].lower() not in ("0", "false", "no", "off")
    out = FluentSettings(**fields)
    return FluentSettings(bool(out.generate_options), str(out.fix_model or "").strip(), float(out.fix_cut or 0.0),
                          max(0, int(out.fix_rounds if out.fix_rounds is not None else 4)), int(out.fix_threads or 0))


__all__ = ["FluentSettings", "settings"]
