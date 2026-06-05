#!/bin/bash
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <runtime bundle path>"
    exit 1
fi

BUNDLE_DIR="$1"
if [ ! -d "$BUNDLE_DIR" ]; then
    echo "ERROR: runtime bundle not found: $BUNDLE_DIR"
    exit 1
fi

# Commercial-safe default: fail builds if cv2 or codec-heavy ffmpeg dylibs are bundled.
if [ "${STIMMA_ALLOW_RESTRICTED_CODECS:-0}" = "1" ]; then
    echo "Runtime surface guard disabled (STIMMA_ALLOW_RESTRICTED_CODECS=1)"
    exit 0
fi

declare -a banned_globs=(
    "libavcodec*.dylib"
    "libavcodec*.so*"
    "libavformat*.dylib"
    "libavformat*.so*"
    "libavdevice*.dylib"
    "libavdevice*.so*"
    "libavfilter*.dylib"
    "libavfilter*.so*"
    "libx264*.dylib"
    "libx264*.so*"
    "libx265*.dylib"
    "libx265*.so*"
    "libvpx*.dylib"
    "libvpx*.so*"
    "libSvtAv1Enc*.dylib"
    "libSvtAv1Enc*.so*"
    "librav1e*.dylib"
    "librav1e*.so*"
    "libbluray*.dylib"
    "libbluray*.so*"
    "libtheora*.dylib"
    "libtheora*.so*"
)

declare -a hits=()
for pat in "${banned_globs[@]}"; do
    while IFS= read -r -d '' p; do
        hits+=("$(basename "$p")")
    done < <(find "$BUNDLE_DIR" -type f -name "$pat" -print0)
done

while IFS= read -r -d '' p; do
    hits+=("$(basename "$p")")
done < <(find "$BUNDLE_DIR" -type f \( -path "*/cv2/*" -o -name "cv2*.so" -o -name "cv2*.dylib" \) -print0)

if [ ${#hits[@]} -gt 0 ]; then
    echo "ERROR: runtime bundle includes disallowed media/codec artifacts:"
    printf '  %s\n' "${hits[@]}" | sort -u
    echo "Set STIMMA_ALLOW_RESTRICTED_CODECS=1 only for temporary debugging builds."
    exit 1
fi

echo "Runtime surface check passed: no banned codec/cv2 artifacts found."
