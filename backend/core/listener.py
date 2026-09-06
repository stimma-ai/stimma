"""The loopback port this backend actually bound.

The desktop shell starts the backend with ``--port 0``, so ``server.port`` in
config is only a preference. Anything that hands the address to something
outside the process (the MCP setup card, the stdio bridge) needs the real one,
and it has to survive ``reload_settings()``, which rebuilds the config object
from disk.
"""
from typing import Optional

_port: Optional[int] = None


def set_port(port: int) -> None:
    global _port
    _port = port


def port() -> int:
    if _port is not None:
        return _port
    from config import get_settings

    return get_settings().server.port
