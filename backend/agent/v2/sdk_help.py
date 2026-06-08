"""Progressive-disclosure help for the Stimma SDK inside run_code sandboxes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SDKMethodHelp:
    name: str
    signature: str
    summary: str
    details: str
    group: str  # "core" | "library" | "display" | "ai"
    is_async: bool


SDK_HELP: dict[str, SDKMethodHelp] = {
    "call_tool": SDKMethodHelp(
        name="call_tool",
        signature="await stimma.call_tool(tool_id: str, **kwargs) -> ToolResult",
        summary="Execute a generation tool. Returns a ToolResult with .media_id, .path, .seed.",
        details="""\
Execute a generation tool (text-to-image, image-to-image, etc.).

Parameters:
  tool_id (str): The tool identifier, e.g. "comfyui:flux-klein-9b".
  **kwargs: Flat keyword arguments — prompt, width, height, seed, steps, cfg, loras, etc.
            Do NOT use nested dicts like inputs={} or parameters={}.
  controlnet (str, optional): Preprocessor to apply to input_images before generation.
            One of: canny, depth, lineart, lineart_realistic, lineart_anime, pose, pose_hands.
            Preprocessing happens automatically — no need to call preprocess_controlnet separately.

Returns:
  ToolResult with attributes:
    .media_id (int)   — library ID of the generated media
    .path (Path)      — workspace file path
    .seed (int|None)  — generation seed (for reproducibility)
    .width, .height   — dimensions
    .open()           — returns a PIL.Image.Image

Example:
  result = await stimma.call_tool("comfyui:flux-klein-9b",
      prompt="a cat in a garden", width=1024, height=1024)
  print(result.media_id, result.seed)

ControlNet example:
  result = await stimma.call_tool("comfyui:flux2-dev",
      prompt="cyberpunk warrior", input_images=[123], controlnet="pose")

Parallel execution:
  For independent batch work (seed sweeps, multiple prompts), use asyncio.gather():
    results = await asyncio.gather(
        stimma.call_tool("tool_id", prompt="cat", seed=1),
        stimma.call_tool("tool_id", prompt="cat", seed=2),
        stimma.call_tool("tool_id", prompt="cat", seed=3),
    )


Gotchas:
  - All params are flat kwargs, NOT nested dicts.
  - Always await — forgetting await returns a coroutine, not the result.
  - Omit seed for a random result each time (the default). Only pass seed
    when the user wants reproducibility or you're isolating a single variable.
  - Only pass: prompt, seed, loras, input_images, width/height, controlnet.
    All other parameters use optimal schema defaults automatically.
  - Use get_schema(tool_id) in the agent to discover available parameters.
  - Safe for concurrent use — multiple call_tool() calls can run in parallel.""",
        group="core",
        is_async=True,
    ),
    "preprocess_controlnet": SDKMethodHelp(
        name="preprocess_controlnet",
        signature="await stimma.preprocess_controlnet(media_id: int, preprocessor: str, params: dict | None = None) -> ControlNetInput",
        summary="Preprocess an image for controlnet workflows. Usually not needed — call_tool handles this automatically via controlnet= param.",
        details="""\
NOTE: call_tool now handles controlnet preprocessing automatically when you pass
controlnet="pose" (or canny, depth, etc.) alongside input_images. Use this method
only for advanced cases where you need the control map for inspection or multi-step workflows.

Returns a ControlNetInput that can be passed directly in input_images to call_tool.
The SDK automatically handles lineage metadata when ControlNetInput objects are used.

Preprocessors: canny, depth, lineart, lineart_realistic, lineart_anime, pose, pose_hands.

Parameters:
  media_id (int): Library media ID of the source image.
  preprocessor (str): One of the preprocessor types listed above.
  params (dict, optional): Preprocessor-specific params (e.g. {"low": 100, "high": 200} for canny).

Returns:
  ControlNetInput with attributes:
    .preprocessed_path (str) — path to the control map image
    .original_media_id (int) — source media ID
    .preprocessor (str) — preprocessor used
    .width, .height (int) — dimensions of the control map

Simpler alternative (preferred):
  result = await stimma.call_tool("comfyui:flux2-dev",
      prompt="cyberpunk warrior", input_images=[123], controlnet="pose")

