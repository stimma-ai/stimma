"""Versioned model bundles on the models bucket: pack, verify, publish, pin.

    stimma models pack MODEL_DIR --version YYYY-MM-DD.N --license FILE [--model FILE] [--cut X] [--out DIR]
    stimma models verify RELEASE_DIR | VERSION | pinned   [--base-url URL] [--selftest]
    stimma models publish RELEASE_DIR [--bucket NAME] [--dry-run]
    stimma models pin RELEASE_DIR

A release dir holds exactly the files its manifest lists plus manifest.json. `pack`
builds one from an ALLOWLIST (the ONNX model, the tokenizer files, a trimmed io.json,
LICENSE): nothing else in the source directory is ever read or copied. `publish`
uploads a verified release dir to `<prefix>/<version>/` on the models bucket over
R2's S3 API (multipart for large files), refuses to overwrite an existing version,
checks the public URL serves every file intact, then writes the app's pin
(backend/model_manifests/<name>.json). Credentials come from the environment only:
R2_S3_ENDPOINT, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and STIMMA_MODELS_R2_BUCKET
(or --bucket).

Only the pick judge (name "pick-judge", JUDGE_IO contract 1) is packed today; verify
and publish work for any bundle manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
PINS = BACKEND / "model_manifests"
DEFAULT_BASE_URL = "https://models.stimma.ai"
VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.[1-9]\d*$")
NAME = "pick-judge"
CONTRACT = 1
MODEL_NAME = "model.int8.onnx"
# Everything a pick-judge release may hold, and nothing else.
ALLOWED = (MODEL_NAME, "tokenizer.json", "tokenizer_config.json", "io.json", "LICENSE")
IO_FIELDS = ("kind", "inputs", "output", "maxlen", "cut")
CHUNK = 1 << 20
# Neutral, made-up picks the pack step scores through the app's own OnnxJudge. Their
# P(wrong) goes in the manifest, so any machine can check it runs the judge the same.
SELFTEST = [
    {"state": "A watercolour of a lighthouse at [Time of day], gulls over the rocks.",
     "label": "Time of day", "about": "", "value": "dusk", "user_prompt": "a lighthouse, watercolour"},
    {"state": "A watercolour of a lighthouse at [Time of day], gulls over the rocks.",
     "label": "Time of day", "about": "", "value": "a frozen tuesday", "user_prompt": "a lighthouse, watercolour"},
    {"state": "A portrait of an elderly fisherman with [Hair], weathered hands on a net.",
     "label": "Hair", "about": "", "value": "thin white hair", "user_prompt": "an old fisherman"},
    {"state": "A portrait of an elderly fisherman with [Hair], weathered hands on a net.",
     "label": "Hair", "about": "", "value": "a toddler's pigtails", "user_prompt": "an old fisherman"},
    {"state": "A small child in [Outfit] building a sandcastle at the beach.",
     "label": "Outfit", "about": "what the child wears", "value": "a striped swimsuit", "user_prompt": ""},
    {"state": "A small child in [Outfit] building a sandcastle at the beach.",
     "label": "Outfit", "about": "what the child wears", "value": "a three-piece business suit", "user_prompt": ""},
]
SELFTEST_TOLERANCE = 0.05  # int8 kernels differ slightly across CPUs (measured < 0.03 on 50 items)
# Text files must not carry a machine's paths into a public bucket.
PRIVATE_PATH = re.compile(r"(/home/|/Users/|[A-Za-z]:\\\\Users)")


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(release: Path) -> dict:
    p = release / "manifest.json"
    if not p.is_file():
        die(f"{release} has no manifest.json")
    return json.loads(p.read_text())


def selftest_scores(release: Path, manifest: dict) -> list[float]:
    """P(wrong) of the SELFTEST items through the app's OnnxJudge (needs the backend env)."""
    sys.path.insert(0, str(BACKEND))
    from prompt_programs.fix import Item, OnnxJudge
    j = OnnxJudge(release, threads=4, manifest=manifest)
    return [round(p, 4) for p in j.p_wrong([Item(**x) for x in manifest.get("selftest", {}).get("items", SELFTEST)])]


# --------------------------------------------------------------------------- pack

