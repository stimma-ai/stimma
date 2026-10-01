"""Agent execution entry points, loaded when a chat actually uses them."""

__all__ = ["run_agent", "interrupt_execution"]


def __getattr__(name):
    if name in __all__:
        from . import service
        return getattr(service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
