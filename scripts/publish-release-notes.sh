#!/usr/bin/env bash
# Publish releasenotes/v*.md to R2 and rebuild the notes index.
#
# Runs in CI (see .github/workflows/release-notes.yml) with R2 credentials;
# it is not expected to work on contributor machines. Always publishes from
# the checked-out tree, so committing a notes edit to main re-deploys it.
#
# Required env: BUCKET, R2_S3_ENDPOINT, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
set -euo pipefail

for var in BUCKET R2_S3_ENDPOINT AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; do
  if [ -z "${!var:-}" ]; then
    echo "$var is required." >&2
    exit 1
  fi
done

R2_S3_ENDPOINT="$(printf '%s' "$R2_S3_ENDPOINT" | tr -d '[:space:]')"
AWS_ACCESS_KEY_ID="$(printf '%s' "$AWS_ACCESS_KEY_ID" | tr -d '[:space:]')"
AWS_SECRET_ACCESS_KEY="$(printf '%s' "$AWS_SECRET_ACCESS_KEY" | tr -d '[:space:]')"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

PREFIX="stimma/notes"

shopt -s nullglob
NOTE_FILES=(releasenotes/v*.md)
if [ ${#NOTE_FILES[@]} -eq 0 ]; then
  echo "No release notes found under releasenotes/ — nothing to publish."
  exit 0
fi

# Build index.json: one entry per notes file, newest version first.
# "released" means a production tag (plain vX.Y.Z) exists for that version;
# unreleased entries are drafts for an upcoming version (visible to beta
# builds, hidden from the public changelog).
python3 - "${NOTE_FILES[@]}" <<'PY' > notes-index.json
import json, re, subprocess, sys

entries = []
for path in sys.argv[1:]:
    m = re.fullmatch(r"releasenotes/v(\d+)\.(\d+)\.(\d+)\.md", path)
    if not m:
        print(f"Skipping unrecognized notes file: {path}", file=sys.stderr)
        continue
    version = ".".join(m.groups())
    tag = subprocess.run(
        ["git", "tag", "-l", f"v{version}"], capture_output=True, text=True
    ).stdout.strip()
    date = subprocess.run(
        ["git", "log", "-1", "--format=%cs", "--", path], capture_output=True, text=True
    ).stdout.strip()
    entries.append({
        "version": version,
        "file": f"v{version}.md",
        "date": date or None,
        "released": bool(tag),
    })

entries.sort(key=lambda e: tuple(int(p) for p in e["version"].split(".")), reverse=True)
json.dump({"notes": entries}, sys.stdout, indent=2)
PY

echo "Publishing ${#NOTE_FILES[@]} notes file(s) to s3://${BUCKET}/${PREFIX}/"
for f in "${NOTE_FILES[@]}"; do
  aws s3 cp "$f" "s3://${BUCKET}/${PREFIX}/$(basename "$f")" \
    --content-type "text/markdown; charset=utf-8" \
    --cache-control "no-cache" \
    --endpoint-url "$R2_S3_ENDPOINT"
done

aws s3 cp notes-index.json "s3://${BUCKET}/${PREFIX}/index.json" \
  --content-type application/json \
  --cache-control "no-cache" \
  --endpoint-url "$R2_S3_ENDPOINT"

echo "Done."
cat notes-index.json
