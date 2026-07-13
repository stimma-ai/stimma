"""Execute sandboxed Python in the session workspace."""

from ..code_runtime import ALLOWED_MODULES_PROMPT_DESCRIPTION, run_code_in_sandbox
from ..tools_registry import tool, ToolParameter


@tool(
    name="run_code",
    description=(
        "Execute Python code in a restricted workspace sandbox with a pre-injected `stimma` SDK. "
        "Code already runs inside `async def` — use `await` directly at the top level. Do NOT wrap in `async def main()` or use `asyncio.run()`. "
        "`stimma` is already available — no import needed (it has .show, .library, .llm, etc.). "
        "Generation/transformation tools are imported by their REAL name from the catalog: read .stimma/tools/<category>/ first "
        "(ls/cat) to get the exact function name, then `from stimma.tools.<category> import <name_from_catalog>` "
        "and `r = await <name_from_catalog>(...)` — the awaited result is a ToolResult (.media_id, .path, .seed). "
        "When generating multiple images, ALWAYS use asyncio.gather() to run them in parallel — this enables the progress display and is significantly faster. "
        "Batch: import the tool once, then `results = await asyncio.gather(*[<tool>(prompt=p) for p in prompts]); stimma.show(results, role='final')` "
        "If run_code already called stimma.show(), do NOT call the show tool again afterward — images are already visible. "
        + ALLOWED_MODULES_PROMPT_DESCRIPTION
        + " Invoked skills may provide additional importable modules — check the skills inventory."
    ),
    parameters=[
        ToolParameter(name="code", type="string", description="Python code to execute"),
        ToolParameter(
            name="label",
            type="string",
            description=(
                "A few words in present-progressive naming what this code does, shown to the "
                'user while it runs (e.g. "Generating image", "Upscaling", "Building grid").'
            ),
            required=False,
        ),
    ],
)
async def run_code(code: str, **kwargs) -> str:
    workspace_dir = kwargs.get("workspace_dir")
    session = kwargs.get("session")
    chat_id = kwargs.get("chat_id")

    if not workspace_dir:
        return "Error: no workspace directory available"
    if not session:
        return "Error: No database session available"
    if chat_id is None:
        return "Error: No chat available"

    result, llm_usage = await run_code_in_sandbox(
        code=code,
        session=session,
        chat_id=chat_id,
        workspace_dir=workspace_dir,
        project_workspace_dir=kwargs.get("project_workspace_dir"),
        interrupt_checker=kwargs.get("interrupt_checker"),
        session_media_ids=kwargs.get("session_media_ids"),
        shown_media_ids=kwargs.get("_shown_media_ids"),
        enabled_stimpacks=kwargs.get("_enabled_stimpacks"),
        project_id=kwargs.get("project_id"),
        effective_model_slug=kwargs.get("_effective_model_slug"),
    )
    # Stash usage on the mutable container so _execute_tool_call can read it
    usage_out = kwargs.get("_llm_usage_out")
    if usage_out is not None and llm_usage and llm_usage.get("calls", 0) > 0:
        usage_out["llm_usage"] = llm_usage
    return result
