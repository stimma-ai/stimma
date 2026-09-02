"""Precompile the Python modules imported by Stimma's backend startup.

The portable backend intentionally ships ordinary Python source so native
wheels and multiprocessing behave like a normal interpreter.  On Windows,
parsing hundreds of loose source files at every launch is especially costly
because real-time antivirus scanning sits in the import path.  Import the
application once at build time, discover the actual startup dependency graph,
and emit hash-based bytecode beside those sources.

Only files inside the portable payload are compiled.  This keeps the package
increase bounded to modules startup really imports instead of compiling every
optional dependency in site-packages.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import logging
import os
from pathlib import Path
import py_compile
import shutil
import sys
import tempfile


def _source_modules_under(payload_dir: Path) -> list[Path]:
    """Return imported Python sources owned by *payload_dir*."""
    sources: set[Path] = set()
    for module in tuple(sys.modules.values()):
        source_name = getattr(module, "__file__", None)
        if not source_name:
            continue
        source = Path(source_name)
        if source.suffix == ".pyc":
            try:
                source = Path(importlib.util.source_from_cache(str(source)))
            except ValueError:
                continue
        if source.suffix != ".py":
            continue
        try:
            source.resolve().relative_to(payload_dir)
        except (OSError, ValueError):
            continue
        sources.add(source.resolve())
    return sorted(sources)


def precompile_startup(payload_dir: Path) -> tuple[int, int]:
    """Import Stimma from *payload_dir* and compile its startup modules."""
    payload_dir = payload_dir.resolve()
    backend_dir = payload_dir / "backend"
    main_path = backend_dir / "main.py"
    if not main_path.is_file():
        raise FileNotFoundError(f"portable backend entry point not found: {main_path}")

    scratch_dir = Path(tempfile.mkdtemp(prefix="stimma-precompile-"))
    previous_cwd = Path.cwd()
    previous_argv = sys.argv[:]
    previous_dont_write = sys.dont_write_bytecode
    previous_path = sys.path[:]
    previous_data_dir = os.environ.get("STIMMA_DATA_DIR")
    previous_cache_dir = os.environ.get("STIMMA_CACHE_DIR")

    try:
        os.environ["STIMMA_DATA_DIR"] = str(scratch_dir)
        os.environ["STIMMA_CACHE_DIR"] = str(scratch_dir)
        os.chdir(payload_dir)
        sys.argv = [str(main_path)]
        sys.path[:0] = [str(backend_dir), str(payload_dir)]

        # Discover the dependency graph without first writing bytecode that
        # embeds machine-specific build paths in traceback filenames.
        sys.dont_write_bytecode = True
        importlib.import_module("main")
        sources = _source_modules_under(payload_dir)

        compiled = 0
        compiled_bytes = 0
        for source in sources:
            relative_source = source.relative_to(payload_dir).as_posix()
            cache_path = Path(importlib.util.cache_from_source(str(source)))
            py_compile.compile(
                str(source),
                cfile=str(cache_path),
                dfile=f"<stimma>/{relative_source}",
                doraise=True,
                # The packaged payload is immutable and every release rebuilds
                # these caches.  Unchecked hashes let Python skip even opening
                # the source file, keeping real-time antivirus out of the hot
                # startup path while remaining independent of installer mtimes.
                invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
            )
            compiled += 1
            compiled_bytes += cache_path.stat().st_size

        return compiled, compiled_bytes
    finally:
        logging.shutdown()
        sys.path[:] = previous_path
        sys.argv = previous_argv
        sys.dont_write_bytecode = previous_dont_write
        os.chdir(previous_cwd)
        if previous_data_dir is None:
            os.environ.pop("STIMMA_DATA_DIR", None)
        else:
            os.environ["STIMMA_DATA_DIR"] = previous_data_dir
        if previous_cache_dir is None:
            os.environ.pop("STIMMA_CACHE_DIR", None)
        else:
            os.environ["STIMMA_CACHE_DIR"] = previous_cache_dir
        shutil.rmtree(scratch_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload_dir", type=Path)
    args = parser.parse_args()

    count, byte_count = precompile_startup(args.payload_dir)
    print(
        f"Precompiled {count} startup modules "
        f"({byte_count / 1024 / 1024:.1f} MiB of bytecode)."
    )
    if count == 0:
        raise RuntimeError("startup import produced no portable bytecode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
