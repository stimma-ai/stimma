"""End-of-turn signal.

`finish` is the explicit way for the agent to hand control back to the user.
It is pure control flow — the loop special-cases it and never persists a
tool_call/tool_result pair for it (an unmatched tool_call would corrupt the
next turn's reconstructed message history). It carries no text: the model's
normal assistant message is its closing remark, so a bare `finish` after a
`show` is the clean "no narration" ending.

Having an explicit terminal act means a text-only message no longer silently
ends the turn mid-task — the loop keeps the agent working until it either
calls `finish` or genuinely stalls. See `_run_agentic_loop`.
"""

from ..tools_registry import tool


@tool(
    name="finish",
    description=(
        "End your turn and hand control back to the user. Call this when the "
        "task is complete, or when you need the user to respond and have "
        "nothing left to do. Put any closing remark in your message — `finish` "
        "itself carries no text. Until you call it, a message without a tool "
        "call does not hand control back; keep working."
    ),
    parameters=[],
    scope="both",
)
async def finish(**kwargs) -> str:
    # Never actually executed — the agent loop intercepts `finish` as control
    # flow before tool dispatch. Defined so the schema is exposed and name
    # resolution succeeds.
    return ""
