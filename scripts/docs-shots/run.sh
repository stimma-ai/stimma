#!/usr/bin/env bash
# Docs screenshot harness runner.
#
#   scripts/docs-shots/run.sh setup      # (re)create + seed the docs-demo sandbox
#   scripts/docs-shots/run.sh shoot      # boot servers and capture all shots
#   scripts/docs-shots/run.sh shoot -g "tool panel"   # capture matching shots only
#   scripts/docs-shots/run.sh clean      # destroy the sandbox
#
# Output: frontend/e2e/docs-shots/out/**.png (light theme, 1480x940 @2x).
# Shot log: frontend/e2e/docs-shots/SHOTS.md
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SANDBOX=docs-demo
BUNDLE=ai.stimma.stimma.debug
DATA_DIR="$HOME/Library/Application Support/$BUNDLE/$SANDBOX"
BACKEND_PORT=9300
FRONTEND_PORT=9301
PROVIDER_PORT=8188   # ComfyUI's usual port: the settings card reads realistically
TOOLS_PY="$(cd "$REPO_ROOT/.." && pwd)/stimma-tools-python"
UV_BIN="$(command -v uv)"

wait_http() {
  local url="$1" tries="${2:-60}"
  for _ in $(seq "$tries"); do
    curl -sf "$url" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "timed out waiting for $url" >&2
  return 1
}

start_provider() {
  # Demo provider runs as a websocket STP server so the Tool Providers
  # settings card shows a clean ws:// URL (no filesystem paths in frame).
  if ! lsof -ti TCP:$PROVIDER_PORT -sTCP:LISTEN >/dev/null 2>&1; then
    echo "starting demo provider on :$PROVIDER_PORT..."
    # Generation pace: slow enough that in-progress shots can catch a chain
    # mid-flight, fast enough that seeding 20+ images stays quick.
    (STIMMA_DEMO_DELAY="${STIMMA_DEMO_DELAY:-0.5}" nohup "$UV_BIN" run --project "$TOOLS_PY" python \
      "$REPO_ROOT/scripts/docs-shots/demo_provider.py" --websocket --port $PROVIDER_PORT \
      > /tmp/docs-demo-provider.log 2>&1 &)
    sleep 2
  fi
}

start_backend() {
  start_provider
  if ! curl -sf "http://localhost:$BACKEND_PORT/api/profiles" >/dev/null 2>&1; then
    echo "starting backend on :$BACKEND_PORT (sandbox=$SANDBOX)..."
    (cd "$REPO_ROOT/backend" && nohup "$UV_BIN" run python main.py \
      --bundle-id=$BUNDLE --sandbox=$SANDBOX --port=$BACKEND_PORT \
      > /tmp/docs-demo-backend.log 2>&1 &)
    wait_http "http://localhost:$BACKEND_PORT/api/profiles" 90
  fi
}

start_frontend() {
  if ! curl -sf "http://localhost:$FRONTEND_PORT/" >/dev/null 2>&1; then
    echo "starting vite on :$FRONTEND_PORT..."
    (cd "$REPO_ROOT/frontend" && STIMMA_BACKEND_PORT=$BACKEND_PORT STIMMA_FRONTEND_PORT=$FRONTEND_PORT \
      nohup npx vite > /tmp/docs-demo-vite.log 2>&1 &)
    wait_http "http://localhost:$FRONTEND_PORT/" 60
  fi
}

