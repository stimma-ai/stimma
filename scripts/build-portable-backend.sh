#!/bin/bash
set -euo pipefail

# Portable Python backend with first-party source.
# This intentionally avoids Python-to-native compilers. Native wheels run under a
# normal bundled interpreter, which keeps multiprocessing/import behavior close
# to local `python main.py`.

TARGET=$(rustc -Vv | grep host | cut -f2 -d' ')
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_SRC="$PROJECT_ROOT/backend"
PYTHON_STANDALONE="$PROJECT_ROOT/python-standalone"
OUTPUT_DIR="$PROJECT_ROOT/src-tauri/binaries/stimma-backend-$TARGET"
BUILD_ROOT="$PROJECT_ROOT/build-experimental/portable-backend-$TARGET"
STAGING_DIR="$BUILD_ROOT/staging"
PYTHON_STANDALONE_RELEASE="20260414"
PYTHON_STANDALONE_VERSION="3.11.15+20260414"

echo "=== Portable Backend Build ==="
echo "Target: $TARGET"
echo "Output: $OUTPUT_DIR"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "WARNING: Portable backend path is currently validated for macOS first."
fi

mkdir -p "$PYTHON_STANDALONE"
PYTHON_TARBALL=$(find "$PYTHON_STANDALONE" -maxdepth 1 -name "cpython-3.11.*-${TARGET}-install_only.tar.gz" -print -quit)

if [ -z "$PYTHON_TARBALL" ]; then
    echo "Downloading python-build-standalone..."
    FILENAME="cpython-${PYTHON_STANDALONE_VERSION}-${TARGET}-install_only.tar.gz"
    ENCODED_FILENAME="${FILENAME/+/%2B}"
    DOWNLOAD_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_STANDALONE_RELEASE}/${ENCODED_FILENAME}"
    curl -fL --retry 5 --retry-delay 2 -o "$PYTHON_STANDALONE/$FILENAME" "$DOWNLOAD_URL"
    PYTHON_TARBALL="$PYTHON_STANDALONE/$FILENAME"
fi
echo "Using Python: $PYTHON_TARBALL"

echo "Cleaning output and staging directories..."
rm -rf "$OUTPUT_DIR" "$STAGING_DIR"
mkdir -p "$OUTPUT_DIR" "$STAGING_DIR"

echo "Extracting portable Python..."
tar -xzf "$PYTHON_TARBALL" -C "$OUTPUT_DIR"
PYTHON_BIN="$OUTPUT_DIR/python/bin/python3"

echo "Exporting backend runtime requirements..."
cd "$BACKEND_SRC"
uv export --no-hashes --no-dev --no-emit-project > "$OUTPUT_DIR/requirements.txt"

echo "Installing backend dependencies into portable Python..."
uv pip install --python "$PYTHON_BIN" -r "$OUTPUT_DIR/requirements.txt"

# opencv-python-headless is pulled transitively today, but the packaged app
# deliberately does not ship cv2/codec dylibs. The runtime-surface guard below
# enforces that packaging rule.
SITE_PACKAGES="$OUTPUT_DIR/python/lib/python3.11/site-packages"
echo "Pruning cv2 and bundled codec libraries from portable Python..."
rm -rf "$SITE_PACKAGES/cv2"
rm -rf "$SITE_PACKAGES"/opencv_python_headless*.dist-info
rm -rf "$SITE_PACKAGES"/opencv_python_headless.libs
rm -rf "$SITE_PACKAGES"/opencv_python.libs
find "$SITE_PACKAGES" -type f \( \
    -name 'libavcodec*.so*' -o \
    -name 'libavformat*.so*' -o \
    -name 'libavdevice*.so*' -o \
    -name 'libavfilter*.so*' -o \
    -name 'libx264*.so*' -o \
    -name 'libx265*.so*' -o \
    -name 'libvpx*.so*' -o \
    -name 'libSvtAv1Enc*.so*' -o \
    -name 'librav1e*.so*' -o \
    -name 'libbluray*.so*' -o \
    -name 'libtheora*.so*' \
  \) -delete
if [ "$TARGET" = "x86_64-unknown-linux-gnu" ]; then
    echo "Pruning optional Tkinter runtime from Linux portable Python..."
    rm -rf "$OUTPUT_DIR/python/lib/python3.11/tkinter"
    rm -rf "$OUTPUT_DIR/python/lib/python3.11/idlelib"
    rm -f "$OUTPUT_DIR/python/lib/python3.11/turtle.py"
    rm -f "$OUTPUT_DIR/python/lib/python3.11/lib-dynload/_tkinter"*.so