Explicit use (advanced):
  cn = await stimma.preprocess_controlnet(media_id=123, preprocessor="pose")
  # Inspect the control map
  Image.open(cn.preprocessed_path).show()
  result = await stimma.call_tool("comfyui:flux2-dev",
      prompt="cyberpunk warrior", input_images=[cn])
  stimma.show(result)""",
        group="core",
        is_async=True,
    ),
    "project_path": SDKMethodHelp(
        name="project_path",
        signature="stimma.project_path(*parts: str) -> Path",
        summary="Resolve a path inside the shared project workspace for durable cross-chat files.",
        details="""\
Use this only in project chats. It returns a Path inside the shared project workspace,
which persists across multiple chats in the same project.

Example:
  manifest_path = stimma.project_path("process", "manifest.json")
  manifest_path.parent.mkdir(parents=True, exist_ok=True)
  manifest_path.write_text("{}")

Gotchas:
  - This is sync — do NOT await it.
  - It raises if the current chat is not attached to a project.
  - Relative open() calls still default to the chat workspace; use this when you
    intentionally want durable shared project state.""",
        group="core",
        is_async=False,
    ),
    "show": SDKMethodHelp(
        name="show",
        signature="stimma.show(items, *, title=None)",
        summary="Display media to the user. Sync — no await needed.",
        details="""\
Display one or more images/videos to the user.

Parameters:
  items: A single item or list of items. Each item can be:
    - ToolResult (from call_tool)
    - int (media_id)
    - str or Path (workspace filename)
  title (str, optional): Display title.

Also accepts keyword args for convenience:
  stimma.show(media_id=123)
  stimma.show(media_ids=[1, 2, 3])
  stimma.show(path="output.png")
  stimma.show(paths=["a.png", "b.png"])

Example:
  results = [await stimma.call_tool(...) for _ in range(4)]
  stimma.show(results, title="Variations")

Gotchas:
  - This is SYNC — do NOT await it.
  - Workspace files shown via stimma.show() are auto-saved to library.
  - Prefer one show() call with a list over multiple single-item calls.""",
        group="display",
        is_async=False,
    ),
    "show_grid": SDKMethodHelp(
        name="show_grid",
        signature="stimma.show_grid(items, cols=3, *, title=None)",
        summary="Display items as a grid layout. Sync — no await needed.",
        details="""\
Display items in a grid layout.

Parameters:
  items: Iterable of ToolResult, int (media_id), str, or Path.
  cols (int): Number of columns (default 3).
  title (str, optional): Display title.

Example:
  stimma.show_grid(results, cols=2, title="Before / After")

Gotchas:
  - This is SYNC — do NOT await it.""",
        group="display",
        is_async=False,
    ),
    "library.search": SDKMethodHelp(
        name="library.search",
        signature="await stimma.library.search(query: str, limit=20, tags=None) -> list[dict]",
        summary="Search library by text query. Returns list of media info dicts.",
        details="""\
Search the media library by text query (semantic + keyword).

Parameters:
  query (str): Search text.
  limit (int): Max results (default 20).
  tags (list[str], optional): Filter by tags.

Returns:
  List of dicts, each with keys like: media_id, filename, tags, created_at, etc.

Example:
  cats = await stimma.library.search("orange cat", limit=5)
  for item in cats:
      print(item["media_id"], item["filename"])""",
        group="library",
        is_async=True,
    ),
    "library.browse": SDKMethodHelp(
        name="library.browse",
        signature="await stimma.library.browse(limit=20, tags=None) -> list[dict]",
        summary="Browse recent library items. Returns list of media info dicts.",
        details="""\
Browse recent items in the library (no query, just recency).

Parameters:
  limit (int): Max results (default 20).
  tags (list[str], optional): Filter by tags.

Returns:
  List of dicts with media info (same shape as library.search results).

Example:
  recent = await stimma.library.browse(limit=10)""",
        group="library",
        is_async=True,
    ),
    "library.get": SDKMethodHelp(
        name="library.get",
        signature="await stimma.library.get(media_id: int) -> dict",
        summary="Retrieve a single media item and copy it into the workspace.",
        details="""\
Retrieve a media item by ID. Copies the file into the workspace so you can
open it with PIL, pass it to tools, etc.

