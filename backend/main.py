"""
Stimma Backend - Main Application Entry Point

This is the refactored main.py that imports modular route components.
All route logic has been split into separate modules under the routes/ directory.
"""

# Create a new process group so Tauri can kill all our children with one signal
# Only do this for the main process, not spawned multiprocessing workers
# (Workers re-run main.py but should stay in parent's process group)
import os
import sys
if not any('--multiprocessing' in arg or 'from multiprocessing' in arg for arg in sys.argv):
    if os.name != "nt":
        try:
            os.setpgrp()
        except OSError:
            pass  # May fail if already a process group leader

# Augment PATH with common binary locations so we can find ffmpeg, ffprobe, etc.
# macOS apps launched from Finder/Dock get a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin)
# that doesn't include Homebrew or MacPorts paths.
_extra_paths = [
    "/opt/homebrew/bin",       # Homebrew (Apple Silicon)
    "/usr/local/bin",          # Homebrew (Intel) / manual installs
    "/opt/local/bin",          # MacPorts
]
if os.name == "nt":
    _extra_paths = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links"),  # winget
        os.path.expandvars(r"%ProgramFiles%\ffmpeg\bin"),
        os.path.expandvars(r"%ChocolateyInstall%\bin") if os.environ.get("ChocolateyInstall") else "",
    ]
_current_path = os.environ.get("PATH", "")
_dirs_to_add = [p for p in _extra_paths if p and p not in _current_path and os.path.isdir(p)]
if _dirs_to_add:
    os.environ["PATH"] = _current_path + os.pathsep + os.pathsep.join(_dirs_to_add)

# Watch for parent death - when parent dies, we get reparented to init/launchd (PID 1)
# This ensures cleanup even if parent is killed with SIGKILL
import threading
import signal
import time as _time

def _watch_parent():
    """Exit if parent process dies (detected via getppid change)."""
    parent_pid = os.getppid()
    while True:
        if os.getppid() != parent_pid:
            # Parent died - kill our entire process group
            if os.name != "nt":
                kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
                try:
                    os.killpg(os.getpgid(os.getpid()), kill_signal)
                except OSError:
                    os.kill(os.getpid(), kill_signal)
            else:
                os._exit(0)
        _time.sleep(0.5)

threading.Thread(target=_watch_parent, daemon=True).start()

# Parse CLI arguments FIRST - before any other imports that might load config
# This is needed to determine the app modifier for finding config location
import argparse
import time
_startup_time = time.time()

def _parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Stimma Backend')
    parser.add_argument('--bundle-id', default='ai.stimma.stimma.debug',
                        help='App bundle ID for environment separation')
    parser.add_argument('--sandbox', default='default',
                        help='Sandbox name for data isolation')
    parser.add_argument('--port', type=int, default=None,
                        help='Port to bind to (0 for ephemeral, default from config)')
    # Multiprocessing worker/spawn helper processes can inject internal argv
    # such as "--multiprocessing-fork ...". Ignore unknown args so workers
    # can bootstrap without tripping backend CLI parsing.
    args, _unknown = parser.parse_known_args()
    return args

_args = _parse_args()

# Set app modifier in context before any config loading
from app_context import set_app_context
set_app_context(_args.bundle_id, _args.sandbox)

# Initialize structured logging FIRST before any other imports
# We need to read the log level from config before full config loading
def _get_log_level_from_config() -> str:
    """Read log level from config.yaml without full config loading."""
    import yaml
    from app_dirs import get_config_path

    config_path = get_config_path()
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
                return config.get("server", {}).get("log_level", "INFO")
        except Exception:
            pass
    return "INFO"

from app_dirs import get_data_dir
from core.logging import setup_logging, get_logger

# Set up logging with rolling file output to the app data directory
setup_logging(
    log_level=_get_log_level_from_config(),
    log_dir=get_data_dir()
)

from core.app import create_app

# CRITICAL: Eagerly import websockets submodules to avoid race conditions in PyInstaller
# When bundled with PyInstaller, lazy imports can cause zlib decompression errors
# if multiple coroutines trigger the same lazy import simultaneously.
# By importing everything at startup (single-threaded), we avoid the race.
import websockets
import websockets.client
import websockets.exceptions
import websockets.frames
import websockets.protocol
import websockets.legacy
import websockets.legacy.client
import websockets.legacy.protocol
# Force the lazy import system to resolve 'connect' now
_ = websockets.connect

log = get_logger(__name__)
log.info(f"TIMING: core.app imported at {time.time() - _startup_time:.2f}s")

# Import all route modules
from routes import (
    admin,
    auth,
    boards,
    cloud,
    chats,
    feedback,
    flags,
    generation,
    keywords,
    markers,
    media,
    media_files,
    models,
    postprocessing,
    preferences,
    projects,
    processing,
    prompt_enhancement,
    profiles,
    realtime,
    flows,
    saved_views,
    tasks as flow_tasks,
    settings,
    share,
    skill_marketplace,
    tags,
    telemetry,
    tools,
    trash,
    mask_assistant,
    presets,
)

log.info(f"TIMING: routes imported at {time.time() - _startup_time:.2f}s")

# Create the FastAPI app
app = create_app()
log.info(f"TIMING: app created at {time.time() - _startup_time:.2f}s")

# Root health check
@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "Stimma API"}

# Include all routers
app.include_router(auth.router)
app.include_router(boards.router)
app.include_router(cloud.router)
app.include_router(media.router)
app.include_router(models.router)
app.include_router(markers.router)
app.include_router(tags.router)
app.include_router(trash.router)
app.include_router(keywords.router)
app.include_router(generation.router)
app.include_router(postprocessing.router)
app.include_router(processing.router)
app.include_router(media_files.router)
app.include_router(preferences.router)
app.include_router(projects.router)
app.include_router(flows.router)
app.include_router(flow_tasks.router)
app.include_router(admin.router)
app.include_router(realtime.router)
app.include_router(chats.router)
app.include_router(prompt_enhancement.router)
app.include_router(profiles.router)
app.include_router(saved_views.router)
app.include_router(settings.router)
app.include_router(tools.router)
app.include_router(mask_assistant.router)
app.include_router(presets.router)
app.include_router(share.router)
app.include_router(skill_marketplace.router)
app.include_router(telemetry.router)
app.include_router(feedback.router)
app.include_router(flags.router)

log.info(f"TIMING: routers included at {time.time() - _startup_time:.2f}s")

if __name__ == "__main__":
    import uvicorn
    import socket
    from config import get_settings

    # Get port from CLI args, falling back to config
    settings = get_settings()
    port = _args.port if _args.port is not None else settings.server.port

    # If port is 0 (ephemeral), we need to use uvicorn.Server to get the actual port
    if port == 0:
        # Find an available port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]

    # Output port in a parseable format for Tauri to read
    # This MUST be printed before uvicorn starts to ensure Tauri can parse it
    print(f"STIMMA_BACKEND_PORT={port}", flush=True)

    log.info(f"TIMING: starting uvicorn at {time.time() - _startup_time:.2f}s")

    # Configure uvicorn to use our logging (not its own)
    # NOTE: reload=False because nodemon handles file watching and restarts.
    # Using both causes deadlocks because watchfiles (uvicorn's reloader) can
    # get stuck in Rust code that doesn't respond to signals.
    # NOTE: We pass the app object directly (not "main:app" string) because
    # PyInstaller bundles the app and string imports don't work.
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        reload=False,
        timeout_graceful_shutdown=0,  # No graceful shutdown wait
        log_config=None,  # Disable uvicorn's logging config - we use our own
    )
