"""System reminder providers for the agent loop.

System reminders are runtime-injected, system-authored messages that become
model-visible conversation context. They are injected into the last user
message (wrapped in <system-reminder> tags) rather than the system prompt,
keeping the prompt prefix stable for caching.

Each provider is a function that returns a list of reminder strings (already
wrapped in tags). The agent loop collects reminders from all providers and
passes them to build_messages().
"""

from typing import List, Optional, Set

from .skills import SkillInfo


def build_skills_reminder(
    all_skills: List[SkillInfo],
    invoked_skills: Set[str],
) -> Optional[str]:
    """Build a system reminder listing available skills.

    Only includes skills that haven't already been invoked in this conversation.
    Returns None if no skills are available or all have been invoked.
    """
    available = [s for s in all_skills if s.name not in invoked_skills]
    if not available:
        return None

    lines = ["<system-reminder>", "Skills available if useful:", ""]
    for s in available:
        desc = s.description
        if s.provides:
            desc += f" (imports: {', '.join(s.provides)})"
        lines.append(f"- {s.name}: {desc}")
    lines.append("")
    lines.append(
        "Load every skill that clearly applies up front, before starting work — "
        "loading a skill mid-task injects new instructions that can reset your focus "
        "and cause you to redo completed steps."
    )
    lines.append("</system-reminder>")
    return "\n".join(lines)


def build_user_program_edit_reminder(flow_id: int) -> Optional[str]:
    """Notify the agent that the user just edited program.py out-of-band.

    Consumes a one-shot marker file: returns a reminder the first time it sees
    one, and clears it. Subsequent turns see no reminder until the user edits
    again.
    """
    from flow_runtime import consume_user_program_edit_marker

    if not consume_user_program_edit_marker(flow_id):
        return None

    return (
        "<system-reminder>\n"
        "The user just saved an edit to program.py from the flow code view. "
        "Your in-context view of the file is stale. Re-read program.py "
        "before making any further edits to it; otherwise edit_file matches "
        "may fail or you may overwrite the user's changes.\n"
        "</system-reminder>"
    )
