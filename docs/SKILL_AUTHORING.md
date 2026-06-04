# Skill Authoring Guide

Quick reference for creating Stimma agent skills. Written for the coding agent and for humans.

## What skills are

Skills are reusable instruction documents that load into the agent's context on demand. They teach the agent domain-specific workflows, patterns, and mental models. Skills are **not** required for basic operation — the agent works fine without any enabled.

## Skill types

### Markdown-only skills (most common)

Pure guidance — the agent reads the instructions and uses its existing tools (`run_code`, `call_tool`, etc.) to carry them out. Good for workflows, checklists, prompt engineering patterns.

### Skills with code

Skills can bundle a `lib/` directory containing Python modules that become importable inside `run_code` when the skill is enabled. Good for domain-specific processing libraries (color grading, image analysis, data transforms) that are too large or specialized for the system prompt.

## Directory layout

```
skills/
    my-skill/
        SKILL.md              # Required — frontmatter + markdown body
        example.png           # Optional — companion assets
        lib/                  # Optional — Python modules for run_code
            my_lib/
                __init__.py
                utils.py
                data/
                    presets.json
```

Skills are stored in two locations:
- **Bundled**: `backend/agent/v2/skills/` — ships with app, read-only, auto-synced
- **User/Agent**: `~/.Stimma/profiles/{profile_id}/skills/` — read-write, created by users or the agent

## SKILL.md format

```yaml
---
name: my-skill
display_name: My Skill
description: One-line description shown in skills inventory
author: system        # system | user | agent
tags: [relevant, tags]
provides:             # optional — list Python modules in lib/
  - my_lib
---

# My Skill

Markdown body goes here. This is what the agent sees when the skill is invoked.
```

### Frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Kebab-case identifier, must be unique |
| `display_name` | yes | Human-readable name |
| `description` | yes | One-liner for the skills inventory table |
| `author` | yes | `system` (bundled), `user` (edited), or `agent` (auto-created) |
| `tags` | no | For discovery and categorization |
| `provides` | no | List of Python module names available in `lib/`. Shows as `(imports: my_lib)` in the skills inventory |

### Markdown body guidelines

- Lead with a one-line summary of what the skill does
- Describe the workflow as principles and mental models, not rigid step lists
- If the skill has code (`provides`), include a Usage section with import examples
- Reference SDK methods by name: `stimma.call_tool()`, `asyncio.gather()`, etc.
- Code examples should be complete enough to copy-paste-adapt, with comments explaining each section
- Keep it focused — one primary workflow per skill

## Skills with Python code

### How it works

1. Put Python modules in `lib/` inside the skill directory
2. Declare them in frontmatter via `provides: [module_name]`
3. When the skill is enabled, the agent can `import module_name` inside `run_code`

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

### Rules for skill code

- **Skill code is trusted** — it runs via real `importlib`, not inside the sandbox. It has the same access as any installed Python package.
- **Dependencies**: Skill code can freely import numpy, scipy, PIL, and any other package installed in the backend environment. It cannot import other skills' modules.
- **Data files**: Use `Path(__file__).parent / "data" / "file.json"` to load data files relative to the module. `__file__` is set correctly by the import system.
- **Module names must not collide** with built-in allowed modules (json, numpy, PIL, math, etc.). Collisions are detected at runtime and the skill module is skipped with a warning.
- **Async is fine**: Skill modules can define async functions. Agent code in `run_code` can `await` them.

### SKILL.md for code skills

When a skill provides importable code, the markdown body should document:

1. **What to import** — show the exact import statement
2. **Function signatures** — list available functions with argument types and descriptions
3. **Data format** — what array shapes, dtypes, value ranges functions expect and return
4. **Usage examples** — complete code blocks the agent can adapt

The agent learns about the skill's API by reading the markdown, then uses it in `run_code`. The markdown is the documentation.

## Distribution

### As a zip file

Skills can be distributed as `.zip` files. The zip should contain `SKILL.md` at the top level (or in a subdirectory), plus any companion files including `lib/`. Install via the UI or programmatically with `install_skill_from_file(path)`.

```
my-skill.zip
    SKILL.md
    lib/
        my_lib/
            __init__.py
            ...
```

### Bundled with the app

Place the skill directory in `backend/agent/v2/skills/`. Set `author: system` in frontmatter. The agent discovers and invokes skills dynamically via system reminders.

## Skill lifecycle

1. **Discovery**: Agent sees the skills inventory table (name, description, enabled status, provided imports)
2. **Invocation**: Agent calls `skill(action="invoke", name="...")` to load full content into context
3. **Execution**: Agent uses normal tools (`run_code`, `call_tool`, etc.) guided by the skill's instructions
4. **Creation**: Agent can create new skills via `skill(action="create", ...)`
5. **Forking**: Users can edit bundled skills — the edit creates a user-tier copy

## Checklist for new skills

- [ ] `SKILL.md` has complete frontmatter (name, display_name, description, author, tags)
- [ ] Description is concise enough for the inventory table (~10 words)
- [ ] Markdown body teaches principles, not rigid procedures
- [ ] If the skill has `lib/`: `provides` lists all importable module names
- [ ] If the skill has `lib/`: markdown documents the API with import examples
- [ ] Module names don't collide with built-in modules
- [ ] Tested: enable the skill, run a prompt that exercises it, verify the agent uses it correctly
