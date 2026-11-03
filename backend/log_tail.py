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
import getpass
import re
import socket
from ipaddress import IPv6Address
from pathlib import Path
from typing import List, Optional

DEFAULT_TAIL_LINES = 200
MAX_TAIL_BYTES = 256 * 1024

# Secret-shaped patterns. Each replaces only the VALUE, keeping the key
# visible so the log stays readable.
_SECRET_PATTERNS = [
    re.compile(r'''(?i)\b(authorization)(["']?\s*[:=]\s*["']?)(?:(?:bearer|basic)\s+)?[^\s"',;]+'''),
    re.compile(r'''(?i)\b(api[_-]?key|(?:access[_-]|refresh[_-]|id[_-]|auth[_-])?token|(?:client[_-])?secret|password|passwd|pin)(["']?\s*[:=]\s*["']?)[^\s"',;&]+'''),
]

# Bare bearer-token-shaped strings (long base64url/JWT-looking blobs).
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b")
_BEARER_INLINE = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{16,}")
_PROVIDER_KEY = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|xox[baprs]-[A-Za-z0-9-]+|(?:AKIA|ASIA)[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{20,})\b")
_OPAQUE_SECRET = re.compile(r"\b[A-Za-z0-9_+/=-]{32,}\b")


def scrub_secrets(text: str) -> str:
    """Redact secrets and local identities before attaching diagnostics."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
    text = _BEARER_INLINE.sub(lambda m: f"{m.group(1)} [redacted]", text)
    text = _JWT_PATTERN.sub("[redacted-jwt]", text)
    text = _PROVIDER_KEY.sub("[redacted]", text)
    text = _OPAQUE_SECRET.sub("[redacted]", text)
    home = str(Path.home())
    for value in {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}:
        if value:
            text = re.sub(re.escape(value), "~", text, flags=re.IGNORECASE)
    text = re.sub(r'''(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\r\n"'<>]+''', "~", text)
    text = re.sub(r'''/(?:home|Users)/[^/\r\n"'<>]+''', "~", text)
    for value in (getpass.getuser(), socket.gethostname()):
        if value:
            text = re.sub(r"(?<!\w)" + re.escape(value) + r"(?!\w)", "[redacted]", text, flags=re.IGNORECASE)
    return text


def _scrub_ipv6(match: re.Match) -> str:
    try:
        IPv6Address(match[0])
    except ValueError:
        return match[0]
    return "[redacted]"


def scrub_shell_details(text: str) -> str:
    """Redact legacy device messages and remote addresses unknown to this backend."""
    text = re.sub(r"(Connected to ).+( via (?:lan|tailscale)) [^\r\n]+", r"\1[redacted]\2 [redacted]", text)
    text = re.sub(r"(Bootstrap refused by )(?!device [a-f0-9]{8}:).+(: \d{3})", r"\1[redacted]\2", text)
    text = re.sub(r"(Bootstrap failed for )(?!device [a-f0-9]{8}:)[^\r\n]+", r"\1[redacted]", text)
    text = re.sub(r"((?:Cached session|Session) rejected by )(?!device [a-f0-9]{8};).+(; re-bootstrapping)", r"\1[redacted]\2", text)
    text = re.sub(r"([a-z][a-z0-9+.-]*://)[^\s/?#\"'<>]+", r"\1[redacted]", text, flags=re.IGNORECASE)
    # Exclude file/line references and numeric versions, sizes and timestamps.
    text = re.sub(
        r"(?<![\w.:-])(?!(?:[\w.-]+\.)?(?:js|mjs|cjs|ts|tsx|json|py):)"
        r"(?:[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)*|(?:\d{1,3}\.){3}\d{1,3}|\[[a-f0-9:]+\]):\d{1,5}(?![\w.])",
        "[redacted]", text, flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(?:getaddrinfo\s+)?(?:ENOTFOUND|EAI_AGAIN)\s+[^\s\"'<>]+", "[redacted]", text)
    text = re.sub(
        r"(?<![\w.])(?:(?:10|127)(?:\.\d{1,3}){3}|(?:169\.254|192\.168|172\.(?:1[6-9]|2\d|3[01])|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7]))(?:\.\d{1,3}){2})(?![\w.])",
        "[redacted]", text,
    )
    text = re.sub(
        r"(?<![\w:])(?:[a-f0-9]{0,4}:){2,}[a-f0-9:]*(?:%[a-z0-9]+)?(?![\w:])",
        _scrub_ipv6,
        text, flags=re.IGNORECASE,
    )
    return re.sub(r"(?<![\w.-])(?:[a-z0-9_-]+\.)+(?:local|lan|internal|home|ts\.net)\b", "[redacted]", text, flags=re.IGNORECASE)


def get_log_dir() -> Path:
    """The rolling-log directory (``<data_dir>/Logs``)."""
    from app_dirs import get_data_dir
    return get_data_dir() / "Logs"


def tail_log_lines(
    n: int = DEFAULT_TAIL_LINES,
    log_dir: Optional[Path] = None,
    *,
    include_shell: bool = False,
) -> List[str]:
    """Up to ``n`` lines per source, oldest first within each, scrubbed.

    Each source spills into older rotations and reads at most MAX_TAIL_BYTES.
    Feedback attachments opt into shell logs; crash reports stay backend-only.
    """
    if n <= 0:
        return []
    directory = log_dir or get_log_dir()
    backend = _tail_files(
        [directory / f"Stimma_log.{index:02d}.txt" for index in range(20)], n,
    )
    shell = _tail_files(
        [directory / "Stimma-shell.log"]
        + [directory / f"Stimma-shell.log.{index}" for index in range(1, 5)], n, drop_first_line=True,
    ) if include_shell else []
    # Keep sources distinct rather than pretending their timestamps are sorted.
    lines = backend + (["[shell]"] + [scrub_shell_details(line) for line in shell] if shell else [])
    return [scrub_secrets(line) for line in lines]


def _tail_files(paths: List[Path], n: int, *, drop_first_line: bool = False) -> List[str]:
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
            # Old shell rotations can start mid-record even without seeking.
            if start or drop_first_line:
                data = data.partition(b"\n")[2]
            lines = data.decode("utf-8", errors="replace").splitlines()
        except OSError:
            break
        needed = n - len(collected)
        collected = lines[-needed:] + collected
    return collected[-n:]


def tail_log_text(
    n: int = DEFAULT_TAIL_LINES, log_dir: Optional[Path] = None, *, include_shell: bool = False,
) -> str:
    """The scrubbed log tail as one string (for logs.txt uploads)."""
    return "\n".join(tail_log_lines(n, log_dir=log_dir, include_shell=include_shell))
