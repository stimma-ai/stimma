#!/bin/bash
set -e

# Get the target triple for the current platform
TARGET=$(rustc -Vv | grep host | cut -f2 -d' ')

echo "Building sidecar for target: $TARGET"

# Navigate to backend directory
cd "$(dirname "$0")/../backend"

# Clean EVERYTHING - venv, caches, builds
echo "Cleaning all caches and builds..."
rm -rf .venv dist build *.spec __pycache__ .pytest_cache
# Clean PyInstaller cache (macOS locations)
echo "Cleaning PyInstaller cache..."
rm -rf ~/Library/Caches/pyinstaller 2>/dev/null || true
rm -rf ~/.pyinstaller 2>/dev/null || true
rm -rf /tmp/pyinstaller* 2>/dev/null || true

# Clean Tauri release bundle to force fresh copy of sidecar
echo "Cleaning Tauri bundle..."
rm -rf ../src-tauri/target/release/bundle 2>/dev/null || true
rm -f ../src-tauri/target/release/stimma-backend 2>/dev/null || true

# Recreate venv and sync dependencies
echo "Recreating venv and syncing dependencies..."
uv venv
uv sync --extra dev

# Use uv to run pyinstaller in the right environment
# --noupx: Disable UPX compression which can corrupt the archive
# --clean: Force a clean build, don't use cached analysis
uv run pyinstaller --onefile \
    --clean \
    --noupx \
    --name "stimma-backend-$TARGET" \
    --add-data "alembic:alembic" \
    --add-data "alembic.ini:." \
    --add-data "../prompts.yaml:." \
    --hidden-import "uvicorn.logging" \
    --hidden-import "uvicorn.protocols" \
    --hidden-import "uvicorn.protocols.http" \
    --hidden-import "uvicorn.protocols.http.auto" \
    --hidden-import "uvicorn.protocols.http.h11_impl" \
    --hidden-import "uvicorn.protocols.http.httptools_impl" \
    --hidden-import "uvicorn.protocols.websockets" \
    --hidden-import "uvicorn.protocols.websockets.auto" \
    --hidden-import "uvicorn.protocols.websockets.websockets_impl" \
    --hidden-import "uvicorn.protocols.websockets.wsproto_impl" \
    --hidden-import "uvicorn.lifespan" \
    --hidden-import "uvicorn.lifespan.on" \
    --hidden-import "uvicorn.lifespan.off" \
    --hidden-import "aiosqlite" \
    --hidden-import "sqlalchemy.dialects.sqlite" \
    --hidden-import "websockets.client" \
    --hidden-import "websockets.exceptions" \
    --hidden-import "websockets.frames" \
    --hidden-import "websockets.protocol" \
    --hidden-import "websockets.legacy" \
    --hidden-import "websockets.legacy.client" \
    --collect-data "open_clip" \
    --collect-all "tiktoken" \
    --collect-all "tiktoken_ext" \
    --collect-all "aiohttp" \
    --collect-all "websockets" \
    main.py

# Move the built binary to the Tauri binaries directory
mkdir -p ../src-tauri/binaries
mv "dist/stimma-backend-$TARGET" ../src-tauri/binaries/

echo "Sidecar built and moved to src-tauri/binaries/"
ls -la ../src-tauri/binaries/
