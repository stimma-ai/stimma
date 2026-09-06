#!/usr/bin/env python3
"""Package an already built frontend for authenticated mobile delivery."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from mobile_ui_package import build_ui_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_ui_package(args.source, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
