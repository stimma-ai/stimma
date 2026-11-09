#!/usr/bin/env bash
set -euo pipefail

# Versioned upstream archive; never use the moving release/latest URL.
VERSION=7.0.2
SHA256=abda8d77ce8309141f83ab8edf0596834087c52467f6badf376a6a2a4c87cf67
BUILD="ffmpeg-${VERSION}-amd64-static"
CACHE_KEY="${BUILD}-${SHA256}"
CACHE_DIR="${HOME}/.cache/stimma-ci-ffmpeg/${CACHE_KEY}"

# The action uses the same pin for the download, directory and exact cache key.
if [ "${1:-}" = --cache-metadata ]; then
  printf 'key=%s\npath=%s\n' "$CACHE_KEY" "$CACHE_DIR"
  exit 0
fi

usable() {
  "$1/ffmpeg" -version >/dev/null 2>&1 && "$1/ffprobe" -version >/dev/null 2>&1
}

activate() {
  export PATH="$CACHE_DIR:$PATH"
  if [ -n "${GITHUB_PATH:-}" ]; then printf '%s\n' "$CACHE_DIR" >> "$GITHUB_PATH"; fi
}

install_static() (
  set -e
  scratch=$(mktemp -d)
  trap 'rm -rf "$scratch"' EXIT
  curl --fail --location --silent --show-error --connect-timeout 10 --max-time 60 \
    --output "$scratch/ffmpeg.tar.xz" \
    "https://johnvansickle.com/ffmpeg/releases/${BUILD}.tar.xz"
  printf '%s  %s\n' "$SHA256" "$scratch/ffmpeg.tar.xz" | sha256sum --check --status
  tar -xJf "$scratch/ffmpeg.tar.xz" -C "$scratch" \
    "$BUILD/ffmpeg" "$BUILD/ffprobe" "$BUILD/GPLv3.txt"
  usable "$scratch/$BUILD"
  mkdir -p "$CACHE_DIR"
  cp "$scratch/$BUILD/ffmpeg" "$scratch/$BUILD/ffprobe" "$scratch/$BUILD/GPLv3.txt" "$CACHE_DIR/"
)

# Keep preprovisioned runners on their existing toolchain. Hosted runners use
# the pinned build even if their image happens to contain another version.
if [ "${RUNNER_ENVIRONMENT:-}" != github-hosted ] && \
    ffmpeg -version >/dev/null 2>&1 && ffprobe -version >/dev/null 2>&1; then
  echo 'Using preinstalled FFmpeg and ffprobe'
elif [ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ]; then
  if ! usable "$CACHE_DIR"; then
    # Run with errexit enabled outside an if/|| context: a checksum or extraction
    # failure must stop the subshell before any binary is executed or cached.
    set +e
    install_static
    static_status=$?
    set -e
    if [ "$static_status" -ne 0 ]; then
      rm -rf "$CACHE_DIR"
      echo '::warning::Pinned FFmpeg unavailable; using system FFmpeg or apt fallback'
    fi
  fi
  if usable "$CACHE_DIR"; then activate; fi
fi

if ! ffmpeg -version >/dev/null 2>&1 || ! ffprobe -version >/dev/null 2>&1; then
  SUDO=()
  if [ "$(id -u)" -ne 0 ]; then SUDO=(sudo); fi

  # The hosted Azure mirror has delivered FFmpeg at 36 kB/s for 25 minutes.
  # Use Ubuntu's signed archive directly, including when apt uses mirror lists.
  # Leave custom/self-hosted package sources alone.
  if [ "${RUNNER_ENVIRONMENT:-}" = github-hosted ]; then
    mapfile -t SOURCES < <(find /etc/apt -maxdepth 2 -type f \
      \( -name '*.list' -o -name '*.sources' -o -name '*mirrors.txt' \))
    if [ "${#SOURCES[@]}" -gt 0 ]; then
      "${SUDO[@]}" sed -i -E \
        's|https?://azure\.archive\.ubuntu\.com/ubuntu|http://archive.ubuntu.com/ubuntu|g' \
        "${SOURCES[@]}"
    fi
    # Playwright's subsequent apt install uses these bounds too.
    "${SUDO[@]}" bash -c 'printf "%s\n" "Acquire::Retries \"1\";" "Acquire::http::Timeout \"15\";" "Acquire::https::Timeout \"15\";" > /etc/apt/apt.conf.d/99-stimma-ci'
  fi

  APT=(-o Acquire::Retries=1 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15)
  "${SUDO[@]}" apt-get "${APT[@]}" update
  "${SUDO[@]}" apt-get "${APT[@]}" install -y --no-install-recommends ffmpeg
fi
ffmpeg -version
ffprobe -version
