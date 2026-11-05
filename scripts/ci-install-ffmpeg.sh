#!/usr/bin/env bash
set -euo pipefail

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

if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  APT=(-o Acquire::Retries=1 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15)
  "${SUDO[@]}" apt-get "${APT[@]}" update
  "${SUDO[@]}" apt-get "${APT[@]}" install -y --no-install-recommends ffmpeg
fi
ffmpeg -version
ffprobe -version