cmd_setup() {
  if [ -d "$DATA_DIR" ]; then
    echo "sandbox exists; destroying first..."
    "$REPO_ROOT/tools/stimma" fork destroy $SANDBOX --yes
    lsof -ti TCP:$BACKEND_PORT -sTCP:LISTEN | xargs kill 2>/dev/null || true
    sleep 1
  fi
  "$REPO_ROOT/tools/stimma" fork create $SANDBOX --empty
  # Pin the harness ports (fork auto-assigns; the harness wants stable ones).
  cat > "$DATA_DIR/.fork.json" <<EOF
{
  "server_port": $BACKEND_PORT,
  "frontend_port": $FRONTEND_PORT
}
EOF

  # First boot generates config.yaml; then we add the demo provider config.
  start_backend
  lsof -ti TCP:$BACKEND_PORT -sTCP:LISTEN | xargs kill 2>/dev/null || true
  sleep 2

  mkdir -p "$DATA_DIR/Library"
  python3 - "$DATA_DIR/config.yaml" <<EOF
import re, sys
p = sys.argv[1]
text = open(p).read()

# Library folder lives inside the sandbox, not the user's real Documents.
text = re.sub(r'  - path: ".*?"', '  - path: "$DATA_DIR/Library"', text, count=1)

# The config template writes the library marker's id after an unrelated
# comment block (it still parses as part of the marker). Putting a top-level
# key between them breaks parsing, so reunite the stray id with its marker.
stray = [l for l in text.splitlines() if l.strip().startswith('id: library-')]
if stray:
    sid = stray[0].strip()
    text = '\n'.join(l for l in text.splitlines() if l.strip() != sid or l.startswith('  - ')) + '\n'
    text = text.replace('    color: "#3b82f6"\n', f'    color: "#3b82f6"\n    {sid}\n', 1)

# Register the demo provider (websocket: the settings card shows a clean
# ws:// URL instead of filesystem paths).
provider = '''tool_providers:
- id: comfyui
  name: ComfyUI
  type: websocket
  url: ws://127.0.0.1:$PROVIDER_PORT/stp-v1
'''
text = text.replace('# tool_providers: []', provider)

# Docs shots are captured in light theme.
if not re.search(r'^theme:', text, re.M):
    text += '\ntheme: light\n'

# Point LLM roles at a local Ollama when one is running: prompt
# suggestions and chat then work for real instead of erroring.
try:
    import json, urllib.request
    models = json.load(urllib.request.urlopen('http://localhost:11434/v1/models', timeout=2))['data']
    model = next((m['id'] for m in models if m['id'].startswith('gemma4')), models[0]['id'])
    endpoint = (
        '    source: endpoint\n'
        '    endpoint:\n'
        '      url: http://localhost:11434/v1\n'
        f'      model: {model}\n'
        '      max_context_tokens: 128000\n'
    )
    text = text.replace(
        'llms:\n  agent:\n    source: auto\n  agent-fast:\n    source: auto\n',
        f'llms:\n  agent:\n{endpoint}  agent-fast:\n{endpoint}')
    print(f'llm endpoint: ollama {model}')
except Exception as e:
    print(f'no local ollama ({e}); LLM features will be unavailable in shots')

open(p, 'w').write(text)
import yaml; yaml.safe_load(open(p))
print('config ok')
EOF

  start_backend
  echo "seeding demo library..."
  python3 "$REPO_ROOT/scripts/docs-shots/seed.py" --port $BACKEND_PORT
  echo "setup complete"
}

cmd_shoot() {
  start_backend
  start_frontend
  rm -rf "$REPO_ROOT/frontend/e2e/docs-shots/.auth"
  (cd "$REPO_ROOT/frontend" && STIMMA_FRONTEND_PORT=$FRONTEND_PORT STIMMA_BACKEND_PORT=$BACKEND_PORT \
    npx playwright test --config e2e/docs-shots/playwright.config.ts "$@")
  echo "shots in frontend/e2e/docs-shots/out/"
}

cmd_clean() {
  lsof -ti TCP:$BACKEND_PORT -sTCP:LISTEN | xargs kill 2>/dev/null || true
  lsof -ti TCP:$FRONTEND_PORT -sTCP:LISTEN | xargs kill 2>/dev/null || true
  lsof -ti TCP:$PROVIDER_PORT -sTCP:LISTEN | xargs kill 2>/dev/null || true
  "$REPO_ROOT/tools/stimma" fork destroy $SANDBOX --yes
}

case "${1:-}" in
  setup) shift; cmd_setup "$@" ;;
  shoot) shift; cmd_shoot "$@" ;;
  clean) shift; cmd_clean "$@" ;;
  *) sed -n '2,9p' "$0"; exit 1 ;;
esac
