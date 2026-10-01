"""Tool implementations load individually; agent catalogs register on demand."""

from importlib import import_module

_BUILTIN_MODULES = (
    "ask_user",
    "finish",
    "bash",
    "browse_web",
    "discover",
    "call_tool",
    "view_image",
    "show",
    "library",
    "media_info",
    "run_code",
    "run_file",
    "create_layout",
    "create_svg",
    "skill",
    "delegate",
    "assemble_grid",
    "assemble_set",
    "sdk_help",
    "notepad",
    "preprocess_controlnet",
    "save_memory",
    "write_file",
    "read_file",
    "edit_file",
    "glob_files",
    "grep_files",
    "flow_update",
    "analyze_flow",
    "share_files",
)
_registered = False


def register_builtin_tools():
    """Register the full catalog only when agent execution requests it."""
    global _registered
    if _registered:
        return
    # Individual tool modules can query the registry while this import runs.
    _registered = True
    try:
        for name in _BUILTIN_MODULES:
            import_module(f"{__name__}.{name}")
    except Exception:
        _registered = False
        raise
