#!/bin/bash
# Two-hop update continuity harness (macOS, staging sandbox channel).
#
# Hop 1: a fielded-equivalent Tauri build (sandbox 0.0.1) must apply the first
#        Electron build (0.0.2) via its own updater (latest.json + Ed25519 tar).
# Hop 2: that Electron build must apply the next Electron build (0.0.3) via
#        electron-updater (latest-mac.yml + zip).
#
# Usage: electron/tests/update-hops.sh <start-dmg-url> <expected-next-version>
#        [--resume <existing-app-dir>]
# The harness never touches /Applications or real data dirs: the app runs from
# a temp dir with STIMMA_DATA_DIR/STIMMA_CACHE_DIR overrides.

set -euo pipefail

START_DMG_URL="${1:?start dmg url}"
EXPECT_VERSION="${2:?expected updated version}"
RESUME_DIR="${4:-}"

# NOT under /tmp: the Tauri updater refuses app paths that traverse a
# symlink (/tmp -> /private/tmp) with "StartingBinary ... symlink".
SCRATCH_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}/stimma/scratch"
mkdir -p "$SCRATCH_ROOT"
WORK="$(mktemp -d "$SCRATCH_ROOT/update-hop.XXXXXX")"
cleanup() {
  rm -rf -- "$WORK"
}
trap cleanup EXIT HUP INT TERM
echo "workdir: $WORK"
DATA="$WORK/data"; CACHE="$WORK/cache"
mkdir -p "$DATA" "$CACHE"

if [ "${3:-}" = "--resume" ] && [ -n "$RESUME_DIR" ]; then
  APP_DIR="$RESUME_DIR"
else
  echo "Downloading start artifact..."
  curl -fsSL -o "$WORK/start.dmg" "$START_DMG_URL"
  MOUNT="$(hdiutil attach -nobrowse -readonly "$WORK/start.dmg" | awk -F'\t' '/\/Volumes\//{print $NF; exit}')"
  APP_SRC="$(find "$MOUNT" -maxdepth 1 -name '*.app' -print -quit)"
  APP_DIR="$WORK/apps"
  mkdir -p "$APP_DIR"
  ditto "$APP_SRC" "$APP_DIR/$(basename "$APP_SRC")"
  hdiutil detach "$MOUNT" >/dev/null
fi

APP_BUNDLE="$(find "$APP_DIR" -maxdepth 1 -name '*.app' -print -quit)"
BIN="$APP_BUNDLE/Contents/MacOS/$(defaults read "$APP_BUNDLE/Contents/Info.plist" CFBundleExecutable)"
START_VERSION="$(defaults read "$APP_BUNDLE/Contents/Info.plist" CFBundleShortVersionString)"
echo "installed: $APP_BUNDLE ($START_VERSION)"

env -u ELECTRON_RUN_AS_NODE -u STIMMA_DEV \
  STIMMA_SANDBOX=update-hop STIMMA_DATA_DIR="$DATA" STIMMA_CACHE_DIR="$CACHE" \
  "$BIN" >/dev/null 2>&1 &
APP_PID=$!
echo "launched pid $APP_PID; waiting for the updater to stage $EXPECT_VERSION..."

# The bundle on disk is swapped when the update is applied/staged (Tauri
# install() swaps immediately; electron-updater swaps at quit — so for the
# Electron hop we wait for the staged marker instead, then quit).
DEADLINE=$(( $(date +%s) + 900 ))
staged=""
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  ON_DISK="$(defaults read "$APP_BUNDLE/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo unknown)"
  if [ "$ON_DISK" = "$EXPECT_VERSION" ]; then staged="bundle-swapped"; break; fi
  # electron-updater staging marker: our updater module logs download
  # completion into the shell log.
  if grep -qiE "\[updater\].*(downloaded|update-downloaded)" "$DATA/Logs/Stimma-shell.log" 2>/dev/null; then
    staged="electron-pending"; break
  fi
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    echo "App exited before staging an update."; exit 1
  fi
  sleep 5
done
if [ -z "$staged" ]; then
  echo "Timed out waiting for update staging."; kill "$APP_PID" 2>/dev/null || true; exit 1
fi
echo "update staged ($staged); quitting app to apply..."
kill "$APP_PID" 2>/dev/null || true
wait "$APP_PID" 2>/dev/null || true

# Squirrel's ShipIt swaps the bundle asynchronously after quit; poll for it.
APPLY_DEADLINE=$(( $(date +%s) + 180 ))
while [ "$(date +%s)" -lt "$APPLY_DEADLINE" ]; do
  ON_DISK="$(defaults read "$APP_BUNDLE/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo unknown)"
  [ "$ON_DISK" = "$EXPECT_VERSION" ] && break
  sleep 5
done
if [ "$ON_DISK" != "$EXPECT_VERSION" ]; then
  echo "Bundle version after quit is $ON_DISK, expected $EXPECT_VERSION"; exit 1
fi
echo "ok - bundle updated to $EXPECT_VERSION"

# The executable name changes across the Tauri→Electron swap; recompute.
BIN="$APP_BUNDLE/Contents/MacOS/$(defaults read "$APP_BUNDLE/Contents/Info.plist" CFBundleExecutable)"

# Relaunch and prove the updated app boots (backend handshake in shell log for
# Electron; process liveness for either shell).
env -u ELECTRON_RUN_AS_NODE -u STIMMA_DEV \
  STIMMA_SANDBOX=update-hop STIMMA_DATA_DIR="$DATA" STIMMA_CACHE_DIR="$CACHE" \
  "$BIN" >"$WORK/relaunch.log" 2>&1 &
NEW_PID=$!
sleep 60
if ! kill -0 "$NEW_PID" 2>/dev/null; then
  echo "Updated app did not stay running. Output:"; tail -20 "$WORK/relaunch.log"; exit 1
fi
if [ -f "$DATA/Logs/Stimma-shell.log" ]; then
  echo "ok - Electron shell log present after update"
  grep -q "Detected port:" "$DATA/Logs/Stimma-shell.log" && echo "ok - backend up under updated app"
fi
kill "$NEW_PID" 2>/dev/null || true
wait "$NEW_PID" 2>/dev/null || true

echo "hop complete: $START_VERSION -> $EXPECT_VERSION"
echo "app dir for next hop: $APP_DIR"
