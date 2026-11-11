"""Execute sandboxed Python in the session workspace."""

import asyncio
import time

from ..code_runtime import ALLOWED_MODULES_PROMPT_DESCRIPTION, run_code_in_sandbox
from ..tools_registry import tool, ToolParameter


@tool(
    name="run_code",
    description=(
        "Execute Python code in a restricted workspace sandbox with a pre-injected `stimma` SDK. "
        "Each call has a fresh Python scope: persist work in files/scripts, not variables from a previous call. "
        "Code already runs inside `async def` — use `await` directly at the top level. Do NOT wrap in `async def main()` or use `asyncio.run()`. "
        "`stimma` is already available — no import needed (it has .show, .library, .llm, etc.). "
        "Generation/transformation tools are imported by their REAL name from the catalog: read .stimma/tools/<category>/ first "
        "with glob/read_file to get the exact function name, then `from stimma.tools.<category> import <name_from_catalog>` "
        "and `r = await <name_from_catalog>(...)` — the awaited result is a ToolResult (.media_id, .path, .seed). "
        "Submit all independent generations for the requested job together in one asyncio.gather(). "
        "Let the runtime and provider manage concurrency so available GPUs stay busy. "
        "Wait between generations only when later work depends on earlier results. "
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
        ToolParameter(
            name="background",
            type="boolean",
            description=(
                "Run this code in the background: the call returns a task id right away and you "
                "get a notification with the receipt when it finishes. For long work such as video "
                "or large batches, so you can keep talking with the user meanwhile."
            ),
            required=False,
        ),
    ],
)
async def run_code(code: str, background: bool = False, **kwargs) -> str:
    workspace_dir = kwargs.get("workspace_dir")
    session = kwargs.get("session")
    chat_id = kwargs.get("chat_id")

    if not workspace_dir:
        return "Error: no workspace directory available"
    if not session:
        return "Error: No database session available"
    if chat_id is None:
        return "Error: No chat available"
    background = background is True or str(background).lower() == "true"
    return await run_code_detachable(code, background=background, **kwargs)


async def run_code_detachable(code: str, *, background: bool = False, **kwargs) -> str:
    """Run agent code for a turn, moving it to the background when asked.

    It moves when ``background`` is set, when the user steers while it runs, or
    when Stop asks to keep its generations going.
    """
    session = kwargs["session"]
    chat_id = kwargs["chat_id"]
    workspace_dir = kwargs["workspace_dir"]
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from .. import background as bg

    # The code runs on a session of its own, so it can outlive this turn: once
    # it moves to the background, the turn's session goes on without it.
    session_maker = async_sessionmaker(session.bind, expire_on_commit=False)
    control = bg.RunControl(session_maker=session_maker)
    turn_interrupted = kwargs.get("interrupt_checker")

    def interrupt_checker() -> bool:
        # Stop ends the turn, and the run with it, only while the turn still owns it.
        return (not control.detached) and callable(turn_interrupted) and bool(turn_interrupted())

    async def execute():
        async with session_maker() as run_session:
            return await run_code_in_sandbox(
                code=code,
                session=run_session,
                chat_id=chat_id,
                workspace_dir=workspace_dir,
                project_workspace_dir=kwargs.get("project_workspace_dir"),
                interrupt_checker=interrupt_checker,
                session_media_ids=kwargs.get("session_media_ids"),
                shown_media_ids=kwargs.get("_shown_media_ids"),
                enabled_stimpacks=kwargs.get("_enabled_stimpacks"),
                project_id=kwargs.get("project_id"),
                effective_model_slug=kwargs.get("_effective_model_slug"),
                control=control,
            )

    label = (kwargs.get("label") or "").strip() or "Running code"
    fg = bg.ForegroundRun(control=control, label=label)
    task = asyncio.create_task(execute())
    has_steer = kwargs.get("_has_pending_input")
    started = time.monotonic()
    detach_reason = None
    bg.set_foreground(chat_id, fg)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.25)
            if done:
                break
            elapsed = time.monotonic() - started
            if fg.detach_requested.is_set():
                detach_reason = "stop"
            elif background and elapsed >= bg.EXPLICIT_DETACH_GRACE_SECONDS:
                detach_reason = "explicit"
            elif callable(has_steer) and has_steer() and elapsed >= bg.STEER_DETACH_GRACE_SECONDS:
                detach_reason = "steer"
            if detach_reason:
                break
    except BaseException:
        # The turn is ending while it still owns the run (a hard Stop): take
        # the run down with it, as before.
        if not control.detached:
            task.cancel()
            while not task.done():
                try:
                    await asyncio.shield(task)
                except BaseException:
                    if task.done():
                        break
        bg.set_foreground(chat_id, None)
        raise

    if detach_reason is None:
        bg.set_foreground(chat_id, None)
        fg.result_saved.set()
        result, llm_usage = task.result()
        # Stash usage on the mutable container so _execute_tool_call can read it
        usage_out = kwargs.get("_llm_usage_out")
        if usage_out is not None and llm_usage and llm_usage.get("calls", 0) > 0:
            usage_out["llm_usage"] = llm_usage
        return result

    wake = fg.detach_wake if detach_reason == "stop" else True
    run = bg.detach(
        chat_id, fg, task,
        reason=detach_reason,
        wake=wake,
        ws_manager=kwargs.get("_ws_manager"),
        on_finished=kwargs.get("_on_background_finished"),
    )
    bg.set_foreground(chat_id, None)
    # Whoever asked for the detach waits for this call's result to be saved.
    after_saved = kwargs.get("_after_result_saved")
    if isinstance(after_saved, list):
        after_saved.append(fg.result_saved.set)
    else:
        fg.result_saved.set()
    items = await control.snapshot_items()
    return bg.describe_detached(run.id, label, items, control.waiting)