Parameters:
  media_id (int): The library media ID.

Returns:
  Dict with keys:
    "media_id"  — the ID
    "filename"  — workspace-relative filename
    "path"      — absolute path to the workspace copy

Example:
  info = await stimma.library.get(123)
  img = Image.open(info["path"])""",
        group="library",
        is_async=True,
    ),
    "library.save": SDKMethodHelp(
        name="library.save",
        signature="await stimma.library.save(item, tags=None, inspired_by=None) -> dict",
        summary="Save a workspace file or ToolResult to the library.",
        details="""\
Save media to the library with optional tags and lineage.

Parameters:
  item: ToolResult, str (filename), or Path. ToolResults auto-inherit provenance.
  tags (list[str], optional): Tags to apply. Only pass when the user explicitly requests tagging.
  inspired_by (int | list[int], optional): Media IDs that inspired this item.

Returns:
  Dict with "media_id", "filename", etc.

Example:
  result = await stimma.call_tool(...)
  saved = await stimma.library.save(result)
  print(saved["media_id"])""",
        group="library",
        is_async=True,
    ),
    "library.lineage": SDKMethodHelp(
        name="library.lineage",
        signature="await stimma.library.lineage(media_id: int) -> dict",
        summary="Get the generation lineage/provenance of a media item.",
        details="""\
Retrieve the full generation history of a media item — what tool created it,
what parameters were used, and what source images it derived from.

Parameters:
  media_id (int): The library media ID.

Returns:
  Dict with lineage info (tool_id, parameters, source_media_ids, etc.).

Example:
  history = await stimma.library.lineage(42)
  print(history)""",
        group="library",
        is_async=True,
    ),
    "library.generation_params": SDKMethodHelp(
        name="library.generation_params",
        signature="await stimma.library.generation_params(media_id: int) -> dict",
        summary="Get a call_tool-ready recipe that reproduces an existing image.",
        details="""\
Return the exact inputs needed to reproduce an existing image, already in
call_tool shape — no manual remapping. This is the way to remix an image:
get its recipe, change one field, resubmit.

Parameters:
  media_id (int): The library media ID to reproduce.

Returns:
  A flat dict spreadable straight into call_tool, with keys such as:
    tool_id, prompt, negative_prompt, seed (top level), width, height,
    loras (as [{"path": ..., "weight": ...}]), input_images (for
    image-to-image sources), plus any stored steps/cfg/sampler/etc.
  Imported/external images have no tool_id — you must choose one yourself.

Example (same image, different LoRA, same seed):
  p = await stimma.library.generation_params(123)
  p["loras"] = [{"path": "new_style"}]
  result = await stimma.call_tool(**p)
  stimma.show(result)

Gotchas:
  - Seed is included for faithful reproduction. To vary the seed instead,
    set p["seed"] = None (random) or a specific value.
  - For a one-liner, prefer stimma.library.regenerate(media_id, **overrides).""",
        group="library",
        is_async=True,
    ),
    "library.regenerate": SDKMethodHelp(
        name="library.regenerate",
        signature="await stimma.library.regenerate(media_id: int, **overrides) -> ToolResult",
        summary="Reproduce an existing image, overriding any fields you pass.",
        details="""\
One-liner remix: fetches the recipe (see generation_params), applies your
overrides, and calls the original tool. Returns a ToolResult.

Parameters:
  media_id (int): The library media ID to reproduce.
  **overrides: Flat kwargs to change — loras=, prompt=, seed=, width=, etc.
               Pass seed=None for a fresh random seed.

Examples:
  # Same image, new LoRA, same seed:
  result = await stimma.library.regenerate(123, loras=[{"path": "new_style"}])

  # Same recipe, ten outfit variations:
  outfits = ["red dress", "leather jacket", "business suit"]
  results = await asyncio.gather(*[
      stimma.library.regenerate(123, prompt=base_prompt + ", wearing " + o, seed=None)
      for o in outfits
  ])
  stimma.show(results)

