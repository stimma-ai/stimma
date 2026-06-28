# Agent V2 Principles

This document defines the design philosophy and operating principles for the Stimma agent v2. It is the authoritative reference for anyone working on agent prompts, tools, stimpacks, or bug fixes.

**Read this before changing the system prompt or fixing agent behavior bugs.**

## Core Philosophy

The v1 agent was a pattern-matching machine with a 20k token system prompt. It could only do what was explicitly encoded as examples. V2 is a Claude Code-style agentic loop where the model's intelligence does the work, tools provide capabilities, and stimpacks load on demand.

### The Six Principles

1. **Progressive disclosure over massive system prompts.** Don't front-load information. Let the agent discover what it needs through the `.stimma/tools` generated catalog, focused runtime APIs, and stimpacks.

2. **The model explores rather than following rigid patterns.** The agent should understand *why* to do something, not memorize *how*. Teach principles, not procedures.

3. **~10 core tools, not 50 specialized ones.** Compose behavior from general-purpose tools. A new capability should be a stimpack or a tool parameter, not a new tool.

4. **Code execution for batch/complex workflows instead of a DAG planner.** `run_code` with the `stimma` SDK replaces the v1 plan-and-execute model for anything beyond single tool calls.

5. **Stimpacks for reusable domain knowledge, not hardcoded examples.** Domain-specific workflows belong in stimpack documents that load on demand, not in the system prompt.

6. **Start minimal, grow reactively.** Add to the system prompt only when the agent repeatedly gets something wrong *and* there's no better place for the fix.

## Anti-Patterns

These are the failure modes that erode the agent over time. Recognizing them is as important as knowing the principles.

### "DO NOT" / "CRITICAL" / "IMPORTANT" accumulation

**The problem:** A bug is found — the agent does X wrong. The fix: add `CRITICAL: NEVER do X` to the prompt. Next bug: add another. The prompt grows, each directive competes for attention, and the agent becomes *worse* at general reasoning because its context is full of negative constraints.

**Why it fails:** LLMs don't reliably follow negative instructions. A list of 20 things not to do is harder to follow than a clear explanation of what *to* do and why. Negative rules also don't compose — "NEVER use view_image before controlnet" and "ALWAYS view_image to understand user intent" create contradictions that the model resolves arbitrarily.

**What to do instead:**
- Ask *why* the agent made the mistake. Usually it lacks context, not rules.
- If it's a tool misuse: improve the tool description or schema, or add a guard in the tool implementation itself.
- If it's a domain knowledge gap: write or update a stimpack.
- If it's a general reasoning failure: write a short *positive* principle that explains the right mental model ("ControlNet strips everything except structure — prompt for the *target* image, not the reference").
- If it truly must be in the system prompt: state it as a positive principle with a *why*, not a bare prohibition.

### Example overload

**The problem:** The prompt includes detailed code examples for how to handle various scenarios. The agent learns to pattern-match against examples instead of reasoning from principles. When it encounters a case that doesn't match an example, it either forces the closest example or fails.

**Why it fails:** Examples teach *what*, not *why*. An agent that has memorized "for 5+ images use `asyncio.gather()`" will use `gather` for 5 sequential-dependency steps because it matched on count, not on the actual criterion (independence). Examples also bloat the prompt — each one costs tokens that could be spent on the actual conversation.

**What to do instead:**
- State the principle: "Use parallel execution (`asyncio.gather`) when items are independent; use sequential loops when each step depends on the previous."
- Put code examples in `.stimma/tools` generated stubs or in stimpacks, not in the system prompt.
- If an example is truly needed for clarity, use *one* minimal example, not several variations.

### Prompt-level fixes for code-level problems

**The problem:** The agent passes wrong parameters to a tool. Fix: add a prompt rule "always pass X as Y." But this should be enforced in code — validate in the tool, raise a clear error, or fix the schema.

