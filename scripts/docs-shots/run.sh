#!/usr/bin/env bash
# Docs screenshot harness runner.
#
#   scripts/docs-shots/run.sh setup      # (re)create + seed the docs-demo sandbox
#   scripts/docs-shots/run.sh shoot      # boot servers and capture all shots
#   scripts/docs-shots/run.sh shoot -g "tool panel"   # capture matching shots only
#   scripts/docs-shots/run.sh clean      # destroy the sandbox
#   scripts/docs-shots/run.sh fluent setup|shoot|clean   # the Fluent set: a real chat
#                                        # model and image tool (see README.md)
#
# Output: frontend/e2e/docs-shots/out/**.png (light theme, 1480x940 @2x).
# Shot log: frontend/e2e/docs-shots/SHOTS.md
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$REPO_ROOT/scripts/docs-shots"
BUNDLE=ai.stimma.stimma.debug

# Machine-specific endpoints live in an ignored local.env (or the environment),
# never in this repo. See README.md for the variables.
if [ -f "$HERE/local.env" ]; then
  set -a; . "$HERE/local.env"; set +a
fi

SET=demo
if [ "${1:-}" = "fluent" ]; then SET=fluent; shift; fi

if [ "$SET" = fluent ]; then
  SANDBOX="${DOCS_SHOTS_FLUENT_SANDBOX:-docs-fluent}"
  BACKEND_PORT="${DOCS_SHOTS_FLUENT_BACKEND_PORT:-9310}"
  FRONTEND_PORT="${DOCS_SHOTS_FLUENT_FRONTEND_PORT:-9311}"
else
  SANDBOX=docs-demo
  BACKEND_PORT="${DOCS_SHOTS_BACKEND_PORT:-9300}"
  FRONTEND_PORT="${DOCS_SHOTS_FRONTEND_PORT:-9301}"
fi
# The sandbox's data dir as the stimma CLI computes it (macOS Application Support,
# XDG data dir on Linux).
DATA_DIR="$("$REPO_ROOT/tools/stimma" --channel=debug --sandbox="$SANDBOX" dir | tail -n 1)"
PROVIDER_PORT=8188   # ComfyUI's usual port: the settings card reads realistically
# The sibling stimma-tools-python checkout (for the demo provider): next to this checkout,
# or next to the main checkout when this is a git worktree; STIMMA_TOOLS_PYTHON overrides.
TOOLS_PY="${STIMMA_TOOLS_PYTHON:-}"
if [ -z "$TOOLS_PY" ]; then
  MAIN_ROOT="$(cd "$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"
  for d in "$REPO_ROOT/../stimma-tools-python" "$MAIN_ROOT/../stimma-tools-python"; do
    if [ -d "$d" ]; then TOOLS_PY="$(cd "$d" && pwd)"; break; fi
  done
fi
UV_BIN="$(command -v uv)"
# Python with the backend's packages (yaml), for the setup scripts.
PY=("$UV_BIN" run --project "$REPO_ROOT/backend" python)
LOG_DIR="${TMPDIR:-/tmp}"