Gotchas:
  - Raises if the image has no recorded tool (imported) — pass tool_id= then.
  - Always await; safe for concurrent use inside asyncio.gather.""",
        group="library",
        is_async=True,
    ),
    "create_parameter_sweep": SDKMethodHelp(
        name="create_parameter_sweep",
        signature="await stimma.create_parameter_sweep(media_ids, rows, cols, row_headers, col_headers, title, description='') -> dict",
        summary="Assemble a labeled comparison grid (.stimmagrid.json) from a parameter sweep the user requested. Owned by the parameter-grid skill — invoke that skill first; it confirms the sweep axes before any generation.",
        details="""\
Create a .stimmagrid.json MediaItem from images generated by systematically
varying two or more parameter axes (e.g. LoRA strength × prompt, model × seed).
This is a deliberate comparison artifact the user explicitly asks for. The
parameter-grid skill owns the end-to-end workflow — gathering the axes,
confirming the plan with the user, then assembling — so invoke that skill
rather than calling this directly. To present several ordinary results, use
stimma.show([...]); for a named collection, use stimma.create_set().

Cell images are superseded (hidden from browse, visible in grid context).

Parameters:
  media_ids: List of ToolResult or int (media_id) in row-major order.
             Length must equal rows * cols.
  rows (int): Number of rows.
  cols (int): Number of columns.
  row_headers (list[str]): Labels for each row. Length must equal rows.
  col_headers (list[str]): Labels for each column. Length must equal cols.
  title (str): Grid title.
  description (str, optional): What the grid compares.

Returns:
  Dict with keys:
    "media_id" (int)           — the grid's library media ID
    "title" (str)              — grid title
    "description" (str)        — grid description
    "rows" (int)               — number of rows
    "cols" (int)               — number of columns
    "row_headers" (list[str])  — row labels
    "col_headers" (list[str])  — column labels
    "cell_count" (int)         — total number of cells

Example (parameter sweep):
  # Build coroutines in column-major order (group by LoRA/param to minimize switching)
  strengths = [0.5, 0.75, 1.0]
  indexed = []
  for col, strength in enumerate(strengths):        # outer = column (param being swept)
      for row, prompt in enumerate(prompts):         # inner = row (prompt)
          coro = stimma.call_tool("comfyui:flux-dev", prompt=prompt,
              loras=[{"path": "style.safetensors", "weight": strength}])
          indexed.append((row, col, coro))

  all_results = await asyncio.gather(*[c for _,_,c in indexed])

  # Reorder to row-major, then assemble
  cells = [[None]*len(strengths) for _ in prompts]
  for (r, c, _), res in zip(indexed, all_results):
      cells[r][c] = res
  grid = await stimma.create_parameter_sweep(
      media_ids=[r for row in cells for r in row], rows=len(prompts), cols=len(strengths),
      row_headers=["Prompt 1", "Prompt 2"],
      col_headers=["0.5", "0.75", "1.0"],
      title="LoRA Strength Sweep"
  )
  stimma.show(grid)
  print(f"Grid created: {grid['media_id']}, {grid['rows']}x{grid['cols']}")

Gotchas:
  - media_ids must be in row-major order (all cols for row 0, then row 1, etc.).
  - Cell images become superseded — they won't appear in library browse individually.
  - The grid itself appears as a single item in the library.""",
        group="library",
        is_async=True,
    ),
    "create_set": SDKMethodHelp(
        name="create_set",
        signature="await stimma.create_set(items, title=None) -> int",
        summary="Group media items into a set. Returns the set's media_id.",
        details="""\
Group multiple media items into a single set that appears as one item
in library browse. Individual members are hidden from browse.

Parameters:
  items: Iterable of ToolResult or int (media_id).
  title (str, optional): Set title.

Returns:
  int — the set's media_id.

Example:
  results = await asyncio.gather(*[
      stimma.call_tool("comfyui:flux-klein-9b", prompt=p) for p in prompts
  ])
  set_id = await stimma.create_set(results, title="Cat variations")
  stimma.show(set_id)""",
        group="library",
        is_async=True,
    ),
    "llm": SDKMethodHelp(
        name="llm",
        signature="await stimma.llm(prompt: str, images=None) -> str",
        summary="Call an LLM for text generation or vision tasks.",
        details="""\
Send a prompt (and optionally images) to an LLM and get a text response.
Useful for generating prompts, analyzing images, classification, etc.

