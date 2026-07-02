# Stimpack Authoring Guide

The canonical reference for building Stimma stimpacks. Written for humans and
for coding agents — if an agent is building a stimpack for you, point it at
this file (or at https://docs.stimma.ai/stimpacks/creating/ for the hosted
version).

> **For coding agents — paste this to get started:**
>
> Build a Stimma stimpack: a directory with a thin `stimpack.json` manifest
> (`{"name", "display_name", "description", "version", "format": 1, "author",
> "tags"}`) and one skill per folder under `skills/<slug>/SKILL.md`. Each
> SKILL.md has YAML frontmatter (`name`, `display_name`, `description`, `tags`,
> optional `environments:` — `chat`/`flow` booleans, `tool` either `true` or
> `{task_types: [...]}`; omit the block for chat-only — and optional
> `provides:` listing Python modules in a sibling `lib/` dir) followed by a
> markdown body of instructions written like a brief to a capable assistant.
> Validate with `stimma stimpacks validate <pack-dir>`, live-test with
> `stimma stimpacks dev <parent-dir>` (skills reload on edit, no reinstall),
> and ship as a zip of the pack directory. Full spec:
> `docs/STIMPACK_AUTHORING.md` in the stimma repo.

## Concepts

- A **stimpack** is the installable *container* — the unit of browse, install,
  trust, and update. It holds one or more skills today, and is designed to
  carry other typed content later (assets, tools, flows).
- A **skill** is one targeted agent capability: a markdown instruction document
  (plus optional Python) the agent loads into context on demand. The agent
  discovers and invokes skills *flat*, addressed as `<pack>/<skill-slug>`
  (e.g. `stimma-essentials/variations`).
- Skills are **not** required for basic operation — the agent works fine with
  none installed. A skill earns its place by making the agent better at one
  category of work.

## Container format

```
my-stimpack/
    stimpack.json            # pack identity — thin, see below
    skills/                  # one skill per folder
        my-skill/
            SKILL.md         # frontmatter + markdown body
            lib/             # optional bundled Python for this skill
        another-skill/
            SKILL.md
    example.png              # companion files are allowed and preserved
```

### `stimpack.json` (the manifest)

```json
{
  "name": "my-stimpack",
  "display_name": "My Stimpack",
  "description": "One-line description shown on the pack card",
  "version": "1",
  "format": 1,
  "author": "user",
  "tags": ["relevant", "tags"]
}
```

The manifest is deliberately **thin**: pack identity only. Skills are
*discovered* by scanning `skills/*/SKILL.md` — they are not declared in the
manifest — and each skill is self-describing via its own frontmatter, so its
targeting travels with it.

| Field | Required | Notes |
|-------|----------|-------|
| `name` | yes | Kebab-case, globally unique on the marketplace |
| `display_name` | yes | Human-facing name |
| `description` | yes | One-liner for the pack card |
| `version` | yes | Content version (string); the marketplace assigns its own integer publish versions |
| `format` | no | **Container-format version** (integer, default `1`). Loaders warn on packs newer than they support and load best-effort. Always write `1` today. |
| `author` | yes | `user`, `agent`, or `system` (first-party) |
| `tags` | no | Discovery/categorization |
| `resources` | no | Legacy: declares a root-level `skill` resource for single-skill packs (see below). Reserved for future declared resource types. |

### Extensibility contract

This is a container format; extend it without breaking old loaders:

- **New content types get their own typed root** (like `skills/`) and/or a
  `resources` declaration. The loader already recognizes `tool`, `flow`,
  `asset`, `model`, and `flow_guidance` resource types with stub landers —
  they parse today and activate when wired.
- **Unknown manifest fields, frontmatter keys, and resource types are
  ignored** (with a warning), never fatal.
- **Incompatible changes bump `format`.** An old app loads a newer pack
  best-effort and logs a warning telling the user to update.

### Legacy single-skill layout

