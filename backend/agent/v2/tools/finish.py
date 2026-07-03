"""End-of-turn signal.

`finish` is an optional explicit way for the agent to hand control back to
the user. It is pure control flow — the loop special-cases it and never
persists a tool_call/tool_result pair for it (an unmatched tool_call would
corrupt the next turn's reconstructed message history). It carries no text:
the model's normal assistant message is its closing remark, so a bare
`finish` after a `show` is the clean "no narration" ending.

It is not required to end a turn: a response with no tool calls is the
model's native end of turn and the loop accepts it whenever the user got a
visible reply. `finish` exists for the silent ending — nothing left to say,
just hand back. See `_run_agentic_loop`.
"""

from ..tools_registry import tool


@tool(
    name="finish",
    description=(
        "Silently hand the conversation back to the user with no message. "
        "Ending a normal message with no tool calls also hands back — use "
        "`finish` only when you have nothing left to say, e.g. right after "
        "`show` when the images speak for themselves. The user never sees "
        "this call, so never announce that you're finishing."
    ),
    parameters=[],
    scope="both",
)
async def finish(**kwargs) -> str:
    # Never actually executed — the agent loop intercepts `finish` as control
    # flow before tool dispatch. Defined so the schema is exposed and name
    # resolution succeeds.
    return ""