Parameters:
  prompt (str): The text prompt.
  images (list[str|Path], optional): Workspace image paths to include.

Returns:
  str — the LLM's text response.

Example:
  description = await stimma.llm("Describe this image in detail",
      images=["photo.png"])
  prompts = await stimma.llm("Generate 5 creative prompts for cat paintings")""",
        group="ai",
        is_async=True,
    ),
    "progress": SDKMethodHelp(
        name="progress",
        signature="tqdm(iterable, desc=None) / tqdm(total=N, desc=None)",
        summary="Progress bars use tqdm (available via `from tqdm import tqdm`).",
        details="""\
Progress bars use the standard tqdm API. `from tqdm import tqdm` is available
in the sandbox — it renders a live progress bar in the chat UI.

Example (wrap an iterable):
  from tqdm import tqdm
  results = []
  for prompt in tqdm(prompts, desc="Generating"):
      r = await stimma.call_tool("comfyui:flux-klein-9b", prompt=prompt)
      results.append(r)
  stimma.show(results)

Preview thumbnails are added automatically — every stimma.call_tool()
result is attached to the active progress bar as a preview.

stimma.progress() also works as an alias:
  stimma.progress(prompts, desc="Working")  # wraps iterable
  stimma.progress(10, desc="Working")       # manual, total=10

For parallel work, asyncio.gather() creates a progress bar automatically:
  results = await asyncio.gather(*coros)""",
        group="display",
        is_async=False,
    ),
    "batch": SDKMethodHelp(
        name="batch",
        signature="Batch generation patterns (5+ images)",
        summary="Patterns for generating multiple images efficiently in run_code.",
        details="""\
When generating 5+ images, use run_code instead of repeated individual call_tool turns.

Principle: use asyncio.gather for parallel work when items are independent;
use a sequential loop when each step depends on the previous result.

IMPORTANT: Always call stimma.show() INSIDE run_code — never defer display
to a separate show tool call afterward. run_code has the actual ToolResult
objects with correct media IDs; outside run_code those IDs are lost.

Parallel (preferred for independent work — much faster):
  prompts = ["a cat", "a dog", "a bird", "a fish", "a horse"]
  results = await asyncio.gather(*[
      stimma.call_tool("comfyui:flux-klein-9b", prompt=p) for p in prompts
  ])
  stimma.show(results, title="Animals")

Sequential (when each step depends on the previous):
  results = []
  for prompt in tqdm(prompts, desc="Generating"):
      r = await stimma.call_tool("comfyui:flux-klein-9b", prompt=prompt)
      results.append(r)
  stimma.show(results, title="Variations")

Seed sweep (parallel, same prompt, different seeds):
  results = await asyncio.gather(*[
      stimma.call_tool("comfyui:flux-klein-9b",
          prompt="a cat in a garden", seed=1000+i) for i in range(6)
  ])
  stimma.show(results, title="Seed Sweep")

Inside run_code, always use stimma.call_tool() (the SDK method, flat kwargs) —
not the agent-level call_tool tool.""",
        group="core",
        is_async=True,
    ),
    "detect_faces": SDKMethodHelp(
        name="detect_faces",
        signature="await stimma.detect_faces(media_id: int) -> list[dict]",
        summary="Get detected faces in an image — bounding boxes, confidence, and embeddings.",
        details="""\
Get all faces detected in a media item. Face detection runs automatically
after ingestion. Each face includes a normalized bounding box (0-1 coordinates),
confidence score, and a 512-dimensional face embedding vector.

Parameters:
  media_id (int): The library media ID.

Returns:
  List of dicts, each with:
    "id" (int)          — face ID
    "bbox" (dict)       — {"x", "y", "width", "height"} normalized 0-1
    "confidence" (float) — detection confidence
    "embedding" (list[float] | None) — 512-dim AuraFace embedding vector

The bbox coordinates are normalized (0-1). To convert to pixel coordinates,
multiply by the image dimensions:
  pixel_x = bbox["x"] * img.width
  pixel_y = bbox["y"] * img.height
  pixel_w = bbox["width"] * img.width
  pixel_h = bbox["height"] * img.height

