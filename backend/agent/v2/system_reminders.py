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

from .stimpacks import SkillInfo


def build_skills_reminder(
    all_skills: List[SkillInfo],
    invoked_skills: Set[str],
    environment: str = "chat",
) -> Optional[str]:
    """Build a system reminder listing skills eligible in this environment.

    ``environment`` is "chat" or "flow" — a skill appears only when its
    frontmatter opts into that surface. Skills already invoked in this
    conversation are omitted. Returns None when nothing is available.
    """
    eligible = [s for s in all_skills if getattr(s.environments, environment, False)]
    available = [
        s for s in eligible
        if s.qualified_name not in invoked_skills
        and s.slug not in invoked_skills
        and s.pack_name not in invoked_skills  # legacy: invoked by pack name
    ]
    if not available:
        return None

    lines = ["<system-reminder>", "Skills available if useful:", ""]
    for s in available:
        desc = s.description
        if s.provides:
            desc += f" (imports: {', '.join(s.provides)})"
        lines.append(f"- {s.qualified_name}: {desc} [{s.pack_display_name}]")
    lines.append("")
    lines.append(
        "Invoke a skill only when the task actually calls for it — being listed "
        "here means it's available, not that it applies. When skills do apply, "
        "load them all up front, before starting work: loading a skill mid-task "
        "injects new instructions that can reset your focus and cause you to "
        "redo completed steps."
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
