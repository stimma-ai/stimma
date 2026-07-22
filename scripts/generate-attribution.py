#!/usr/bin/env python3
"""Regenerate the dependency tables in ATTRIBUTION.md.

Reads the real dependency graphs (backend uv venv, frontend node_modules,
src-tauri cargo metadata) and rewrites the generated sections of
ATTRIBUTION.md between the BEGIN/END GENERATED markers. Hand-written prose
outside the markers is left untouched.

Run from the repo root on a machine with the dev environment set up
(backend venv synced, frontend node_modules installed, Rust toolchain):

    python3 scripts/generate-attribution.py

The tables list every third-party package that ships in the packaged app:
  - Python: full `uv export --no-dev` set (the whole venv is bundled)
  - npm: production dependency closure (what Vite bundles into the webview)
  - Rust: crates reachable from src-tauri + watchdog via normal/build edges,
    with build-time-only crates marked (they run during compilation and are
    not linked into shipped binaries, but are listed for completeness)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ATTRIBUTION = REPO_ROOT / "ATTRIBUTION.md"

# ---------------------------------------------------------------------------
# License-string helpers

# Packages whose installed metadata is missing/vague (platform-conditional
# deps not installed on the machine running this script, or packages that
# embed full license text instead of an identifier). Verified against the
# package's own LICENSE file or PyPI.
PY_OVERRIDES = {
    "colorama": ("BSD-3-Clause", "https://github.com/tartley/colorama"),
    "win32-setctime": ("MIT", "https://github.com/Delgan/win32-setctime"),
    "pyreadline3": ("BSD-3-Clause", "https://github.com/pyreadline3/pyreadline3"),
    "jeepney": ("MIT", "https://gitlab.com/takluyver/jeepney"),
    "secretstorage": ("BSD-3-Clause", "https://github.com/mitya57/secretstorage"),
    "brotlicffi": ("MIT", "https://github.com/python-hyper/brotlicffi"),
    "pysocks": ("BSD-3-Clause", "https://github.com/Anorov/PySocks"),
    "humanfriendly": ("MIT", "https://humanfriendly.readthedocs.io"),
    "coloredlogs": ("MIT", "https://coloredlogs.readthedocs.io"),
    "pillow": ("HPND", "https://github.com/python-pillow/Pillow"),
    "pyphen": (
        "GPL-2.0+ OR LGPL-2.1+ OR MPL-1.1 (used under MPL-1.1)",
        "https://github.com/Kozea/Pyphen",
    ),
    "tld": (
        "MPL-1.1 OR GPL-2.0 OR LGPL-2.1+ (used under MPL-1.1)",
        "https://github.com/barseghyanartur/tld",
    ),
    "tqdm": ("MPL-2.0 AND MIT", "https://github.com/tqdm/tqdm"),
    "pypdfium2": (
        "BSD-3-Clause AND Apache-2.0 (bundles PDFium and its third-party libraries)",
        "https://github.com/pypdfium2-team/pypdfium2",
    ),
    "regex": ("Apache-2.0 AND CNRI-Python", "https://github.com/mrabarnett/mrab-regex"),
    "ffmpeg-python": ("Apache-2.0", "https://github.com/kkroening/ffmpeg-python"),
    # Platform-conditional (not installed in the macOS venv this usually runs in)
    "cryptography": ("Apache-2.0 OR BSD-3-Clause", "https://github.com/pyca/cryptography"),
    "tzdata": ("Apache-2.0", "https://github.com/python/tzdata"),
}

# npm packages missing license metadata, verified against upstream:
# (license, repository URL).
NPM_OVERRIDES = {
    # No license field in the published package or its source manifest; the
    # publish source repo dual-licenses it via root LICENSE_MIT +
    # LICENSE_APACHE-2.0 (LICENSE.spdx declares both; © CrabNebula Ltd.).
    # Same repo publishes the Rust tauri-plugin-drag crate under the same
    # dual grant.
    "@crabnebula/tauri-plugin-drag": (
        "MIT OR Apache-2.0",
        "https://github.com/crabnebula-dev/drag-rs",
    ),
}

CLASSIFIER_MAP = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: BSD License": "BSD",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: The Unlicense (Unlicense)": "Unlicense",
    "License :: OSI Approved :: Historical Permission Notice and Disclaimer (HPND)": "HPND",
    "License :: OSI Approved :: GNU Affero General Public License v3": "AGPL-3.0",
}


def clean_repo_url(url: str | None) -> str:
    if not url:
        return ""
    url = url.strip()
    url = re.sub(r"^git\+", "", url)
    url = re.sub(r"^git:", "https:", url)
    url = re.sub(r"^ssh://git@", "https://", url)
    url = re.sub(r"\.git$", "", url)
    if url and "://" not in url:
        url = f"https://github.com/{url}"
    return url


def md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def table(rows: list[tuple[str, ...]], header: tuple[str, ...]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for row in rows:
        lines.append("| " + " | ".join(md_escape(c) for c in row) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Python

def python_rows() -> list[tuple[str, ...]]:
    backend = REPO_ROOT / "backend"
    export = subprocess.run(
        ["uv", "export", "--no-dev", "--no-hashes", "--no-emit-project",
         "--format", "requirements-txt"],
        cwd=backend, capture_output=True, text=True, check=True,
    ).stdout
    wanted: dict[str, str] = {}
    for line in export.splitlines():
        line = line.split(";")[0].strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^ ]+)$", line)
        if m:
            wanted[m.group(1).lower().replace("_", "-")] = m.group(2)

    probe = r"""
