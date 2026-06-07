"""Execute a workspace Python file in the run_code sandbox.

Two execution paths, same runtime: run_code for ephemeral one-liners and
exploration (nothing persists), run_file for substantial, reusable scripts you
authored with write_file. Both run in-process with the live `stimma` SDK and the
`from stimma.tools.<task> import <tool>` namespace injected — a bash subprocess
would have neither.
"""

from ..code_runtime import run_code_in_sandbox
from ..tools_registry import tool, ToolParameter
from ._workspace_files import resolve_workspace_path


@tool(
    name="run_file",
    description=(
        "Execute a Python file from the workspace in the same sandbox as run_code: "
        "the `stimma` SDK is pre-injected and tools are callable via "
        "`from stimma.tools.<task> import <tool>` (browse them under .stimma/tools/). "
        "Use run_file for substantial or reusable logic you wrote with write_file; use "
        "run_code for quick one-liners so the workspace doesn't fill with throwaway scripts. "
        "The file runs inside `async def` — use `await` at the top level, no asyncio.run()."
    ),
    parameters=[
        ToolParameter(
            name="file_path",
            type="string",
            description="Workspace-relative path to a .py file to execute",
        ),
    ],
    scope="agent",
)
async def run_file(file_path: str, **kwargs) -> str:
    workspace_dir = kwargs.get("workspace_dir")
    session = kwargs.get("session")
    chat_id = kwargs.get("chat_id")

    if not workspace_dir:
        return "Error: no workspace directory available"
    if not session:
        return "Error: No database session available"
    if chat_id is None:
        return "Error: No chat available"
    if not file_path:
        return "Error: file_path is required"

    resolved, err = resolve_workspace_path(str(workspace_dir), file_path)
    if err:
        return err
    if not resolved.exists() or not resolved.is_file():
        return f"Error: file not found: {file_path}. Write it with write_file first."
    try:
        code = resolved.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading {file_path}: {e}"

    result, llm_usage = await run_code_in_sandbox(
        code=code,
        session=session,
        chat_id=chat_id,
        workspace_dir=workspace_dir,
        project_workspace_dir=kwargs.get("project_workspace_dir"),
        interrupt_checker=kwargs.get("interrupt_checker"),
        session_media_ids=kwargs.get("session_media_ids"),
        shown_media_ids=kwargs.get("_shown_media_ids"),
        enabled_skills=kwargs.get("_enabled_skills"),
        project_id=kwargs.get("project_id"),
        effective_model_slug=kwargs.get("_effective_model_slug"),
    )
    usage_out = kwargs.get("_llm_usage_out")
    if usage_out is not None and llm_usage and llm_usage.get("calls", 0) > 0:
        usage_out["llm_usage"] = llm_usage
    return result
