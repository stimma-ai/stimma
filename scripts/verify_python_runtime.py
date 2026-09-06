"""Import runtime-sensitive packages from a staged portable Python payload."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import sys


RUNTIME_IMPORTS = (
    "alembic",
    "cmap",
    "imgviz",
    "lxml",
    "numpy",
    "onnx",
    "onnxruntime",
    "osam",
    "PIL",
    "pypdfium2",
    "scipy",
    "skimage",
    "sqlalchemy",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload_dir", type=Path)
    args = parser.parse_args()
    payload = args.payload_dir.resolve()
    sys.path[:0] = [str(payload / "backend"), str(payload)]
    for module in RUNTIME_IMPORTS:
        importlib.import_module(module)
    print(f"Portable runtime import smoke passed ({len(RUNTIME_IMPORTS)} packages).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
