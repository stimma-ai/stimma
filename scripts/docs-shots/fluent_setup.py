"""
Configure the docs-fluent sandbox: a real chat model and a real image tool.

Two steps, both driven by run.sh (`run.sh fluent setup`):

    fluent_setup.py --config <config.yaml> --library <dir>   # before boot
    fluent_setup.py --port 9310                              # backend running

Before boot it points the library folder inside the sandbox and sets the light
theme. With the backend up it goes through the same API the Settings screens
use: adds the chat model as a local OpenAI-compatible endpoint (which tests it
and reads what it supports), sets every agent role to it with reasoning off
(Fluent runs with reasoning off), and adds the image tool's STP provider.

Endpoints come from the environment (scripts/docs-shots/local.env, ignored):

    DOCS_SHOTS_CHAT_URL     OpenAI-compatible base URL, e.g. http://localhost:8000/v1
    DOCS_SHOTS_CHAT_MODEL   the model id that endpoint serves
    DOCS_SHOTS_STP_URL      the image tools' STP websocket, e.g. ws://localhost:8188/stp-v1
    DOCS_SHOTS_IMAGE_TOOL   full tool id the shots use, e.g. comfyui:my-image-tool
    DOCS_SHOTS_PEOPLE_FROM  optional: Fluent's "People are from" (country code or anywhere)
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = ""
PROFILE = ""


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"{name} is not set (see scripts/docs-shots/README in frontend/e2e/docs-shots)")
    return value


def api(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        f"{BASE}{path}",
        method=method,
        headers={"X-Profile-ID": PROFILE, "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read() or "null")
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path}: {e.code} {e.read().decode(errors='replace')[:400]}")


def configure(config_path: str, library: str) -> None:
    """Edit the generated config before the real boot: library inside the sandbox, light theme,
    first-run screens seen."""
    import yaml  # run.sh runs this with the backend's environment

    with open(config_path) as f:
        text = f.read()
    # The template's first folder is the user's Documents; keep it inside the sandbox.
    text = re.sub(r'  - path: ".*?"', f'  - path: "{library}"', text, count=1)
    cfg = yaml.safe_load(text) or {}
    cfg["theme"] = "light"
    # The first-run setup wizard and tour: seen, so they never cover a shot.
    cfg["setup_wizard_seen_version"] = 1
    cfg["tour_seen_version"] = 1
    with open(config_path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
    print("config ok")


def connect(port: int) -> None:
    global BASE, PROFILE
    BASE = f"http://localhost:{port}"
    PROFILE = api("GET", "/api/profiles")["profiles"][0]["id"]

    chat_url, chat_model = env("DOCS_SHOTS_CHAT_URL"), env("DOCS_SHOTS_CHAT_MODEL")
    stp_url, tool = env("DOCS_SHOTS_STP_URL"), env("DOCS_SHOTS_IMAGE_TOOL")

    # 1. The chat model, as Settings → AI Services adds a local endpoint. A generic
    #    name, so no host appears in any Settings frame.
    providers = api("GET", "/api/models/providers")["providers"]
    provider = next((p for p in providers if p.get("base_url") == chat_url.rstrip("/")), None)
    if provider is None:
        provider = api("POST", "/api/models/providers", {
            "kind": "local", "name": "Local endpoint", "base_url": chat_url, "model_ids": [chat_model],
        })
    slug = next(m["id"] for m in provider["models"] if m.get("model_id") == chat_model or m["id"].endswith(f":{chat_model}"))
    print(f"chat model: {slug}")

    # 2. Every role on it, reasoning off.
    roles = ("quick_task", "tool_assistant", "chat", "flow")
    api("PATCH", "/api/settings/agent", {"models": {r: {"model": slug, "effort": "off"} for r in roles}})
    print(f"roles: {', '.join(roles)} (effort off)")

    # 3. The image tools' provider: the tool id's prefix names it.
    provider_id = tool.split(":", 1)[0]
    existing = {p.get("provider_id") for p in api("GET", "/api/tools/providers")}
    if provider_id not in existing:
        api("POST", "/api/settings/tool-providers", {
            "id": provider_id, "name": "ComfyUI" if provider_id == "comfyui" else provider_id,
            "type": "websocket", "url": stp_url,
        })
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    f"{BASE}/api/tools/provider-tool/{tool}", headers={"X-Profile-ID": PROFILE}), timeout=30):
                break
        except urllib.error.URLError:
            time.sleep(2)
    else:
        sys.exit(f"tool {tool} did not appear from {provider_id}")
    print(f"image tool: {tool}")

    # 4. Where people are from, when the shots should say so.
    people = os.environ.get("DOCS_SHOTS_PEOPLE_FROM", "").strip()
    if people:
        api("PUT", "/api/prompt-programs/people-from", {"value": people})
        print(f"people from: {people}")
    print("fluent setup complete")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--library")
    ap.add_argument("--port", type=int)
    args = ap.parse_args()
    if args.config:
        configure(args.config, args.library)
    if args.port:
        connect(args.port)


if __name__ == "__main__":
    main()
