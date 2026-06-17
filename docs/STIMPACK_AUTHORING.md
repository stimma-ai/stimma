# Stimpack Authoring Guide

Quick reference for creating Stimma agent stimpacks. Written for the coding agent and for humans.

## What stimpacks are

A **stimpack** is the installable/marketplace PACKAGE. It is a directory holding a `stimpack.json` manifest plus the files for one or more typed **resources**. The most common resource is a `skill` — a `SKILL.md` instruction document that loads into the agent's context on demand to teach it domain-specific workflows, patterns, and mental models. Stimpacks are **not** required for basic operation — the agent works fine without any enabled.

> Naming: the package is always a "stimpack". The word "skill" survives only as the name of the agent-instruction **resource type** (`SKILL.md`).

## Stimpack manifest (`stimpack.json`)

Every stimpack declares its resources in a `stimpack.json` at the pack root:

```json
{
  "name": "my-stimpack",
  "display_name": "My Stimpack",
  "description": "One-line description shown in the stimpacks inventory",
  "version": "1",
  "author": "system",
  "tags": ["relevant", "tags"],
  "resources": [
    { "type": "skill", "path": "SKILL.md" }
  ]
}
```

### Resource types

| Type | Status | Backed by |
|------|--------|-----------|
| `skill` | **Fully wired** | `SKILL.md` (+ optional `lib/`). Injected on invoke; `lib/*` importable in `run_code`. |
| `tool` | Recognized, not yet loaded | (manifest schema + stub lander) |
| `flow` | Recognized, not yet loaded | (manifest schema + stub lander) |
| `asset` | Recognized, not yet loaded | (manifest schema + stub lander) |
| `model` | Recognized, not yet loaded | (manifest schema + stub lander) |
| `flow_guidance` | Recognized, not yet loaded | (manifest schema + stub lander) |

Only `skill` is fully wired today. The other types have a manifest schema and a lander interface in place (each currently a stub that logs "recognized, not yet loaded"), so new resource types can be added incrementally.

A **bare `SKILL.md` with no `stimpack.json`** still loads: a default single-`skill` manifest is derived from its frontmatter. Vended/published stimpacks should ship a real `stimpack.json`.

## Stimpack types

### Markdown-only stimpacks (most common)

Pure guidance — the agent reads the instructions and uses its existing tools (`run_code`, `call_tool`, etc.) to carry them out. Good for workflows, checklists, prompt engineering patterns.

### Stimpacks with code

Stimpacks can bundle a `lib/` directory containing Python modules that become importable inside `run_code` when the stimpack is enabled. Good for domain-specific processing libraries (color grading, image analysis, data transforms) that are too large or specialized for the system prompt.

## Directory layout

```
stimpacks/
    my-stimpack/
        stimpack.json         # Manifest — declares the pack's resources
        SKILL.md              # The `skill` resource — frontmatter + markdown body
        example.png           # Optional — companion assets
        lib/                  # Optional — Python modules for run_code (skill)
            my_lib/
                __init__.py
                utils.py
                data/
                    presets.json
```

Stimpacks are stored in two locations:
- **Bundled**: `backend/agent/v2/stimpacks/` — ships with app, read-only, auto-synced
- **User/Agent**: `~/.Stimma/profiles/{profile_id}/stimpacks/` — read-write, created by users or the agent

## SKILL.md format

```yaml
---
name: my-stimpack
display_name: My Stimpack
description: One-line description shown in stimpacks inventory
author: system        # system | user | agent
tags: [relevant, tags]
provides:             # optional — list Python modules in lib/
  - my_lib
---

# My Stimpack

Markdown body goes here. This is what the agent sees when the stimpack is invoked.
```

### Frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Kebab-case identifier, must be unique |
| `display_name` | yes | Human-readable name |
| `description` | yes | One-liner for the stimpacks inventory table |
| `author` | yes | `system` (bundled), `user` (edited), or `agent` (auto-created) |
| `tags` | no | For discovery and categorization |
| `provides` | no | List of Python module names available in `lib/`. Shows as `(imports: my_lib)` in the stimpacks inventory |

