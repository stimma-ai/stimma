"""Progressive-disclosure help for Stimma SDK code in run_code sandboxes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SDKMethodHelp:
    name: str
    signature: str
    summary: str
    details: str
    group: str
    is_async: bool


SDK_HELP: dict[str, SDKMethodHelp] = {
    "generated_tools": SDKMethodHelp(
        name="generated_tools",
        signature="from stimma.tools.<category> import <tool_name>",
        summary="Import STP generation tools from the generated .stimma/tools catalog.",
        details="""\
Generation tools are exposed as generated async Python functions.

Workflow:
  1. Inspect .stimma/tools/ to find available task categories.
  2. Inspect .stimma/tools/<category>/ to find real function names.
  3. Import the selected function from stimma.tools.<category>.
  4. Await it with flat keyword arguments.

Example:
  from stimma.tools.text_to_image import flux_schnell

  result = await flux_schnell(prompt="a cat in a garden", width=1024, height=1024)
  stimma.show(result)

Parallel execution:
  Use asyncio.gather() for independent batches such as prompt or seed sweeps.""",
        group="core",
        is_async=True,
    ),
    "project_path": SDKMethodHelp(
        name="project_path",
        signature="stimma.project_path(*parts: str) -> Path",
        summary="Resolve a durable path inside the shared project workspace.",
        details="""\
Use this only in project chats. It returns a Path inside the shared project
workspace, which persists across multiple chats in the same project.

Example:
  manifest_path = stimma.project_path("process", "manifest.json")
  manifest_path.parent.mkdir(parents=True, exist_ok=True)
  manifest_path.write_text("{}")""",
        group="core",
        is_async=False,
    ),
    "show": SDKMethodHelp(
        name="show",
        signature="stimma.show(items, *, title=None)",
        summary="Display media to the user. Sync; do not await.",
        details="""\
Display one or more images/videos to the user. Items can be ToolResult objects,
media IDs, workspace paths, or lists of those values.

Example:
  stimma.show(result, title="Final")
  stimma.show([a, b, c], title="Variations")""",
        group="display",
        is_async=False,
    ),
    "show_grid": SDKMethodHelp(
        name="show_grid",
        signature="stimma.show_grid(items, cols=3, *, title=None)",
        summary="Display media in a grid layout. Sync; do not await.",
        details="""\
Use this for compact comparison sets.

Example:
  stimma.show_grid(results, cols=3, title="Prompt sweep")""",
        group="display",
        is_async=False,
    ),
    "library.search": SDKMethodHelp(
        name="library.search",
        signature="await stimma.library.search(query: str, *, limit=20)",
        summary="Semantic/text search of the media library.",
        details="""\
Find existing media before generating or editing.

Example:
  cats = await stimma.library.search("cats", limit=10)""",
        group="library",
        is_async=True,
    ),
    "library.browse": SDKMethodHelp(
        name="library.browse",
        signature="await stimma.library.browse(**filters)",
        summary="Browse library media with structured filters.",
        details="""\
Use browse when the user asks for recent items, media types, tags, or other
library filters rather than a semantic query.""",
        group="library",
        is_async=True,
    ),
    "library.get": SDKMethodHelp(
        name="library.get",
        signature="await stimma.library.get(media_id: int)",
        summary="Load metadata for one media item.",
        details="""\
Use get when you already know the media ID and need its metadata or workspace
file path.""",
        group="library",
        is_async=True,
    ),
    "library.save": SDKMethodHelp(
        name="library.save",
        signature="await stimma.library.save(item, tags=None, sources=None, inspired_by=None)",
        summary="Save workspace files or generated results to the media library.",
        details="""\
Library save is explicit. Generated results shown with stimma.show() may be
displayed to the user, but save when the user asks to keep a durable asset.
When saving an image you composed or edited in code (a path rather than a
ToolResult), pass sources=[media_id, ...] for the images it was made from so
the derivation shows up in lineage. ToolResults carry their own provenance.""",
        group="library",
        is_async=True,
    ),
    "library.lineage": SDKMethodHelp(
        name="library.lineage",
        signature="await stimma.library.lineage(media_id: int)",
        summary="Return provenance for a media item.",
        details="""\
Use lineage when the user asks where an asset came from, what tool made it, or
which source images were used.""",
        group="library",
        is_async=True,
    ),
    "library.generation_params": SDKMethodHelp(
        name="library.generation_params",
        signature="await stimma.library.generation_params(media_id: int)",
        summary="Get reusable generation parameters for an existing media item.",
        details="""\
Use this before regenerating, remixing, or making controlled variations from an
existing generated item.""",
        group="library",
        is_async=True,
    ),
    "library.regenerate": SDKMethodHelp(
        name="library.regenerate",
        signature="await stimma.library.regenerate(media_id: int, **overrides)",
        summary="Regenerate an item with optional parameter overrides.",
        details="""\
