"""Run shell commands in the session workspace."""

import asyncio
import platform
import shutil

from ..tools_registry import tool, ToolParameter

MAX_OUTPUT = 10_000
MAX_TIMEOUT = 600


def is_windows_host() -> bool:
    return platform.system().lower() == "windows"


def get_shell_runtime_name() -> str:
    return "PowerShell" if is_windows_host() else "bash"


@tool(
    name="bash",
    description=(
        "Run a shell command in the session workspace directory. "
        "Uses PowerShell on Windows and bash on other platforms. "
        "Use for file operations, ImageMagick, ffmpeg, and other CLI tools."
    ),
    parameters=[
        ToolParameter(name="command", type="string", description="The shell command to run"),
        ToolParameter(
            name="purpose",
            type="string",
            description=(
                "A short plain-language description of what this command does, shown to the "
                'user if approval is needed (e.g. "Download the reference image", "Move '
                'results into the project folder").'
            ),
            required=False,
        ),
        ToolParameter(name="timeout", type="integer", description="Timeout in seconds (default 120, max 600)", required=False),
    ],
)
async def bash(command: str, timeout: int = 120, **kwargs) -> str:
    workspace_dir = kwargs.get("workspace_dir")
    if not workspace_dir:
        return "Error: no workspace directory available"

    timeout = min(max(timeout, 1), MAX_TIMEOUT)

    proc = None
    try:
        if is_windows_host():
            proc = await asyncio.create_subprocess_exec(
                "powershell",
                "-NoProfile",
                "-Command",
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(workspace_dir),
            )
        else:
            shell_executable = shutil.which("bash")
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(workspace_dir),
                executable=shell_executable or None,
            )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        if proc:
            proc.kill()
        return f"Error: command timed out after {timeout}s"
    except asyncio.CancelledError:
        if proc and proc.returncode is None:
            proc.kill()
        raise
    except Exception as e:
        return f"Error running command: {e}"

    output = ""
    if stdout:
        output += stdout.decode(errors="replace")
    if stderr:
        output += ("\n" if output else "") + stderr.decode(errors="replace")

    if not output:
        return f"(exit code {proc.returncode}, no output)"

    if len(output) > MAX_OUTPUT:
        output = f"... (truncated, showing last {MAX_OUTPUT} chars)\n" + output[-MAX_OUTPUT:]

    return output