### Markdown body guidelines

- Lead with a one-line summary of what the stimpack does
- Describe the workflow as principles and mental models, not rigid step lists
- If the stimpack has code (`provides`), include a Usage section with import examples
- Reference SDK methods by name: `stimma.call_tool()`, `asyncio.gather()`, etc.
- Code examples should be complete enough to copy-paste-adapt, with comments explaining each section
- Keep it focused — one primary workflow per stimpack

## Stimpacks with Python code

### How it works

1. Put Python modules in `lib/` inside the stimpack directory
2. Declare them in frontmatter via `provides: [module_name]`
3. When the stimpack is enabled, the agent can `import module_name` inside `run_code`

The `lib/` directory acts as a Python package root. Each top-level directory with `__init__.py` (or top-level `.py` file) inside `lib/` becomes an importable module.

### Example structure

```
color-math/
    SKILL.md
    lib/
        color_math/           # <- importable as `color_math`
            __init__.py
            conversions.py
            blend.py
```

Agent code in `run_code`:
```python
from color_math import rgb_to_hsl, blend
# ... use functions on numpy arrays
```

### Rules for stimpack code

- **Stimpack code is trusted** — it runs via real `importlib`, not inside the sandbox. It has the same access as any installed Python package.
- **Dependencies**: Stimpack code can freely import numpy, scipy, PIL, and any other package installed in the backend environment. It cannot import other stimpacks' modules.
- **Data files**: Use `Path(__file__).parent / "data" / "file.json"` to load data files relative to the module. `__file__` is set correctly by the import system.
- **Module names must not collide** with built-in allowed modules (json, numpy, PIL, math, etc.). Collisions are detected at runtime and the stimpack module is skipped with a warning.
- **Async is fine**: Stimpack modules can define async functions. Agent code in `run_code` can `await` them.

### SKILL.md for code stimpacks

When a stimpack provides importable code, the markdown body should document:

1. **What to import** — show the exact import statement
2. **Function signatures** — list available functions with argument types and descriptions
3. **Data format** — what array shapes, dtypes, value ranges functions expect and return
4. **Usage examples** — complete code blocks the agent can adapt

The agent learns about the stimpack's API by reading the markdown, then uses it in `run_code`. The markdown is the documentation.

## Distribution

### As a zip file

Stimpacks can be distributed as `.zip` files. The zip should contain `SKILL.md` at the top level (or in a subdirectory), plus any companion files including `lib/`. Install via the UI or programmatically with `install_stimpack_from_file(path)`.

```
my-stimpack.zip
    SKILL.md
    lib/
        my_lib/
            __init__.py
            ...
```

### Bundled with the app

Place the stimpack directory in `backend/agent/v2/stimpacks/`. Set `author: system` in frontmatter. The agent discovers and invokes stimpacks dynamically via system reminders.

## Stimpack lifecycle

1. **Discovery**: Agent sees the stimpacks inventory table (name, description, enabled status, provided imports)
2. **Invocation**: Agent calls `stimpack(action="invoke", name="...")` to load full content into context
3. **Execution**: Agent uses normal tools (`run_code`, `call_tool`, etc.) guided by the stimpack's instructions
4. **Creation**: Agent can create new stimpacks via `stimpack(action="create", ...)`
5. **Forking**: Users can edit bundled stimpacks — the edit creates a user-tier copy

## Checklist for new stimpacks

- [ ] `SKILL.md` has complete frontmatter (name, display_name, description, author, tags)
- [ ] Description is concise enough for the inventory table (~10 words)
- [ ] Markdown body teaches principles, not rigid procedures
- [ ] If the stimpack has `lib/`: `provides` lists all importable module names
- [ ] If the stimpack has `lib/`: markdown documents the API with import examples
- [ ] Module names don't collide with built-in modules
- [ ] Tested: enable the stimpack, run a prompt that exercises it, verify the agent uses it correctly
