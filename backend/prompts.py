"""
Hot-reloading prompt loader - re-reads prompts.yaml on every access when the file changes.
"""
import yaml
from pathlib import Path


def _get_prompts_file() -> Path:
    """Get the path to prompts.yaml - in project root (parent of backend/)."""
    return Path(__file__).parent.parent / "prompts.yaml"


_prompts_file = _get_prompts_file()
_last_mtime: float = 0
_cached_prompts: dict = None


def _load_prompts() -> dict:
    """Load prompts from YAML file, reloading if file has changed."""
    global _last_mtime, _cached_prompts

    current_mtime = _prompts_file.stat().st_mtime
    if _cached_prompts is None or current_mtime != _last_mtime:
        # Force UTF-8 to avoid locale-dependent defaults (e.g. ascii in frozen builds).
        with open(_prompts_file, "r", encoding="utf-8") as f:
            _cached_prompts = yaml.safe_load(f)
        _last_mtime = current_mtime

    return _cached_prompts


def get_prompt(section: str, key: str = "prompt") -> str:
    """
    Get a prompt by section and key, re-reading from disk if file changed.

    Args:
        section: Top-level key in prompts.yaml (e.g., "captioning", "agent")
        key: Key within the section (default "prompt", or e.g., "system_prompt")

    Returns:
        The prompt string, or empty string if not found.

    Examples:
        get_prompt("captioning")  # Gets captioning.prompt
        get_prompt("agent", "system_prompt")  # Gets agent.system_prompt
        get_prompt("prompt_enhancement", "improve_system_prompt")
    """
    prompts = _load_prompts()
    return prompts.get(section, {}).get(key, "")