Example (draw boxes around faces):
  from PIL import ImageDraw
  info = await stimma.library.get(MEDIA_ID)
  img = Image.open(info["path"])
  faces = await stimma.detect_faces(MEDIA_ID)
  draw = ImageDraw.Draw(img)
  for face in faces:
      b = face["bbox"]
      x, y = b["x"] * img.width, b["y"] * img.height
      w, h = b["width"] * img.width, b["height"] * img.height
      draw.rectangle([x, y, x + w, y + h], outline="red", width=3)
  img.save("faces.png")
  stimma.show("faces.png")

Example (compare face similarity):
  import numpy as np
  faces_a = await stimma.detect_faces(media_id_a)
  faces_b = await stimma.detect_faces(media_id_b)
  if faces_a and faces_b:
      a = np.array(faces_a[0]["embedding"])
      b = np.array(faces_b[0]["embedding"])
      similarity = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
      print(f"Cosine similarity: {similarity:.3f}")

Raises RuntimeError if face detection is still pending or failed.""",
        group="image",
        is_async=True,
    ),
    "adjust": SDKMethodHelp(
        name="adjust",
        signature="stimma.adjust(image, *, auto=None, brightness=0, contrast=0, ...) -> PIL.Image.Image",
        summary="Apply image adjustments, filters, and effects. Sync — no await needed.",
        details="""\
Apply image adjustments, filters, and spatial/creative effects.
Accepts a PIL Image or workspace path. Returns a PIL Image.
All parameters are optional and composable — call multiple times to chain.

Parameters:
  image: PIL Image or str/Path to an image file.

  Auto corrections:
    auto (str): "levels" | "contrast" | "white_balance"

  Level adjustments (-100 to 100):
    brightness, contrast, saturation, exposure, temperature (float)
    gamma (float): 0.2 to 2.2 (default 1.0) — real gamma correction

  Filter presets:
    filter (str): e.g. "chrome", "portra_400", "velvia", "kodachrome"
                  See stimma.filters for all available names.

  Spatial effects (0 to 100):
    blur, sharpen, noise, vignette, clarity, glow, pixelate (float)
    chromatic_aberration (float)
    motion_blur (float), motion_blur_angle (float)

  Creative effects:
    halftone (float, 0-100), halftone_angle (float)
    vhs (float, 0-100)
    glitch (float, 0-100), glitch_block_size (int, default 16)
    dither (str): None or palette name: "bw", "4bit", "8bit", "gameboy", "cga"

  Color effects:
    split_toning (dict): {shadow_hue, shadow_sat, highlight_hue, highlight_sat, balance}
    gradient_map (dict): {shadow_color, highlight_color, intensity}
    color_isolation (dict): {hue, range, feather}

Returns:
  PIL.Image.Image

Examples:
  # Full working pattern (run_code is already async — use await directly):
  info = await stimma.library.get(MEDIA_ID)
  img = Image.open(info["path"])
  img = stimma.adjust(img, filter="portra_400")
  img.save("result.png")
  stimma.show("result.png")

  # Basic adjustments
  img = stimma.adjust(img, brightness=20, contrast=15, saturation=-10)

  # Apply a film filter
  img = stimma.adjust(img, filter="portra_400")

  # Combine filter + levels
  img = stimma.adjust(img, brightness=10, filter="kodachrome", vignette=30)

  # Auto corrections
  img = stimma.adjust(img, auto="levels")

  # Spatial effects
  img = stimma.adjust(img, sharpen=40, noise=15, vignette=25)

  # Chain multiple calls
  img = stimma.adjust(img, auto="levels")
  img = stimma.adjust(img, filter="velvia", contrast=10)
  img = stimma.adjust(img, sharpen=30)
  img.save("final.png")
  stimma.show("final.png")

  # Retro / creative
  img = stimma.adjust(img, dither="gameboy")
  img = stimma.adjust(img, vhs=50)
  img = stimma.adjust(img, halftone=60)

  # Color effects
  img = stimma.adjust(img, gradient_map={"shadow_color": (20, 0, 40), "highlight_color": (255, 200, 100), "intensity": 80})
  img = stimma.adjust(img, color_isolation={"hue": 0, "range": 30, "feather": 20})