**Why it fails:** The model might not attend to that prompt line on every call. Code-level validation is 100% reliable; prompt-level is probabilistic.

**What to do instead:**
- Fix the tool schema to make the right usage obvious.
- Add input validation that raises clear errors.
- Use type coercion in the tool implementation where safe.

### Context pollution

**The problem:** The system prompt grows to thousands of tokens of behavioral rules, tool documentation, edge cases, and examples. The model spends its attention budget parsing instructions instead of thinking about the user's actual request.

**Why it fails:** Attention is finite. A 600-token prompt with clear principles outperforms a 3000-token prompt with exhaustive rules, because the model can hold the principles in working memory while reasoning about the task.

**What to do instead:**
- Audit the system prompt regularly. If a section hasn't prevented a bug in weeks, consider removing it.
- Move domain knowledge to stimpacks (loaded on demand).
- Move tool documentation to `.stimma/tools` generated stubs and focused helper surfaces (loaded on demand).
- Keep the system prompt under ~800 tokens of actual guidance (excluding dynamic sections like tool preferences and stimpack content).

## Diagnosis Checklist

When the agent misbehaves, work through this before touching the system prompt:

1. **Is it a tool/schema problem?** Can the tool validate its inputs better? Is the schema misleading?
2. **Is it a missing stimpack?** Would a stimpack document give the agent the domain knowledge it needs?
3. **Is it a coverage gap?** Add a regression test so the fix is verifiable and stays fixed.
4. **Is it a one-off?** Some failures are stochastic. If the agent gets it right 9/10 times, adding a prompt rule for the 1/10 case may hurt the 9/10.
5. **Is it truly a prompt problem?** If yes — write a short positive principle with a *why*. No bare "DO NOT" lines.

## Architecture

### Workspace Model

Claude Code-style filesystem access. The agent operates on the real filesystem with permission prompts for sensitive operations.

- **Session workspace**: temp directory per chat, created on agent start, serves as cwd
- **Workspace files are just files** — Python can glob, PIL can open, the agent can view them
- **Library save is explicit** — nothing auto-saves to the user's media library
- **Bash access** — permission-gated shell for ImageMagick, ffmpeg, etc.

### Core Tool Surface

| # | Tool | Purpose |
|---|------|---------|
| 1 | **run_code** | Execute Python in sandbox. Batch ops, PIL, loops, grids, and `.stimma/tools` STP calls. |
| 2 | **view_image** | Send image pixels to LLM (multimodal). Agent sees with its own eyes. |
| 3 | **show** | Display one or more media items to user in chat. Creates ChatItems. |
| 4 | **library** | Search, get, save, browse, lineage. One tool, multiple actions. |
| 5 | **bash** | Shell commands. Permission-gated. |
| 6 | **web_search** | Search the web. Returns titles, URLs, and snippets. |
| 7 | **web_fetch** | Fetch a URL and extract readable content. |
| 8 | **ask_user** | Ask user for clarification, preferences, approval. |
| 9 | **stimpack** | Invoke a stimpack. Meta-tool that loads instructions into context. |
| 10 | **delegate** | Spawn subagent for bulk/isolated work. |

### Progressive Disclosure for STP Tools

The agent drills down as needed:

1. **Task categories** in system prompt (~100 tokens): "text-to-image, image-to-image, ..."
2. **Browse `.stimma/tools/<task_type>/`** -> generated modules with tool names and one-line descriptions
3. **Open a generated tool module** -> typed async function, parameter docs, and enum discovery hints
4. **Use the helper named by the generated stub** -> search large enum values such as loras, checkpoints, and samplers

Large enum parameters are NOT inlined in generated stubs. The stub points to the focused helper for finding values.

### Code Execution (run_code)

The agent writes Python, we `exec()` it with a `stimma` API object injected.

