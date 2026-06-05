"""Structured logging configuration using structlog."""
import logging
import os
import sys
import structlog
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Track if we've already set up logging
_logging_configured = False
_file_handler = None


class StimmaRotatingFileHandler(RotatingFileHandler):
    """
    Custom rotating file handler that uses Stimma_log.00.txt naming convention.
    00 is always the current/latest log, 01 is the previous, etc.
    """

    def __init__(self, log_dir: Path, max_bytes: int = 4*1024*1024, backup_count: int = 20):
        self.log_dir = log_dir
        self.backup_count = backup_count
        self.base_filename = "Stimma_log"

        # Ensure log directory exists
        log_dir.mkdir(parents=True, exist_ok=True)

        # Current log file is always .00.txt
        current_log = log_dir / f"{self.base_filename}.00.txt"
        super().__init__(
            str(current_log),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )

    def doRollover(self):
        """
        Do a rollover, renaming files in reverse order.
        Stimma_log.00.txt -> Stimma_log.01.txt -> ... -> Stimma_log.19.txt (deleted)
        """
        if self.stream:
            self.stream.close()
            self.stream = None

        # Delete the oldest file if it exists
        oldest = self.log_dir / f"{self.base_filename}.{self.backup_count - 1:02d}.txt"
        if oldest.exists():
            oldest.unlink()

        # Rotate all files: .18 -> .19, .17 -> .18, ..., .00 -> .01
        for i in range(self.backup_count - 2, -1, -1):
            src = self.log_dir / f"{self.base_filename}.{i:02d}.txt"
            dst = self.log_dir / f"{self.base_filename}.{i + 1:02d}.txt"
            if src.exists():
                src.rename(dst)

        # Open a new .00.txt file
        self.mode = 'w'
        self.stream = self._open()


def setup_logging(log_level: str = "INFO", log_dir: Path = None) -> None:
    """
    Configure structlog for the application.

    Sets up structlog with:
    - Console output with colors and readable formatting
    - Rolling file output (20 files, 4MB each)
    - Automatic context binding (request_id, etc.)
    - Integration with standard library logging
    - Uncaught exception logging

    ALL Python loggers (including alembic, uvicorn, etc.) are routed
    through structlog for consistent formatting.
    """
    global _logging_configured, _file_handler

    # Shared processors for both structlog and stdlib logging
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
        structlog.stdlib.ExtraAdder(),
    ]

    # Configure structlog
    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Create formatters for stdout (with colors) and file (plain text)
    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
    )

    file_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=False),  # No ANSI codes in file
        ],
    )

    # Configure root logger - this captures EVERYTHING
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove ALL existing handlers from root and all known loggers
    # This prevents duplicate output and ensures our format is used
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add console handler (stderr)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)

    # Add file handler if log_dir is specified
    if log_dir:
        try:
            logs_dir = log_dir / "Logs"
            _file_handler = StimmaRotatingFileHandler(
                log_dir=logs_dir,
                max_bytes=4 * 1024 * 1024,  # 4MB
                backup_count=20
            )
            _file_handler.setFormatter(file_formatter)
            _file_handler.setLevel(logging.DEBUG)
            root_logger.addHandler(_file_handler)

            # Log startup marker
            root_logger.info("=" * 60)
            root_logger.info("STIMMA BACKEND STARTING")
            root_logger.info(f"Log directory: {logs_dir}")
            root_logger.info("=" * 60)
        except Exception as e:
            root_logger.warning(f"Failed to set up file logging: {e}")

    # Set up uncaught exception handler
    def exception_handler(exc_type, exc_value, exc_traceback):
        """Log uncaught exceptions."""
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        # Always dump via stdlib first so a formatter blow-up downstream
        # (structlog/rich) can never hide the real exception.
        import traceback
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)
        root_logger.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback)
        )

    sys.excepthook = exception_handler

    # Reconfigure known noisy loggers
    _configure_log_levels()

    _logging_configured = True


def _configure_log_levels():
    """Set appropriate log levels for various libraries."""
    # Quiet down noisy loggers
    quiet_loggers = [
        "httpcore", "httpx", "urllib3", "asyncio", "aiosqlite",
        "websockets", "watchfiles",
        # Suppress litellm's own logging - we handle it ourselves
        "LiteLLM", "litellm",
    ]
    for name in quiet_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Alembic should use INFO (we want to see migration output)
    logging.getLogger("alembic").setLevel(logging.INFO)

    # Uvicorn loggers - keep uvicorn.error for startup/shutdown, quiet access
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("uvicorn").setLevel(logging.INFO)


def reconfigure_logging():
    """
    Reconfigure logging after something else (like alembic) has messed with it.

    Call this after any operation that might call logging.config.fileConfig()
    or otherwise reconfigure the logging system.
    """
    global _logging_configured
    _logging_configured = False
    setup_logging()


def get_logger(name: str = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structlog logger.

    Usage:
        from core.logging import get_logger
        log = get_logger(__name__)
        log.info("something happened", user_id=123)
    """
    # Ensure logging is configured
    if not _logging_configured:
        setup_logging()
    return structlog.get_logger(name)