A pack may instead be a bare root `SKILL.md` (with or without a manifest) —
this is what the in-app editor and the agent's `skill(action="create")` write.
It loads as a one-skill pack whose skill is named after the pack. If both a
root `SKILL.md` and a `skills/` directory exist, `skills/` wins and the root
file is ignored. New multi-skill packs should always use `skills/`.

## SKILL.md

```yaml
---
name: product-photo
display_name: Product Photography
description: Consistent product shots on white backgrounds with soft lighting
author: user
tags: [photography, ecommerce]
environments:
  chat: true
  flow: true
  tool:
    task_types: [text-to-image, image-to-image]
provides:
  - product_photo_utils
---

# Product Photography

Generate product images with studio lighting, white cyclorama background,
and soft shadow. Frame the product centered with 15-20% padding...
```

| Field | Required | Notes |
|-------|----------|-------|
| `name` | yes | Kebab-case; should match the folder slug |
| `display_name` | yes | Shown in skill lists and "Activated skill" indicators |
| `description` | yes | **This is how the agent decides to invoke the skill.** One specific sentence. |
| `author` | yes | `system` (first-party), `user` (edited), or `agent` (auto-created) |
| `tags` | no | |
| `environments` | no | Targeting — see below |
| `provides` | no | Python modules bundled in this skill's `lib/`. Shows as `(imports: ...)` in the skills reminder |

### Targeting (`environments`)

Skills opt into the surfaces where they apply:

- `chat` (boolean) — the main agent conversation. The agent invokes by
  judgment from the description; users can also activate manually from the
  skills menu on the chat input.
- `flow` (boolean) — the flow-building assistant. Strict opt-in: irrelevant
  skills actively hurt flow builds, so only opt in if the skill helps *author
  workflows*.
- `tool` — the assistant on tool screens. `true` for every tool, or
  `{ task_types: [text-to-image, ...] }` to scope it. Tool-surface skills
  **auto-activate** on matching tools; there is no invoke judgment here, so
  the eligibility scope is the relevance gate. The object form is the general
  "narrow it" slot (future keys, e.g. specific tool ids, add no format break).

**Absent key = not offered there. Absent block = chat only** — the right
default for most skills.

### Writing the body

The body is what lands in the agent's context on invoke. Write it like a brief
to a capable assistant who knows Stimma's tools but not your preferences:

- Lead with a one-line summary of what the skill does
- **Teach principles, not rigid steps** — the agent adapts principles;
  procedures break when anything varies
- **Be specific where it matters** — exact values, parameter ranges, model
  preferences
- One minimal example beats several variations; reference the current runtime
  surface by name (`.stimma.tools` imports, `asyncio.gather()`, etc.)
- Keep it focused — one primary workflow per skill; every token rides the
  conversation after invoke

## Skills with Python code (`lib/`)

A skill may bundle Python in its own `lib/` directory:

1. Put modules in `lib/` inside the **skill's** folder
2. Declare them in the skill's frontmatter via `provides: [module_name]`
3. While the skill is active, agent code in `run_code` can `import module_name`

The `lib/` directory acts as a package root: each top-level directory with
`__init__.py` (or top-level `.py` file) becomes an importable module.

```
skills/
    color-math/
        SKILL.md              # provides: [color_math]
        lib/
            color_math/       # <- importable as `color_math`
                __init__.py
                conversions.py
```

Rules:

- **Skill code is trusted** — it runs via real `importlib`, not inside the
  sandbox, with the same access as any installed Python package.
- **Dependencies**: numpy, PIL, and anything else installed in the backend
  environment are importable — including packages like scipy that arrive as
  transitive dependencies of other backend packages, though those aren't
  guaranteed to stick around across versions. This is separate from
  `run_code`'s sandboxed allow-list (a fixed module set that does **not**
  include scipy); `lib/` code runs unsandboxed via real `importlib` and isn't
  bound by that list. Skills cannot import other skills' modules.
- **Data files**: load with `Path(__file__).parent / "data" / "file.json"`.
- **Module names must not collide** with built-in allowed modules (json,
  numpy, PIL, math, ...) or with modules from other active skills — collisions
  are skipped with a warning (first wins).