Gotchas:
  - This is SYNC — do NOT await it.
  - Does NOT accept media_id. Use stimma.library.get() first:
      info = await stimma.library.get(123)
      img = Image.open(info["path"])
      result = stimma.adjust(img, filter="chrome")
  - Returns a new PIL Image; the original is not modified.""",
        group="image",
        is_async=False,
    ),
    "filters": SDKMethodHelp(
        name="filters",
        signature="stimma.filters -> list[str]",
        summary="List of available filter preset names for stimma.adjust(filter=...).",
        details="""\
A property that returns the list of all available filter preset names.
Use these names with stimma.adjust(filter="name").

Available filters:
  chrome, fade, cold, warm, pastel, mono, noir, stark, sepia, vintage,
  vivid, dramatic, portra_400, velvia, kodachrome, cinestill_800t,
  polaroid_600, tri_x_400

Example:
  print(stimma.filters)
  # ['chrome', 'fade', 'cold', 'warm', 'pastel', 'mono', 'noir', 'stark',
  #  'sepia', 'vintage', 'vivid', 'dramatic', 'portra_400', 'velvia',
  #  'kodachrome', 'cinestill_800t', 'polaroid_600', 'tri_x_400']""",
        group="image",
        is_async=False,
    ),
}

# Group ordering for overview display
_GROUP_ORDER = ["core", "display", "library", "image", "ai"]
_GROUP_LABELS = {
    "core": "Core",
    "display": "Display",
    "library": "Library",
    "image": "Image",
    "ai": "AI",
}


_GROUP_DESCRIPTIONS = {
    "core": "call_tool, gather, batch patterns, controlnet preprocessing, shared project paths",
    "display": "show, show_grid, progress bars (tqdm)",
    "library": "search, browse, get, save, lineage, sets; parameter-sweep grids via the parameter-grid skill",
    "image": "adjust (filters/levels/effects), detect_faces",
    "ai": "llm (text generation, vision)",
}


def get_sdk_overview() -> str:
    """Compact group index. For sdk_help() no-arg call."""
    lines = ["stimma SDK — available method groups:", ""]
    for group in _GROUP_ORDER:
        label = _GROUP_LABELS[group]
        desc = _GROUP_DESCRIPTIONS.get(group, "")
        lines.append(f"  {label} — {desc}")
    lines.append("")
    lines.append('Call sdk_help("<group>") to see methods in a group (e.g. sdk_help("core")).')
    lines.append('Call sdk_help("<method>") for full docs on a specific method (e.g. sdk_help("call_tool")).')
    return "\n".join(lines)


def get_sdk_group_help(group: str, methods: list[SDKMethodHelp]) -> str:
    """Level 2: method names + signatures + summaries for a group."""
    label = _GROUP_LABELS.get(group, group)
    lines = [f"{label} methods:", ""]
    for m in methods:
        async_note = " (async)" if m.is_async else " (sync)"
        lines.append(f"  {m.signature}{async_note}")
        lines.append(f"    {m.summary}")
    lines.append("")
    lines.append(f'Call sdk_help("<method>") for full docs (e.g. sdk_help("{methods[0].name}")).')
    return "\n".join(lines)


def get_sdk_method_help(name: str) -> str:
    """Level 2 (group browse) or Level 3 (method detail) depending on input."""
    # Level 3: direct method lookup
    if name in SDK_HELP:
        m = SDK_HELP[name]
        return f"{m.signature}\n\n{m.details}"

    # Level 2: group name (e.g. "core", "library", "display")
    name_lower = name.lower()
    group_methods = [m for m in SDK_HELP.values() if m.group == name_lower]
    if group_methods:
        return get_sdk_group_help(name_lower, group_methods)

    # Level 2: prefix lookup for "library" matching "library.search", "library.get", etc.
    prefix_methods = [m for m in SDK_HELP.values() if m.name.startswith(name + ".")]
    if prefix_methods:
        # Find the group these belong to and include all group members
        group = prefix_methods[0].group
        all_group = [m for m in SDK_HELP.values() if m.group == group]
        return get_sdk_group_help(group, all_group)

    available_groups = ", ".join(_GROUP_LABELS[g] for g in _GROUP_ORDER)
    available_methods = ", ".join(sorted(SDK_HELP.keys()))
    return f'Unknown "{name}". Groups: {available_groups}. Methods: {available_methods}'


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