def pack(a: argparse.Namespace) -> None:
    src = Path(a.model_dir)
    if not VERSION_RE.match(a.version):
        die("--version must look like YYYY-MM-DD.N")
    model = Path(a.model) if a.model else src / MODEL_NAME
    lic = Path(a.license) if a.license else src / "LICENSE"
    for need in (model, src / "tokenizer.json", src / "tokenizer_config.json", src / "io.json", lic):
        if not need.is_file():
            die(f"missing {need}")
    out = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix=f"{NAME}-")) / a.version
    if out.exists() and any(out.iterdir()):
        die(f"{out} isn't empty")
    out.mkdir(parents=True, exist_ok=True)

    io_src = json.loads((src / "io.json").read_text())
    io = {k: io_src[k] for k in IO_FIELDS if k in io_src}
    if a.cut is not None:
        io["cut"] = float(a.cut)
    if io.get("kind") not in ("enc", "dec") or not isinstance(io.get("cut"), (int, float)):
        die("io.json needs kind and cut")
    shutil.copyfile(model, out / MODEL_NAME)
    shutil.copyfile(src / "tokenizer.json", out / "tokenizer.json")
    shutil.copyfile(src / "tokenizer_config.json", out / "tokenizer_config.json")
    shutil.copyfile(lic, out / "LICENSE")
    (out / "io.json").write_text(json.dumps(io, indent=1) + "\n")
    for name in ("tokenizer_config.json", "io.json", "LICENSE"):
        if PRIVATE_PATH.search((out / name).read_text(errors="replace")):
            die(f"{name} contains a local filesystem path; fix the source before packing")

    labels = ["fine", "odd", "wrong"]
    manifest = {
        "name": NAME, "version": a.version, "contract": CONTRACT,
        "kind": io["kind"], "maxlen": int(io.get("maxlen") or 512), "output": "probs",
        "labels": labels, "wrong": "wrong", "cut": round(float(io["cut"]), 6), "model": MODEL_NAME,
        "files": [{"path": n, "size": (out / n).stat().st_size, "sha256": sha256_file(out / n)} for n in ALLOWED],
        "base_model": a.base_model, "license": a.license_id,
    }
    if a.metrics:
        manifest["metrics"] = json.loads(a.metrics)
    manifest["selftest"] = {"items": SELFTEST}
    manifest["selftest"]["p_wrong"] = selftest_scores(out, manifest)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    check_release(out)
    total = sum(f["size"] for f in manifest["files"])
    print(json.dumps({"release": str(out), "version": a.version, "bytes": total,
                      "mib": round(total / 1024 / 1024, 1), "cut": manifest["cut"],
                      "selftest": manifest["selftest"]["p_wrong"]}, indent=1))


# --------------------------------------------------------------------------- verify

def check_release(release: Path, selftest: bool = False) -> dict:
    """A release dir holds exactly its manifest's files, each with its size and sha256."""
    m = read_manifest(release)
    if not VERSION_RE.match(str(m.get("version"))):
        die("the manifest's version isn't YYYY-MM-DD.N")
    if release.name != m["version"]:
        die(f"the release dir must be named after its version ({m['version']})")
    listed = {f["path"] for f in m["files"]}
    if m.get("name") == NAME and not listed <= set(ALLOWED):
        die(f"the manifest lists files outside the allowlist: {sorted(listed - set(ALLOWED))}")
    present = {str(p.relative_to(release)) for p in release.rglob("*") if p.is_file()} - {"manifest.json"}
    if present != listed:
        die(f"the release dir doesn't match its manifest: extra {sorted(present - listed)}, "
            f"missing {sorted(listed - present)}")
    for f in m["files"]:
        p = release / f["path"]
        if p.stat().st_size != f["size"] or sha256_file(p) != f["sha256"]:
            die(f"{f['path']} doesn't match its manifest")
    if selftest and m.get("selftest"):
        got = selftest_scores(release, m)
        want = m["selftest"]["p_wrong"]
        worst = max(abs(x - y) for x, y in zip(got, want))
        if worst > SELFTEST_TOLERANCE:
            die(f"selftest differs from the manifest by {worst:.4f} (got {got}, want {want})")
        print(f"selftest: max |dP| {worst:.4f} over {len(got)} items")
    return m


def _fetch(url: str, timeout: float = 60.0):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Stimma/1.0"}), timeout=timeout)


def check_remote(manifest: dict, base: str) -> None:
    """The bucket serves this manifest and every file it lists, byte for byte."""
    root = f"{base.rstrip('/')}/{manifest['name']}/{manifest['version']}"
    with _fetch(f"{root}/manifest.json") as r:
        served = json.loads(r.read())
    if served != manifest:
        die(f"{root}/manifest.json differs from the local manifest")
    for f in manifest["files"]:
        h, n = hashlib.sha256(), 0
        with _fetch(f"{root}/{f['path']}") as r:
            while chunk := r.read(CHUNK):
                h.update(chunk)
                n += len(chunk)
        if n != f["size"] or h.hexdigest() != f["sha256"]:
            die(f"{root}/{f['path']} doesn't match the manifest ({n} bytes)")
        print(f"ok  {f['path']}  {n} bytes")
    print(f"verified {root}")


def verify(a: argparse.Namespace) -> None:
    target = a.target
    base = a.base_url or os.environ.get("STIMMA_MODELS_BASE_URL") or DEFAULT_BASE_URL
    if Path(target).is_dir():
        m = check_release(Path(target), selftest=a.selftest)
        print(f"release {target}: {len(m['files'])} files match manifest {m['name']}/{m['version']}")
        return
    pin = PINS / f"{NAME}.json"
    m = json.loads(pin.read_text())
    if target not in ("pinned", m["version"]):
        die(f"{target} isn't a release dir or the pinned version ({m['version']})")
    check_remote(m, base)


# --------------------------------------------------------------------------- publish / pin