Use this when the user asks for another version of an existing generated image
and wants to preserve most of its original generation setup.""",
        group="library",
        is_async=True,
    ),
    "llm": SDKMethodHelp(
        name="llm",
        signature="await stimma.llm(prompt: str, *, images=None)",
        summary="Ask the configured language model for text or vision reasoning.",
        details="""\
Use stimma.llm() for local reasoning inside a code workflow, especially prompt
rewriting or structured summaries. Pass images only when needed.""",
        group="ai",
        is_async=True,
    ),
    "progress": SDKMethodHelp(
        name="progress",
        signature="stimma.progress(iterable, *, desc=None)",
        summary="Wrap loops so progress appears in the chat UI.",
        details="""\
Use progress for long loops that produce visible stages for the user.""",
        group="core",
        is_async=False,
    ),
    "detect_faces": SDKMethodHelp(
        name="detect_faces",
        signature="await stimma.detect_faces(media_id: int)",
        summary="Detect faces in a library image.",
        details="""\
Use this for face-aware workflows such as cropping, matching, or portrait
selection.""",
        group="image",
        is_async=True,
    ),
    "adjust": SDKMethodHelp(
        name="adjust",
        signature="stimma.adjust(image, **edits)",
        summary="Apply simple local image edits such as filters and levels.",
        details="""\
Use this for local image adjustments in PIL/numpy workflows rather than calling a
generation provider.""",
        group="image",
        is_async=False,
    ),
    "filters": SDKMethodHelp(
        name="filters",
        signature="stimma.filters -> list[str]",
        summary="List available filter preset names for stimma.adjust(filter=...).",
        details="""\
Example:
  print(stimma.filters)""",
        group="image",
        is_async=False,
    ),
}


_GROUP_ORDER = ["core", "display", "library", "image", "ai"]
_GROUP_LABELS = {
    "core": "Core",
    "display": "Display",
    "library": "Library",
    "image": "Image",
    "ai": "AI",
}
_GROUP_DESCRIPTIONS = {
    "core": "generated tools, parallel batches, progress, shared project paths",
    "display": "show, show_grid",
    "library": "search, browse, get, save, lineage, regeneration",
    "image": "adjust, filters, detect_faces",
    "ai": "llm text and vision reasoning",
}


def get_sdk_overview() -> str:
    """Compact group index for the retired sdk_help wrapper."""
    lines = ["stimma SDK - available method groups:", ""]
    for group in _GROUP_ORDER:
        label = _GROUP_LABELS[group]
        desc = _GROUP_DESCRIPTIONS.get(group, "")
        lines.append(f"  {label} - {desc}")
    lines.append("")
    lines.append('Call sdk_help("<group>") to see methods in a group, e.g. sdk_help("core").')
    lines.append('Call sdk_help("<method>") for method docs, e.g. sdk_help("generated_tools").')
    return "\n".join(lines)


def get_sdk_group_help(group: str, methods: list[SDKMethodHelp]) -> str:
    """Method names, signatures, and summaries for a group."""
    label = _GROUP_LABELS.get(group, group)
    lines = [f"{label} methods:", ""]
    for method in methods:
        async_note = " (async)" if method.is_async else " (sync)"
        lines.append(f"  {method.signature}{async_note}")
        lines.append(f"    {method.summary}")
    lines.append("")
    lines.append(f'Call sdk_help("<method>") for details, e.g. sdk_help("{methods[0].name}").')
    return "\n".join(lines)


def get_sdk_method_help(name: str) -> str:
    """Return help for a method, group, or namespace prefix."""
    if name in SDK_HELP:
        method = SDK_HELP[name]
        return f"{method.signature}\n\n{method.details}"

    name_lower = name.lower()
    group_methods = [method for method in SDK_HELP.values() if method.group == name_lower]
    if group_methods:
        return get_sdk_group_help(name_lower, group_methods)

    prefix_methods = [method for method in SDK_HELP.values() if method.name.startswith(name + ".")]
    if prefix_methods:
        return get_sdk_group_help(prefix_methods[0].group, prefix_methods)

    groups = ", ".join(_GROUP_ORDER)
    methods = ", ".join(sorted(SDK_HELP))
    return f"Unknown SDK help topic: {name}. Groups: {groups}. Methods: {methods}"


def get_sdk_quick_ref() -> str:
    """Minimal SDK reference appended to run_code errors for self-correction."""
    return """\
stimma quick reference (inside run_code / run_file):
  Generation tools are imported by their REAL function name from the catalog.
  First read .stimma/tools/<category>/ (ls/cat) to get the exact name, then:
    from stimma.tools.<category> import <name_from_catalog>
    r = await <name_from_catalog>(prompt="a cat", width=1024)   # r.media_id, r.path, r.seed
  stimma.show(r) to display; asyncio.gather() for parallel batches.
  stimma.* also has: .library (search/get/save), .llm(), .show(), .detect_faces().
NOT available in run_code (use as agent tools outside run_code): create_layout, bash, view_image, ask_user, browse_web, skill"""
