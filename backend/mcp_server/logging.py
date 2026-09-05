"""Keep SDK diagnostics categorical: SDK debug reprs can contain access_open PINs."""

import logging


class TransportLogFilter(logging.Filter):
    def filter(self, record):
        record.msg = "MCP transport event (%s)"
        record.args = (record.levelname,)
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def protect_sdk_logs():
    for name in list(logging.Logger.manager.loggerDict):
        if name == "mcp" or name.startswith("mcp."):
            logger = logging.getLogger(name)
            if not any(isinstance(f, TransportLogFilter) for f in logger.filters):
                logger.addFilter(TransportLogFilter())