need_fluent_env() {
  local missing=()
  for v in DOCS_SHOTS_CHAT_URL DOCS_SHOTS_CHAT_MODEL DOCS_SHOTS_STP_URL DOCS_SHOTS_IMAGE_TOOL; do
    [ -n "${!v:-}" ] || missing+=("$v")
  done
  if [ ${#missing[@]} -gt 0 ]; then
    echo "the fluent set needs: ${missing[*]} (set them in scripts/docs-shots/local.env)" >&2
    exit 1
  fi
}

wait_http() {
  local url="$1" tries="${2:-60}"
  for _ in $(seq "$tries"); do
    curl -sf "$url" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "timed out waiting for $url" >&2
  return 1
}

# Start a server detached: its own session, stdin/stdout/stderr off the caller's
# terminal or pipe (a caller piping run.sh's output would otherwise wait on it).
detach() {
  local dir="$1" log="$2"; shift 2
  if command -v setsid >/dev/null 2>&1; then
    (cd "$dir" && setsid nohup "$@" </dev/null >"$log" 2>&1 &) </dev/null >/dev/null 2>&1
  else
    (cd "$dir" && nohup "$@" </dev/null >"$log" 2>&1 &) </dev/null >/dev/null 2>&1
  fi
}

start_provider() {
  [ -n "$TOOLS_PY" ] || { echo "can't find stimma-tools-python; set STIMMA_TOOLS_PYTHON" >&2; exit 1; }
  # Demo provider runs as a websocket STP server so the Tool Providers
  # settings card shows a clean ws:// URL (no filesystem paths in frame).
  if ! lsof -ti TCP:$PROVIDER_PORT -sTCP:LISTEN >/dev/null 2>&1; then
    echo "starting demo provider on :$PROVIDER_PORT..."
    # Generation pace: slow enough that in-progress shots can catch a chain
    # mid-flight, fast enough that seeding 20+ images stays quick.
    STIMMA_DEMO_DELAY="${STIMMA_DEMO_DELAY:-0.5}" detach "$REPO_ROOT" "$LOG_DIR/docs-demo-provider.log" \
      "$UV_BIN" run --project "$TOOLS_PY" python \
      "$REPO_ROOT/scripts/docs-shots/demo_provider.py" --websocket --port $PROVIDER_PORT
    sleep 2
  fi
}

start_backend() {
  [ "$SET" = fluent ] || start_provider
  if ! curl -sf "http://localhost:$BACKEND_PORT/api/profiles" >/dev/null 2>&1; then
    echo "starting backend on :$BACKEND_PORT (sandbox=$SANDBOX)..."
    detach "$REPO_ROOT/backend" "$LOG_DIR/$SANDBOX-backend.log" \
      "$UV_BIN" run python main.py --bundle-id=$BUNDLE --sandbox=$SANDBOX --port=$BACKEND_PORT
    wait_http "http://localhost:$BACKEND_PORT/api/profiles" 90
  fi
}

start_frontend() {
  if ! curl -sf "http://localhost:$FRONTEND_PORT/" >/dev/null 2>&1; then
    echo "starting vite on :$FRONTEND_PORT..."
    STIMMA_BACKEND_PORT=$BACKEND_PORT STIMMA_FRONTEND_PORT=$FRONTEND_PORT \
      detach "$REPO_ROOT/frontend" "$LOG_DIR/$SANDBOX-vite.log" npx vite
    wait_http "http://localhost:$FRONTEND_PORT/" 60
  fi
}

configure_demo() {
  mkdir -p "$DATA_DIR/Library"
  "${PY[@]}" - "$DATA_DIR/config.yaml" <<EOF
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

# The first-run setup wizard and tour: seen, so they never cover a shot.
for key in ('setup_wizard_seen_version', 'tour_seen_version'):
    if not re.search(rf'^{key}:', text, re.M):
        text += f'{key}: 1\n'

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

}

configure_fluent() {
  need_fluent_env
  mkdir -p "$DATA_DIR/Library"
  "${PY[@]}" "$HERE/fluent_setup.py" --config "$DATA_DIR/config.yaml" --library "$DATA_DIR/Library"
}

cmd_setup() {
  [ "$SET" = fluent ] && need_fluent_env
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

  # First boot generates config.yaml; then each set adds its own config.
  start_backend
  lsof -ti TCP:$BACKEND_PORT -sTCP:LISTEN | xargs kill 2>/dev/null || true
  sleep 2

  if [ "$SET" = fluent ]; then configure_fluent; else configure_demo; fi

  start_backend
  if [ "$SET" = fluent ]; then
    echo "connecting the chat model..."
    "${PY[@]}" "$HERE/fluent_setup.py" --port $BACKEND_PORT
  else
    echo "seeding demo library..."
    "${PY[@]}" "$HERE/seed.py" --port $BACKEND_PORT
  fi
  echo "setup complete"
}

cmd_shoot() {
  start_backend
  start_frontend
  rm -rf "$REPO_ROOT/frontend/e2e/docs-shots/.auth"
  # The config picks each set's specs from DOCS_SHOTS_SET.
  [ "$SET" = fluent ] && need_fluent_env
  (cd "$REPO_ROOT/frontend" && STIMMA_FRONTEND_PORT=$FRONTEND_PORT STIMMA_BACKEND_PORT=$BACKEND_PORT \
    DOCS_SHOTS_BUNDLE=$BUNDLE DOCS_SHOTS_SANDBOX=$SANDBOX DOCS_SHOTS_SET=$SET \
    npx playwright test --config e2e/docs-shots/playwright.config.ts "$@")
  echo "shots in frontend/e2e/docs-shots/out/"
}

cmd_clean() {
  lsof -ti TCP:$BACKEND_PORT -sTCP:LISTEN | xargs kill 2>/dev/null || true
  lsof -ti TCP:$FRONTEND_PORT -sTCP:LISTEN | xargs kill 2>/dev/null || true
  [ "$SET" = fluent ] || lsof -ti TCP:$PROVIDER_PORT -sTCP:LISTEN | xargs kill 2>/dev/null || true
  "$REPO_ROOT/tools/stimma" fork destroy $SANDBOX --yes
}

case "${1:-}" in
  setup) shift; cmd_setup "$@" ;;
  shoot) shift; cmd_shoot "$@" ;;
  clean) shift; cmd_clean "$@" ;;
  *) sed -n '2,11p' "$0"; exit 1 ;;
esac