fi
find "$SITE_PACKAGES" -type d \( -name '__pycache__' -o -name 'tests' -o -name 'test' \) -prune -exec rm -rf {} +
rm -rf "$SITE_PACKAGES/pip" "$SITE_PACKAGES"/pip-*.dist-info
rm -rf "$SITE_PACKAGES/setuptools" "$SITE_PACKAGES"/setuptools-*.dist-info
rm -rf "$SITE_PACKAGES/wheel" "$SITE_PACKAGES"/wheel-*.dist-info

echo "Copying backend source..."
rsync -a \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='dist' \
    --exclude='build' \
    --exclude='*.spec' \
    --exclude='*.egg-info' \
    --exclude='*.db' \
    --exclude='pyproject.toml' \
    --exclude='uv.lock' \
    --exclude='*-crash-report.xml' \
    --exclude='.claude' \
    --exclude='output' \
    --exclude='tests' \
    --exclude='tests_transition' \
    --exclude='agent/evals' \
    "$BACKEND_SRC/" "$STAGING_DIR/backend/"

rsync -a "$STAGING_DIR/backend/" "$OUTPUT_DIR/backend/"

echo "Copying app-level runtime files..."
cp "$PROJECT_ROOT/prompts.yaml" "$OUTPUT_DIR/"

# Build distribution baked into the launchers: 'dev' (default) or 'official'
# (set only by release CI). Runtime env still wins so the Tauri shell's
# compile-time value can override.
STIMMA_DISTRIBUTION_BAKED="${STIMMA_DISTRIBUTION:-dev}"
if [ "$STIMMA_DISTRIBUTION_BAKED" != "official" ]; then
    STIMMA_DISTRIBUTION_BAKED="dev"
fi
echo "Baking STIMMA_DISTRIBUTION=$STIMMA_DISTRIBUTION_BAKED into launchers..."

echo "Creating launchers..."
cat > "$OUTPUT_DIR/run.sh" << 'LAUNCHER'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
unset PYTHONHOME
export PYTHONUTF8=1
export PYTHONNOUSERSITE=1
export PYTHONPATH="$DIR:$DIR/backend"
export STIMMA_DISTRIBUTION="${STIMMA_DISTRIBUTION:-__STIMMA_DISTRIBUTION_BAKED__}"
exec "$DIR/python/bin/python3" "$DIR/backend/main.py" "$@"
LAUNCHER
sed -i.bak "s/__STIMMA_DISTRIBUTION_BAKED__/$STIMMA_DISTRIBUTION_BAKED/" "$OUTPUT_DIR/run.sh"
rm -f "$OUTPUT_DIR/run.sh.bak"
chmod +x "$OUTPUT_DIR/run.sh"

cat > "$OUTPUT_DIR/run.cmd" << 'LAUNCHER'
@echo off
setlocal
set PYTHONUTF8=1
set PYTHONPATH=%~dp0;%~dp0backend;%PYTHONPATH%
if not defined STIMMA_DISTRIBUTION set STIMMA_DISTRIBUTION=__STIMMA_DISTRIBUTION_BAKED__
"%~dp0python\python.exe" "%~dp0backend\main.py" %*
LAUNCHER
sed -i.bak "s/__STIMMA_DISTRIBUTION_BAKED__/$STIMMA_DISTRIBUTION_BAKED/" "$OUTPUT_DIR/run.cmd"
rm -f "$OUTPUT_DIR/run.cmd.bak"

"$SCRIPT_DIR/verify-portable-runtime-surface.sh" "$OUTPUT_DIR"

if [ "$(uname -s)" = "Darwin" ] && [ -d "$OUTPUT_DIR" ] && [ "${STIMMA_CODESIGN_NATIVE:-1}" = "1" ]; then
    if [ "${STRIP_BINARIES:-1}" = "1" ]; then
        echo "Stripping macOS native artifacts..."
        while IFS= read -r -d '' f; do
            if file "$f" | grep -q "Mach-O"; then
                strip -x "$f" 2>/dev/null || true
            fi
        done < <(find "$OUTPUT_DIR" -type f -print0)
    fi

    echo "Signing macOS native artifacts..."
    SIGN_ARGS=(--force --sign "-")
    if [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
        if security find-identity -v -p codesigning | grep -Fq "$APPLE_SIGNING_IDENTITY"; then
            SIGN_ARGS=(--force --sign "$APPLE_SIGNING_IDENTITY" --options runtime --timestamp)
        else
            echo "Apple signing identity is not available before Tauri signing; using ad-hoc signatures for backend native artifacts."
        fi
    fi

    while IFS= read -r -d '' f; do
        if file "$f" | grep -q "Mach-O"; then
            codesign "${SIGN_ARGS[@]}" "$f"
        fi
    done < <(find "$OUTPUT_DIR" -type f -print0)
fi

echo ""
echo "Portable backend build complete."
echo "Output: $OUTPUT_DIR"
du -sh "$OUTPUT_DIR"