**The `stimma` API:**
```python
# STP tool calls
from stimma.tools.text_to_image import turbo_gen

result = await turbo_gen(prompt="a cat")
# result is a ToolResult with path, dimensions, seed, parameters, etc.
result.open()  # -> PIL.Image.Image

# Library
items = await stimma.library.search("cats", limit=10)
await stimma.library.save(result)
await stimma.library.save("composite.png", tags=["composite"])
media = await stimma.library.get(media_id=42)

# LLM
response = await stimma.llm("Write a detailed prompt for: a cat in a cyberpunk city")
response = await stimma.llm("Describe this image", images=["photo.png"])

# Display to user
stimma.show("result.png")
stimma.show(["a.png", "b.png", "c.png"])
stimma.show_grid(["a.png", "b.png", "c.png"], cols=3)
```

**ToolResult:**
```python
@dataclass
class ToolResult:
    path: Path
    width: int | None
    height: int | None
    seed: int | None
    tool_name: str
    parameters: dict
    duration_ms: int

    def open(self) -> PIL.Image.Image: ...
```

**Sandbox constraints:**
- Restricted globals: only stimma API, standard lib, PIL, numpy
- Async execution on separate task
- Timeout
- Session workspace as cwd

**Whitelisted imports:** PIL/Pillow, numpy, pathlib, json, math, random, itertools, collections, re, os.path (not full os), aiohttp, urllib/urllib.parse/urllib.request

### Multimodal Vision

Use `view_image` tool to see image pixels directly in the agent's context. Downscales to ~512px by default, or use `detail="high"` for 1024px.
- **view_image** (context cost) -> when agent needs to reason visually

**Bulk review:** Delegate to a subagent. Don't view 50 images in the main context.

### Lineage / Provenance

Tracked automatically at the `stimma` API layer:
- Generated `.stimma.tools` calls record "output X was produced from input Y using tool Z with params W"
- `library.save()` carries provenance chain from ToolResult
- `library.save()` accepts optional `inspired_by` for looser remix links
- `library(action="lineage", media_id=42)` returns the full derivation tree

The agent and user code don't have to bookkeep lineage — it's automatic.

### Stimpacks System

Stimpacks are markdown instruction documents that load into context on demand. Stimpacks can optionally bundle a `lib/` directory with Python modules that become importable in `run_code` when the stimpack is enabled.

**See `docs/STIMPACK_AUTHORING.md` for the full authoring guide.**

**Three tiers:**
- **Dev** — sibling checkout for built-in stimpacks during development (`../stimma-skills`, enabled with `stimma stimpacks dev`), read-only in the app
- **User-created** — in app data directory, read-write
- **Agent-created** — same location, written by the agent to capture learned workflows

**Lifecycle:** Discovery (name + description index) -> Invocation (full content loads) -> Execution (agent uses normal tools) -> Creation (agent writes new stimpack file)

**Key properties:**
- Instruction templates that make the agent smarter
- Can include Python code via `lib/` directory (declared with `provides:` in frontmatter)
- Not required for basic operation
- Agent can create/fork/modify its own stimpacks
- Frontmatter is advisory (e.g., "requires comfyui provider"), not enforced structurally

### System Prompt

Keep it compact. Three layers:

1. **Identity + boundaries** (~200 tokens): Who you are, what you can do, workspace model
2. **Tool behavior guidance** (~300 tokens): When to use which tool, progressive disclosure strategy
3. **Task categories** (~100 tokens): Just names of available task types and the `.stimma/tools` entry point

**What stays OUT:** Workflow examples, tool parameter details, lora/model lists, prompt engineering advice, edge case handling. All of that is stimpacks territory or progressive disclosure.


## The Flow Agent

The flow agent should adhere to the above principles with one exception: It's system prompt includes an embedded "stimpack" for working on flow programs. So the length limit does not apply, and it's OK for it to explain "how" a little bit more. It should still avoid pitfalls like lots of negative instructions, etc. Just keep this in mind when working over there.
