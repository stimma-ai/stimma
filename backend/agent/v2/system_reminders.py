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

from sqlalchemy.ext.asyncio import AsyncSession

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
    if environment == "flow":
        # Flow builds are mostly plumbing; the historical failure mode was
        # loading skills into flows that didn't call for them. Chat keeps the
        # unhedged load-up-front instruction below.
        lines.append(
            "Invoke a skill only when the task actually calls for it — being "
            "listed here means it's available, not that it applies. When skills "
            "do apply, load them all up front, before starting work: loading a "
            "skill mid-task injects new instructions that can reset your focus "
            "and cause you to redo completed steps."
        )
    else:
        lines.append(
            "Load every skill that clearly applies up front, before starting "
            "work — loading a skill mid-task injects new instructions that can "
            "reset your focus and cause you to redo completed steps."
        )
    lines.append("</system-reminder>")
    return "\n".join(lines)


async def build_artifact_context_reminder(
    session: AsyncSession,
    artifact_context: Optional[dict],
) -> Optional[str]:
    """Tell the agent which artifact revision the user is currently looking at.

    ``artifact_context`` comes from the chat send-message payload as
    ``{asset_id, revision_id, revision_number}``. Silent (returns None) when
    the user is viewing the current revision — nothing to say — or the
    revision no longer exists.
    """
    if not artifact_context:
        return None
    asset_id = artifact_context.get("asset_id")
    revision_id = artifact_context.get("revision_id")
    revision_number = artifact_context.get("revision_number")
    if not asset_id or not revision_id:
        return None

    from database import Asset

    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None:
        return None
    if asset.current_revision_id == revision_id:
        return None

    return (
        "<system-reminder>\n"
        f"The user is currently viewing revision {revision_number} (revision_id={revision_id}) "
        f"of asset {asset_id}, not its latest version. If they ask for changes, commit the "
        f"result with revises={asset_id} and parent_revision={revision_id} so the new revision "
        "branches from what they're looking at.\n"
        "</system-reminder>"
    )


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