import importlib.metadata as im, json
out = {}
for d in im.distributions():
    md = d.metadata
    name = (md["Name"] or "").lower().replace("_", "-").replace(".", "-")
    lic = md.get("License-Expression") or ""
    raw = md.get("License") or ""
    classifiers = [c for c in (md.get_all("Classifier") or []) if c.startswith("License")]
    home = md.get("Home-page") or ""
    if not home:
        for u in md.get_all("Project-URL") or []:
            label, _, link = u.partition(",")
            if label.strip().lower() in ("homepage", "repository", "source", "source code"):
                home = link.strip(); break
        else:
            urls = md.get_all("Project-URL") or []
            if urls:
                home = urls[0].partition(",")[2].strip()
    out[name] = {"version": md["Version"], "expr": lic, "raw": raw,
                 "classifiers": classifiers, "home": home}
print(json.dumps(out))
"""
    meta = json.loads(subprocess.run(
        ["uv", "run", "python", "-c", probe],
        cwd=backend, capture_output=True, text=True, check=True,
    ).stdout)

    rows = []
    for name in sorted(wanted):
        version = wanted[name]
        info = meta.get(name)
        if name in PY_OVERRIDES:
            lic, home = PY_OVERRIDES[name]
            if info and info.get("home"):
                home = info["home"]
        elif info:
            lic = info["expr"]
            if not lic:
                for c in info["classifiers"]:
                    if c in CLASSIFIER_MAP:
                        lic = CLASSIFIER_MAP[c]
                        break
            if not lic and info["raw"] and len(info["raw"]) <= 60:
                lic = info["raw"]
            if not lic:
                print(f"WARNING: no license resolved for python package {name}",
                      file=sys.stderr)
                lic = "see upstream"
            home = info["home"]
        else:
            print(f"WARNING: {name} not installed and not in PY_OVERRIDES; "
                  f"license unresolved", file=sys.stderr)
            lic, home = "see upstream", ""
        rows.append((name, version, lic, clean_repo_url(home)))
    return rows


# ---------------------------------------------------------------------------
# npm

def npm_rows() -> list[tuple[str, ...]]:
    frontend = REPO_ROOT / "frontend"

    def read_pkg(path: Path) -> dict | None:
        try:
            return json.loads((path / "package.json").read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def resolve(name: str, from_dir: Path) -> Path | None:
        cur = from_dir
        while True:
            candidate = cur / "node_modules" / name
            if (candidate / "package.json").exists():
                return candidate
            if cur == REPO_ROOT or cur.parent == cur:
                return None
            cur = cur.parent

    root_pkg = read_pkg(frontend)
    queue: list[tuple[str, Path]] = [
        (dep, frontend) for dep, spec in (root_pkg.get("dependencies") or {}).items()
        if not str(spec).startswith("file:")
    ]
    seen: dict[str, dict] = {}
    while queue:
        name, from_dir = queue.pop()
        if name in seen:
            continue
        loc = resolve(name, from_dir)
        if loc is None:
            print(f"WARNING: npm package {name} not found in node_modules",
                  file=sys.stderr)
            continue
        pkg = read_pkg(loc)
        lic = pkg.get("license")
        if isinstance(lic, dict):
            lic = lic.get("type", "")
        if not lic and isinstance(pkg.get("licenses"), list):
            lic = " OR ".join(entry.get("type", "") for entry in pkg["licenses"])
        override_repo = None
        if not lic:
            if name in NPM_OVERRIDES:
                lic, override_repo = NPM_OVERRIDES[name]
            else:
                print(f"WARNING: no license for npm package {name}", file=sys.stderr)
                lic = "see upstream"
        repo = pkg.get("repository")
        if isinstance(repo, dict):
            repo = repo.get("url", "")
        repo = repo or override_repo
        seen[name] = {"version": pkg.get("version", ""), "license": lic,
                      "repo": clean_repo_url(repo or pkg.get("homepage"))}
        for dep in (pkg.get("dependencies") or {}):
            queue.append((dep, loc))

    return [(n, seen[n]["version"], seen[n]["license"], seen[n]["repo"])
            for n in sorted(seen)]


# ---------------------------------------------------------------------------
# Rust

def cargo_rows(manifest_dir: Path) -> list[tuple[str, ...]]:
    meta = json.loads(subprocess.run(
        ["cargo", "metadata", "--format-version", "1", "--offline"],
        cwd=manifest_dir, capture_output=True, text=True, check=True,
    ).stdout)
    packages = {p["id"]: p for p in meta["packages"]}
    nodes = {n["id"]: n for n in meta["resolve"]["nodes"]}
    workspace = set(meta["workspace_members"])
    roots = list(workspace)

    def reach(kinds: set[str | None]) -> set[str]:
        out, stack = set(roots), list(roots)
        while stack:
            nid = stack.pop()
            for dep in nodes[nid]["deps"]:
                if any(k["kind"] in kinds for k in dep["dep_kinds"]):
                    if dep["pkg"] not in out:
                        out.add(dep["pkg"])
                        stack.append(dep["pkg"])
        return out

    shipped = reach({None, "build"})
    runtime = reach({None})

    by_name: dict[str, dict] = defaultdict(lambda: {"versions": [], "build_only": True})
    # Sort so that for multi-version crates the license/repo strings come
    # deterministically from the highest version, not iteration order.
    for pid in sorted(shipped, key=lambda p: (packages[p]["name"], packages[p]["version"])):
        if pid in workspace:
            continue
        pkg = packages[pid]
        entry = by_name[pkg["name"]]
        entry["versions"].append(pkg["version"])
        entry["license"] = pkg.get("license") or "see upstream"
        entry["repo"] = clean_repo_url(pkg.get("repository"))
        if pid in runtime:
            entry["build_only"] = False
        if not pkg.get("license"):
            print(f"WARNING: no license for crate {pkg['name']}", file=sys.stderr)

    rows = []
    for name in sorted(by_name):
        e = by_name[name]
        note = "build-time only" if e["build_only"] else ""
        rows.append((name, ", ".join(sorted(set(e["versions"]))),
                     e["license"].replace("/", " OR "), e["repo"], note))
    return rows


# ---------------------------------------------------------------------------

def replace_section(content: str, key: str, body: str) -> str:
    begin, end = f"<!-- BEGIN GENERATED: {key} -->", f"<!-- END GENERATED: {key} -->"
    if begin not in content or end not in content:
        sys.exit(f"ERROR: markers for '{key}' not found in {ATTRIBUTION}")
    head, _, rest = content.partition(begin)
    _, _, tail = rest.partition(end)
    return f"{head}{begin}\n{body}\n{end}{tail}"


def main() -> None:
    content = ATTRIBUTION.read_text()

    py = python_rows()
    content = replace_section(
        content, "python",
        f"{len(py)} packages (direct and transitive; the entire environment "
        "is bundled with the app).\n\n"
        + table(py, ("Package", "Version", "License", "Source")))

    npm = npm_rows()
    content = replace_section(
        content, "npm",
        f"{len(npm)} packages (production dependency closure bundled into "
        "the UI).\n\n"
        + table(npm, ("Package", "Version", "License", "Source")))

    rust_main = cargo_rows(REPO_ROOT / "src-tauri")
    rust_wd = cargo_rows(REPO_ROOT / "src-tauri" / "watchdog")
    merged: dict[str, tuple[str, ...]] = {r[0]: r for r in rust_main}
    for r in rust_wd:
        if r[0] not in merged:
            merged[r[0]] = r
    rust = [merged[n] for n in sorted(merged)]
    shipped_count = sum(1 for r in rust if not r[4])
    content = replace_section(
        content, "rust",
        f"{len(rust)} crates ({shipped_count} compiled into shipped binaries; "
        "the rest are marked build-time only).\n\n"
        + table(rust, ("Crate", "Version(s)", "License", "Source", "Notes")))

    ATTRIBUTION.write_text(content)
    print(f"Updated {ATTRIBUTION}: {len(py)} python, {len(npm)} npm, "
          f"{len(rust)} rust entries.")


if __name__ == "__main__":
    main()
