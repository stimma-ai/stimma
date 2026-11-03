"""
Log tail + secret scrubber for feedback and crash reports.

Tails the last N lines of each rolling backend and shell log
(``<data_dir>/Logs/Stimma_log.00.txt``, spilling into ``.01`` when the
current file is short — see core/logging.py for the rotation scheme) and
scrubs secret-shaped values before anything leaves the machine.

Scrubbing is value-shaped and word-boundary based: ``Authorization: …``
headers, ``api_key=…`` / ``api-key: …`` assignments, ``token=…``
assignments, and bearer-token-shaped strings. A naive ``token`` substring
match would mangle every LLM token-count log line, so only *assignments*
of secret-named keys are redacted, never the words themselves.
"""
import re
from pathlib import Path
from typing import List, Optional

DEFAULT_TAIL_LINES = 200
MAX_TAIL_BYTES = 256 * 1024

# Secret-shaped patterns. Each replaces only the VALUE, keeping the key
# visible so the log stays readable.
_SECRET_PATTERNS = [
    # Authorization: Bearer xxxx / Authorization=xxxx
    re.compile(r"(?i)\b(authorization)(\s*[:=]\s*)(\"?)(?:bearer\s+)?[^\s\"',;]+", ),
    # api_key / api-key / apikey (json, yaml, query, env styles)
    re.compile(r"(?i)\b(api[_-]?key)(\s*[:=]\s*)(\"?)[^\s\"',;&]+"),
    # token / access_token / refresh_token / id_token ASSIGNMENTS only
    re.compile(r"(?i)\b((?:access[_-]|refresh[_-]|id[_-]|auth[_-])?token)(\s*[:=]\s*)(\"?)[^\s\"',;&]+"),
    # secret / client_secret assignments
    re.compile(r"(?i)\b((?:client[_-])?secret)(\s*[:=]\s*)(\"?)[^\s\"',;&]+"),
    # password assignments
    re.compile(r"(?i)\b(password|passwd)(\s*[:=]\s*)(\"?)[^\s\"',;&]+"),
]

# Bare bearer-token-shaped strings (long base64url/JWT-looking blobs).
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b")
_BEARER_INLINE = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{16,}")


def scrub_secrets(text: str) -> str:
    """Redact secret-shaped values from log text (keys stay visible)."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}[redacted]", text)
    text = _BEARER_INLINE.sub(lambda m: f"{m.group(1)} [redacted]", text)
    text = _JWT_PATTERN.sub("[redacted-jwt]", text)
    return text


def get_log_dir() -> Path:
    """The rolling-log directory (``<data_dir>/Logs``)."""
    from app_dirs import get_data_dir
    return get_data_dir() / "Logs"


def tail_log_lines(
    n: int = DEFAULT_TAIL_LINES,
    log_dir: Optional[Path] = None,
) -> List[str]:
    """Up to ``n`` lines per source, oldest first within each, scrubbed.

    Each source spills into older rotations and reads at most MAX_TAIL_BYTES.
    Both feedback attachments and crash reports use this same consent-gated tail.
    """
    if n <= 0:
        return []
    directory = log_dir or get_log_dir()
    backend = _tail_files(
        [directory / f"Stimma_log.{index:02d}.txt" for index in range(20)], n,
    )
    shell = _tail_files(
        [directory / "Stimma-shell.log"]
        + [directory / f"Stimma-shell.log.{index}" for index in range(1, 5)], n,
    )
    # Keep sources distinct rather than pretending their timestamps are sorted.
    lines = backend + (["[shell]"] + shell if shell else [])
    return [scrub_secrets(line) for line in lines]


def _tail_files(paths: List[Path], n: int) -> List[str]:
    collected: List[str] = []
    budget = MAX_TAIL_BYTES
    for path in paths:
        if len(collected) >= n or budget <= 0:
            break
        try:
            with path.open("rb") as file:
                size = file.seek(0, 2)
                start = max(0, size - budget)
                file.seek(start)
                data = file.read(budget)
            budget -= len(data)
            # Avoid attaching a partial first line after seeking into a file.
            if start and b"\n" in data:
                data = data.split(b"\n", 1)[1]
            lines = data.decode("utf-8", errors="replace").splitlines()
        except OSError:
            break
        needed = n - len(collected)
        collected = lines[-needed:] + collected
    return collected[-n:]


def tail_log_text(n: int = DEFAULT_TAIL_LINES, log_dir: Optional[Path] = None) -> str:
    """The scrubbed log tail as one string (for logs.txt uploads)."""
    return "\n".join(tail_log_lines(n, log_dir=log_dir))