- **Async is fine** — agent code can `await` your functions.
- **Document the API in the SKILL.md body** — exact import statements,
  function signatures, expected shapes/dtypes/ranges, one complete usage
  example. The markdown *is* the documentation the agent reads.

## Developing and testing

### Without a source checkout (packaged app)

Everything needed ships in the app, anchored on the **Stimpacks** page:

1. **Open Folder** (header button) reveals the profile's stimpacks folder.
   Every child directory is one pack. Drop a pack in — or edit any file in
   place — and it's picked up **live**: the loader re-reads from disk on every
   agent turn, no restart or reinstall.
2. **Validate** (card menu) runs the same checks as the CLI and shows the
   report in-app.
3. Test in a chat: the skills (book icon) menu on the input bar shows what's
   eligible; ask the agent something the skill should shape.
4. **Download as Zip** (card menu) produces the shareable artifact;
   **Publish to Marketplace** (card menu, your own packs) submits it for
   listing — first publishes are moderated before going live.

### With a source checkout

The dev loop, end to end:

```bash
# 1. Scaffold: create <dir>/my-stimpack/{stimpack.json,skills/<slug>/SKILL.md}

# 2. Validate — parses with the app's real loader; errors exit non-zero
stimma stimpacks validate path/to/my-stimpack

# 3. Live-test: point the app at the PARENT directory (each child dir = one pack)
stimma stimpacks dev path/to/dir-containing-packs
#    SKILL.md edits are picked up live — no publish, no reinstall.
#    Open a chat and check the skills (book icon) menu on the input bar;
#    ask the agent something the skill should shape; for tool-targeted
#    skills open a matching tool and check the same menu there.
stimma stimpacks dev --off   # when done (dev packs shadow installed ones by name)

# 4. Package: zip the pack directory (drag-drop the .zip onto the Stimpacks
#    page to install; `Download as Zip` on any card shows the expected shape)
cd path/to/my-stimpack && zip -r ../my-stimpack.zip . -x "*.DS_Store" -x "*__pycache__*"
```

`validate` reports the pack as the agent will see it — every skill with its
per-environment eligibility and resolved lib modules — and catches the common
mistakes: missing descriptions, `provides` naming a module `lib/` doesn't
have, module collisions, unknown `environments` keys, empty bodies, a root
`SKILL.md` shadowed by `skills/`.

## Distribution

- **Marketplace**: use **Publish to Marketplace** on the pack's card in the
  app (requires a signed-in Stimma Cloud account). First publish creates the
  listing and goes through moderation; later publishes bump the version.
  First-party packs live in the sibling `stimma-skills` repo and publish with
  `stimmacloud stimpacks publish`.
- **Direct sharing**: send the zip; recipients drop it on the Stimpacks page.

## Skill lifecycle at runtime

1. **Discovery**: eligible skills are surfaced to the agent per environment
   (name, description, provided imports) via system reminders
2. **Invocation**: the agent calls `skill(action="invoke", name="<pack>/<slug>")`,
   or the user activates from the skills menu; the body lands in context
3. **Execution**: the agent works with its normal tools, guided by the skill
4. **Creation**: the agent can write new single-skill packs via
   `skill(action="create", ...)`

## Checklist for new stimpacks

- [ ] `stimpack.json` has name, display_name, description, version, `format: 1`
- [ ] Every skill folder has a `SKILL.md` with complete frontmatter
- [ ] Each description is one specific sentence (~10 words) — it's the invoke signal
- [ ] `environments` reflects where the skill genuinely helps (default: chat only)
- [ ] Bodies teach principles, not rigid procedures
- [ ] Skills with `lib/`: `provides` lists every importable module, and the body documents the API
- [ ] `stimma stimpacks validate <pack>` passes with no errors
- [ ] Tested live via `stimma stimpacks dev`: the agent invokes it when relevant and the output improves