def write_pin(release: Path) -> Path:
    m = check_release(release)
    PINS.mkdir(parents=True, exist_ok=True)
    pin = PINS / f"{m['name']}.json"
    shutil.copyfile(release / "manifest.json", pin)
    print(f"pinned {m['name']}/{m['version']} in {pin.relative_to(REPO)}: commit it")
    return pin


def pin(a: argparse.Namespace) -> None:
    write_pin(Path(a.release))


def publish(a: argparse.Namespace) -> None:
    release = Path(a.release)
    m = check_release(release)
    prefix = f"{m['name']}/{m['version']}"
    bucket = a.bucket or os.environ.get("STIMMA_MODELS_R2_BUCKET", "")
    keys = [f["path"] for f in m["files"]] + ["manifest.json"]  # the manifest goes up last
    if a.dry_run:
        print(json.dumps({"bucket": bucket or "(STIMMA_MODELS_R2_BUCKET)", "prefix": prefix, "upload": keys}, indent=1))
        return
    env = {k: "".join(os.environ.get(k, "").split()) for k in ("R2_S3_ENDPOINT", "AWS_ACCESS_KEY_ID",
                                                               "AWS_SECRET_ACCESS_KEY")}
    if not bucket or not all(env.values()):
        die("set STIMMA_MODELS_R2_BUCKET (or --bucket), R2_S3_ENDPOINT, AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")
    if not re.fullmatch(r"https://[a-f0-9]{32}\.r2\.cloudflarestorage\.com", env["R2_S3_ENDPOINT"].rstrip("/")):
        die("R2_S3_ENDPOINT must be an HTTPS R2 S3 endpoint")
    import boto3
    from boto3.s3.transfer import TransferConfig
    from botocore.config import Config
    client = boto3.client("s3", endpoint_url=env["R2_S3_ENDPOINT"], region_name="auto",
                          aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
                          aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
                          config=Config(retries={"mode": "standard", "max_attempts": 5},
                                        request_checksum_calculation="when_required",
                                        response_checksum_validation="when_required"))
    existing = client.list_objects_v2(Bucket=bucket, Prefix=prefix + "/", MaxKeys=1).get("KeyCount", 0)
    if existing:
        die(f"{prefix}/ already exists in {bucket}: versions are immutable, pack a new one (.N+1)")
    transfer = TransferConfig(multipart_threshold=64 << 20, multipart_chunksize=64 << 20, max_concurrency=4)
    types = {".json": "application/json", ".onnx": "application/octet-stream"}
    for k in keys:
        p = release / k
        extra = {"ContentType": types.get(p.suffix, "text/plain; charset=utf-8"),
                 "CacheControl": "public, max-age=31536000, immutable"}
        print(f"uploading {prefix}/{k} ({p.stat().st_size} bytes)")
        client.upload_file(str(p), bucket, f"{prefix}/{k}", ExtraArgs=extra, Config=transfer)
    base = a.base_url or DEFAULT_BASE_URL
    check_remote(m, base)
    write_pin(release)


def main() -> None:
    ap = argparse.ArgumentParser(prog="stimma models", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack", help="build a release dir from a judge model dir (allowlist only)")
    p.add_argument("model_dir")
    p.add_argument("--version", required=True)
    p.add_argument("--model", help="the ONNX file to ship (default MODEL_DIR/model.int8.onnx)")
    p.add_argument("--license", help="the LICENSE text to ship (default MODEL_DIR/LICENSE)")
    p.add_argument("--cut", type=float, help="P(wrong) cut fitted for this file (default io.json's)")
    p.add_argument("--out", help="the release dir to create, named after the version (default: a temp dir)")
    p.add_argument("--base-model", default="cross-encoder/ettin-reranker-150m-v1")
    p.add_argument("--license-id", default="Apache-2.0")
    p.add_argument("--metrics", help="public metrics as JSON, e.g. '{\"dev_auroc\": 0.876}'")
    p.set_defaults(fn=pack)
    p = sub.add_parser("verify", help="check a release dir, or the pinned version on the bucket")
    p.add_argument("target", help="a release dir, the pinned version, or 'pinned'")
    p.add_argument("--base-url", help=f"models mirror (default STIMMA_MODELS_BASE_URL or {DEFAULT_BASE_URL})")
    p.add_argument("--selftest", action="store_true", help="also score the manifest's selftest items here")
    p.set_defaults(fn=verify)
    p = sub.add_parser("publish", help="upload a release dir to the models bucket, verify it, write the pin")
    p.add_argument("release")
    p.add_argument("--bucket", help="the models bucket (default STIMMA_MODELS_R2_BUCKET)")
    p.add_argument("--base-url", help=f"public URL to verify against (default {DEFAULT_BASE_URL})")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=publish)
    p = sub.add_parser("pin", help="write backend/model_manifests/<name>.json from a release dir")
    p.add_argument("release")
    p.set_defaults(fn=pin)
    a = ap.parse_args()
    # `stimma models` runs this from backend/ (for the app's env); paths are the caller's.
    caller = os.environ.get("STIMMA_CALLER_CWD")
    if caller:
        os.chdir(caller)
    a.fn(a)


if __name__ == "__main__":
    main()
