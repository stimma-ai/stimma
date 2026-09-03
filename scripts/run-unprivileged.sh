#!/usr/bin/env bash
# Run a command as an unprivileged user when the caller is root.
#
# Chromium refuses to start as root unless its sandbox is switched off
# (crbug.com/638180), and an AppImage mounts nosuid so the bundled
# chrome-sandbox helper cannot carry setuid either. Some self-hosted runners
# execute jobs as root, which makes every Electron-launching gate fail there
# while the same gates pass on the non-root x86_64 runners.
#
# Dropping privileges is preferred over passing --no-sandbox: these gates should
# keep exercising the sandboxed configuration that real users run.
#
# Usage: scripts/run-unprivileged.sh <command> [args...]
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  exec "$@"
fi

# Reuse the runner image's own unprivileged account when it has one.
CI_USER=""
# stimma-ci is last so a container we already provisioned is reused: these
# runners are not ephemeral, so the account survives between jobs.
for candidate in "${STIMMA_CI_USER:-}" runner ubuntu stimma-ci; do
  if [ -n "$candidate" ] && id -u "$candidate" >/dev/null 2>&1; then
    CI_USER="$candidate"
    break
  fi
done
if [ -z "$CI_USER" ]; then
  CI_USER="stimma-ci"
  useradd --create-home --shell /bin/bash "$CI_USER"
fi

CI_HOME="$(getent passwd "$CI_USER" | cut -d: -f6)"
: "${CI_HOME:=/home/$CI_USER}"
mkdir -p "$CI_HOME/tmp"
chown "$CI_USER:$CI_USER" "$CI_HOME" "$CI_HOME/tmp"

# Root's umask leaves the checkout world-readable, so these lanes can already
# read the build output and node_modules. They do write back into a couple of
# places, which must belong to the unprivileged user. Resolve them from this
# script's own location so the caller's working directory does not matter.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for dir in "$REPO_ROOT/electron/dist" "$REPO_ROOT/electron/out"; do
  [ -e "$dir" ] && chown -R "$CI_USER:$CI_USER" "$dir"
done

# A root-owned RUNNER_TEMP is not writable for the dropped user; the lanes fall
# back to their own scratch directories under HOME.
# runuser resets PATH to a conservative default, which would drop the toolchain
# the workflow put there (setup-node, uv). Carry the caller's PATH across.
exec runuser -u "$CI_USER" -- \
  env HOME="$CI_HOME" TMPDIR="$CI_HOME/tmp" PATH="$PATH" "$@"
