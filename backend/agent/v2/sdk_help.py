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
  stimma.show(result, role="final")

Parallel execution:
  Use asyncio.gather() for independent batches such as prompt or seed sweeps.""",
        group="core",
        is_async=True,
    ),
    "packages.open": SDKMethodHelp(
        name="packages.open",
        signature="await stimma.packages.open(media_id_or_preview_folder) -> PackageDraft",
        summary="Edit a saved package or resume an unsaved preview snapshot, preserving files.",
        details="""Open the attached package's media id in a fresh or existing conversation.
manifest() lists member ids, recipe runs, exact paths and parameters. preview()
writes a workspace copy of all files, including _stimma/cover.src.html for editing.
Existing members, run outputs, paths, recipe versions, extras and cover are preserved.
Add new members/runs normally. For a replacement, use await pkg.replace_member(member_id,
workspace_path), then await pkg.rerun(run_id) for each affected run. Saving rejects
stale dependent runs. Other runs are carried unchanged even if recipes were upgraded.
Update the authored cover with set_cover(); save and show with revises=existing_asset_id.
For an existing loose extra, pkg.replace_file(manifest_path, workspace_path) keeps
its path/name. add_file always adds another file; replace_member targets members only.
This does not regenerate artwork or infer changes from edits to the preview folder.
Each code call has a fresh Python scope. preview() returns a resumable folder;
preview_html()/preview_pdf() return it as 'draft'. In the next code call use
await stimma.packages.open(preview_folder) to continue the exact inspected draft.
Opening the original integer media id starts from the original saved revision.
Load the Packaging skill for the full edit workflow.""",
        group="core", is_async=True,
    ),
    "packages.new": SDKMethodHelp(
        name="packages.new",
        signature="stimma.packages.new(title) -> PackageDraft; await draft.add_member(item, role=None); await draft.run(recipe, inputs, params=None); draft.add_file(path); await draft.manifest(); await draft.preview(); await draft.preview_html(width=1200); await draft.preview_pdf(); draft.set_cover(html_or_path); draft.set_tile(image); await draft.save() -> media_id",
        summary="Assemble a deliverable package: members, deterministic recipe runs, extras, and a cover.",
        details="""\
A package is what you hand over: masters, the derivative tree a recipe
produced (icon sets, logo variants, crops), loose extras, and a visual guide.
Members can be media ids, ToolResults, or workspace paths (saved with lineage).

  pkg = stimma.packages.new(title)
  member = await pkg.add_member(source)  # ToolResult, media id, or workspace path
  await pkg.run(recipe_id, {input_role: member}, chosen_params)
  print(await pkg.manifest())                 # actual member ids, run roots, file paths
  print(await pkg.preview())           # workspace snapshot; inspect before designing
  pkg.set_cover("cover.html")           # required for agent deliveries; validates now
  media_id = await pkg.save()
  stimma.show(media_id=media_id, role="final")  # first delivery only

For an update to an existing package, replace that last line with:
  stimma.show(media_id=media_id, role="final", revises=existing_asset_id,
              revision_note="What changed")
Use the asset_id from its display receipt (or packages.status(original_media_id)).
The same title does not preserve identity. A v1 receipt is a new asset, not a
revision; never describe it as replacing the earlier package.

Add any number of members, runs and loose files (pkg.add_file(path)).
await pkg.manifest() returns a snapshot without saving. await pkg.preview() returns a workspace
folder containing index.html and the files; use read_file/glob/view_image there.
Pass that folder to await stimma.packages.open(folder) in a later code call to
resume the unsaved draft. Both visual preview methods also return this as 'draft'.
await pkg.preview_html(width=390) returns {image, slices, width, height}: the
complete responsive HTML rendered at that width, plus readable image slices.
Inspect slices with view_image(detail="high") at phone and desktop widths
(for example 390 and 1200). These are screen previews, not PDF pages.
After set_cover(), await pkg.preview_pdf() returns {pdf, page_count, pages}:
workspace-relative paths to the exported PDF and its page PNGs. Use view_image
on those PNGs to check pagination, captions and custom print styles before save.
It uses the download exporter and does not create a library item.
Each run_code/run_file call has fresh Python locals. Resume the latest preview
folder to keep edits across calls, or keep the whole build in a workspace script.
Only save the completed package. preview() does not create a library item.

Recipes are deterministic and memoized; judgment (focal points, colors,
naming) goes in params. await stimma.packages.recipes() lists roles and params.
Naming: pass {"naming": {"template": "{slug}-{variant}-{color}", "case": "kebab"}}
to honor the user's filename conventions; platform-fixed names never change.""",
        group="packages",
        is_async=True,
    ),
    "packages.recipes": SDKMethodHelp(
        name="packages.recipes",
        signature="await stimma.packages.recipes() -> list[dict]",
        summary="List installed recipes with their input roles, constraints and parameters.",
        details="""\
Each entry has id, version, display_name, description, inputs (name, kind,
required, square, min_size, alpha), params (name, type, default, options) and
has_guidance. Read it before running a recipe so you gather the right masters
first: a recipe never generates anything, it only arranges what you give it.

  await stimma.packages.guidance(recipe_id)   # notes from that recipe, on demand

Fetch guidance for the recipe you settled on, not for all of them — that is
what keeps a profile with fifty recipes as cheap to work with as one.""",
        group="packages",
        is_async=True,
    ),
    "packages.cover": SDKMethodHelp(
        name="packages.cover",
        signature="draft.set_cover(html)  # arbitrary HTML/CSS/JS plus kit elements",
        summary="Author the package cover: free HTML with kit elements that reference members by ref.",
        details="""\
The cover is a responsive web page. Write any HTML, CSS and classic JS, and
use kit elements wherever the page touches package content:

  <stimma-media ref="m1" caption="Primary mark"></stimma-media>   member, run file path, or extra
  <stimma-grid><stimma-media ref="m1"/><stimma-media ref="m2"/></stimma-grid>   contact-sheet grid
  <stimma-files ref="r1"></stimma-files>                           browsable tree + downloads for a run
  <stimma-compare a="m1" b="m2" mode="slider"></stimma-compare>

Refs are member ids (m1), run ids (r1), or bundle-relative paths from the
manifest. Rules: no external URLs (bundle fonts and images as members),
no <script type="module">, unique ids. A cover that breaks a rule is
refused with the reason, so fix and save again. Author a cover before save(). The plain auto cover is a fallback for
packaging without an agent. Use await draft.manifest() for exact file refs.
Use stimma-appearance for light/dark variants and stimma-sizes for true-size rows.""",
        group="packages",
        is_async=False,
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
        signature="stimma.show(items, *, role='intermediate'|'final', title=None, revises=None, revision_note=None, artifact=False, parent_revision=None)",
        summary="Display media to the user. Sync; do not await.",
        details="""\
Display one or more images/videos to the user. Items can be ToolResult objects,
media IDs, workspace paths, or lists of those values.

role="final" commits the items to the user's library as Assets — use it for results
you produced for them. role="intermediate" is plain display: work-in-progress, and
reference material found or downloaded from elsewhere.

For a revision, pass one result with role="final", revises=<existing asset_id>,
and revision_note="What changed". This forwards the native show revision API;
the execution receipt returns the asset_id for later updates. Keep that asset
handle distinct from media_id. artifact=True creates an explicitly versioned
first result; it is mutually exclusive with revises. parent_revision optionally
branches from an older revision of the same asset.

Example:
  stimma.show(result, role="final", title="Final")
  stimma.show(updated, role="final", revises=asset_id, revision_note="Refined layout")
  stimma.show([a, b, c], role="intermediate", title="Work in progress")
  stimma.show(downloaded_paths, role="intermediate", title="Reference photos")""",
        group="display",
        is_async=False,
    ),
    "show_grid": SDKMethodHelp(
        name="show_grid",
        signature="stimma.show_grid(items, cols=3, *, role='intermediate'|'final', title=None)",
        summary="Display media in a grid layout. Sync; do not await.",
        details="""\
Use this for compact comparison sets.

Example:
  stimma.show_grid(results, cols=3, role="final", title="Prompt sweep")""",
        group="display",
        is_async=False,
    ),
    "library.search": SDKMethodHelp(
        name="library.search",
        signature="await stimma.library.search(query: str, *, limit=20)",
        summary="Literal prompt text search; accepts structured filters and pagination.",
        details="""\
Find existing media before generating or editing.

Example:
  cats = await stimma.library.search("cats", limit=10)""",
        group="library",
        is_async=True,
    ),
    "library.browse": SDKMethodHelp(
        name="library.browse",
        signature="await stimma.library.browse(*, filters=None, query=None, tags=None, limit=20, offset=0, sort_by='created_desc', scope='assets')",
        summary="Browse library media with structured filters.",
        details="""\
Use browse when the user asks for recent items, media types, tags, or other
library filters. Returns a list; query() returns the full page with total/has_more.
Call schema() for fields and matching; options('loras') discovers recorded values.""",
        group="library",
        is_async=True,
    ),
    "library.query": SDKMethodHelp(
        name="library.query",
        signature="await stimma.library.query(filters=None, *, query=None, tags=None, limit=20, offset=0, sort_by='created_desc', random_seed=None, scope='assets')",
        summary="Search metadata with an explicit paginated response.",
        details="Returns items, total, has_more, limit, offset and applied_filters. Filters use strings or {include, exclude, match: contains|exact|glob, mode: any|all}. Call schema() for all fields. scope='media' explicitly searches profile-wide retained intermediates and old revisions as well as current Assets.",
        group="library", is_async=True,
    ),
    "library.schema": SDKMethodHelp(
        name="library.schema", signature="await stimma.library.schema()",
        summary="Discover filters and lineage semantics.",
        details="Returns supported filters, facets, matching rules, scopes and lineage semantics. Same as library(action='browse_schema').",
        group="library", is_async=True,
    ),
    "library.options": SDKMethodHelp(
        name="library.options", signature="await stimma.library.options(facet, *, filters=None, query=None, limit=25, cursor=None, scope='assets')",
        summary="Discover recorded facet values and counts.",
        details="Facets include models, loras, task_types, direct_tools, tags, markers and folders. Returns items and next_cursor. Counts respect other filters and the current project in Assets scope.",
        group="library", is_async=True,
    ),
    "library.inspect": SDKMethodHelp(
        name="library.inspect", signature="await stimma.library.inspect(media_ids: list[int])",
        summary="Batch metadata/history without copying media files.",
        details="Returns items in requested order, each with status and recorded metadata/history. Deleted, missing and ephemeral IDs return status placeholders. Accepts up to 500 IDs. History snapshots do not necessarily have traversable relational edges.",
        group="library", is_async=True,
    ),
    "library.get": SDKMethodHelp(
        name="library.get",
        signature="await stimma.library.get(media_id: int)",
        summary="Load metadata for one media item.",
        details="""\
Use get when you already know the media ID and need its metadata or workspace
file path. The result supports both dict and attribute access: info["path"]
or info.path.""",
        group="library",
        is_async=True,
    ),
    "library.save": SDKMethodHelp(
        name="library.save",
        signature="await stimma.library.save(item, tags=None, sources=None, inspired_by=None)",
        summary="Save workspace files or generated results to the media library.",
        details="""\
Library save is explicit. `show(..., role="final")` also commits a durable
Asset, while `role="intermediate"` only retains Media in the chat for viewing
(work-in-progress, downloaded reference material).
Use save when the user asks to keep something without presenting it.
`item` accepts a ToolResult, a PIL Image, or a workspace path. When saving an
image you composed or edited in code (an Image or path rather than a
ToolResult), pass sources=[media_id, ...] for the images it was made from so
the derivation shows up in lineage. ToolResults carry their own provenance.""",
        group="library",
        is_async=True,
    ),
    "library.by_hash": SDKMethodHelp(
        name="library.by_hash",
        signature="await stimma.library.by_hash(file_hash: str)",
        summary="Resolve a content hash to a library item (copied into the workspace).",
        details="""\
Sprite documents (.stimmasprite.json) reference their base image, portrait, and
per-move artifacts as {"media_id", "hash"}. Use the media_id when present; fall
back to by_hash when only the hash survived. Returns the same record as get().""",
        group="library",
        is_async=True,
    ),
    "library.export": SDKMethodHelp(
        name="library.export",
        signature="await stimma.library.export(media_id: int, format: str, **options)",
        summary="Export a sprite document for a game engine, as frames, or as a preview.",
        details="""\
Same writers as the Export dialog. Formats: atlas-hash (Phaser/Pixi), atlas-array,
godot, unity, unreal, gamemaker, rpgmaker, defold, libgdx, cocos2d, frames,
grid-sheet, strips, stills, gif, webp, apng, mp4. Options: animations=[...],
directions=[...], trim=, padding=, extrude=, scale=, power_of_two=, background=,
image_format=, walk=, sizes=[...]. Files land in the workspace (zips unpacked
into a folder with manifest.json) and the paths are returned — save them with
library.save(path=..., sources=[sprite_media_id]) when the user wants to keep them.
Example:
  paths = await stimma.library.export(sprite.media_id, "godot")""",
        group="library",
        is_async=True,
    ),
    "library.lineage": SDKMethodHelp(
        name="library.lineage",
        signature="await stimma.library.lineage(media_id=None, *, media_ids=None, direction='parents', relationship='derived', filters=None, limit=20, offset=0)",
        summary="Traverse provenance edges, preserving source/output pairs.",
        details="""\
parents/children follow one hop; ancestors/descendants recursively follow recorded
edges, including retained intermediates. relationship is derived, inspired or all.
Returns roots, edges, endpoint items, total and has_more. Each edge carries
root_media_id, source_media_id, output_media_id, task_type, relationship_type,
source_order and input_role when recorded. Filters select reached endpoints
without pruning intermediate traversal. Use inspect() for full history snapshots.""",
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
        signature="await stimma.detect_faces(media_id, *, wait=True, timeout=60) -> list[dict]",
        summary="Faces in a library image: id, bbox, area, confidence, embedding.",
        details="""\
Faces come from the library's index, most confident first. bbox is x, y,
width, height as fractions of the image; area is width*height, so the
largest area is usually the subject. If the image hasn't been indexed yet
this waits up to `timeout` seconds; wait=False raises instead.
Returns [] for media that isn't an image or video.

Example — crop the main face:
  faces = await stimma.detect_faces(42)
  main = max(faces, key=lambda f: f["area"])""",
        group="similarity",
        is_async=True,
    ),
    "face_similarity": SDKMethodHelp(
        name="face_similarity",
        signature="await stimma.face_similarity(a, b) -> dict",
        summary="Is this the same person? Identity similarity between two faces.",
        details="""\
a and b are each a media id, a face (an entry from detect_faces or
find_faces_like, or {"face_id": n}), or a workspace image path. A media id
uses its largest face. A path is analysed on the fly and is not added to
the library. Returns {"similarity", "a", "b"}, where a and b say which face
was compared (face_id, bbox, area). If a side has no face, similarity is
None and "error" says which.

Face similarity measures identity and ignores pose, lighting, clothes and
background. For "same scene / style / near-duplicate" use clip_similarity.

Rough guidance, measured on public portraits (cosine, -1..1). Use these as
starting points and check borderline cases with view_image:
  different people         usually below 0.2 (max seen 0.20)
  same person, other photo median about 0.63; 94% above 0.35
  same photo, recropped    above 0.9
Treat above 0.35 as likely the same person and above 0.5 as confident.
Profile views, heavy stylisation and tiny faces score lower.""",
        group="similarity",
        is_async=True,
    ),
    "find_faces_like": SDKMethodHelp(
        name="find_faces_like",
        signature="await stimma.find_faces_like(ref, *, limit=50, min_similarity=None) -> dict",
        summary="Find library shots of the same person as ref (a media id, face, or path).",
        details="""\
Searches every indexed face in the library (live library items only, not
trash or intermediate results) and returns {"reference", "matches",
"min_similarity", "total_compared"}. Each match has media_id, face_id,
similarity, bbox and area, best face per image, highest first. The
reference image itself is left out. ref is interpreted as in
face_similarity.

min_similarity defaults to the library's face-match setting (0.55 unless
the user changed it), which favours precision. Pass about 0.35 to catch
more varied shots of the person; different people rarely score above 0.2.
If ref has no face the result has no matches and an "error".""",
        group="similarity",
        is_async=True,
    ),
    "clip_embedding": SDKMethodHelp(
        name="clip_embedding",
        signature="await stimma.clip_embedding(target) -> dict",
        summary="CLIP vector for a media id, workspace image path, or text.",
        details="""\
Returns {"embedding": [floats], "dim", "model"} plus what was embedded
(media_id, path or text). Library media uses its stored vector, waiting up
to 60s if indexing hasn't reached it. A string is treated as a workspace
path when it names an image file, otherwise as text. Images and text share
one space, so a text vector can be compared with image vectors.
Use this for your own math; for comparisons, clip_similarity,
find_similar and pairwise_similarity are simpler.""",
        group="similarity",
        is_async=True,
    ),
    "clip_similarity": SDKMethodHelp(
        name="clip_similarity",
        signature="await stimma.clip_similarity(a, b) -> dict",
        summary="Visual/semantic similarity between two images or texts (CLIP cosine).",
        details="""\
a and b are any mix of media ids, workspace image paths and text. Returns
{"similarity", "a", "b"}.

CLIP measures what an image looks like and depicts: same scene, same
style, same subject matter, near-duplicates. It does not tell people apart
reliably; for "same person?" use face_similarity.

Rough guidance for image-to-image, measured on public photos (cosine):
  near-duplicate (recrop, resize, re-encode)  above 0.95
  same subject in a different photo           about 0.85-0.95
  different people, same kind of shot         about 0.6-0.8
Text-to-image scores sit much lower: about 0.2-0.3 for a good match.""",
        group="similarity",
        is_async=True,
    ),
    "find_similar": SDKMethodHelp(
        name="find_similar",
        signature="await stimma.find_similar(ref, *, limit=50, min_similarity=None) -> dict",
        summary="Find visually or semantically similar library images (by image or text).",
        details="""\
The same search as the library's "find similar". ref is a media id, a
workspace image path, or text. Searches live library items only (not
trash or intermediate results) and returns {"reference", "matches",
"min_similarity", "total_compared"}; each match has media_id and
similarity, highest first. The reference image itself is left out.

min_similarity defaults to the library's settings: 0.75 for an image
reference, 0.225 for text. Pass a lower value to see more; pass a higher
one (about 0.95) to find near-duplicates. Items still being indexed are
not searched yet.""",
        group="similarity",
        is_async=True,
    ),
    "pairwise_similarity": SDKMethodHelp(
        name="pairwise_similarity",
        signature='await stimma.pairwise_similarity(targets, *, kind="clip") -> dict',
        summary="N×N similarity matrix for checking a set for duplicates or repeats.",
        details="""\
targets is a list of up to 64 media ids, workspace paths (including crops
you made), texts (clip only) or faces (face only). kind="clip" compares
look and content; kind="face" compares identity using each target's
largest face. Returns {"kind", "targets", "matrix"}; matrix[i][j] is the
cosine between targets i and j, with None where a target had no face.

Use it for dataset checks: near-duplicates (clip above about 0.95),
repeated backgrounds or framing (run clip on background crops), or
confirming a character stays the same person (face above about 0.35).

  sims = await stimma.pairwise_similarity(paths)
  dupes = [(i, j) for i in range(len(paths)) for j in range(i + 1, len(paths))
           if sims["matrix"][i][j] > 0.95]""",
        group="similarity",
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
    "export_layout_html": SDKMethodHelp(
        name="export_layout_html",
        signature="await stimma.export_layout_html(layout, *, out) -> Path",
        summary="Export editable application HTML with bundled fonts and images embedded.",
        details="""Accepts a layout media id or workspace .stimmalayout bundle path. Uses the
app's HTML exporter and preserves the authored canvas and print CSS. Export to a
workspace filename, then include that returned path in the package. Raw source
HTML can still reference workspace assets that won't exist in the recipient's ZIP.
Example: source = await stimma.export_layout_html(layout_id, out="care-card.html")
pkg.add_file(source)""",
        group="image",
        is_async=True,
    ),
    "rasterize_svg": SDKMethodHelp(
        name="rasterize_svg",
        signature="await stimma.rasterize_svg(svg, *, width=None, height=None, out=None) -> Image | Path",
        summary="Render an SVG to pixels with the app's real browser engine.",
        details="""\
`svg` is a workspace path or SVG markup. Returns a PIL Image at exactly the
requested size (or the written path when `out` is given). Size defaults to the
document's own; pass one of width/height and the other follows the aspect ratio.
Warns on stdout if the document renders completely empty.

This is the same renderer behind thumbnails, view_image, PNG export and the
icon bundles. Do not shell out to rsvg-convert, inkscape or magick instead:
they are not installed on users' machines, and where they are they rasterize
differently from what the app ships — so you would be checking your work
against something other than the deliverable.

Example — check a mark at icon size:
  small = await stimma.rasterize_svg("mark.svg", width=16)
  print(small.size, small.getbbox())""",
        group="image",
        is_async=True,
    ),
    "rasterize_layout": SDKMethodHelp(
        name="rasterize_layout",
        signature="await stimma.rasterize_layout(layout, *, out=None, dpi=None) -> Image | Path",
        summary="Export an existing editable layout as a PNG at its authored canvas size.",
        details="""\
`layout` is a workspace .stimmalayout bundle path or library media id returned
by create_layout. Uses the app's existing browser renderer and bundled assets.
Returns a PIL Image, or the written PNG path when `out` is given. Preserves
the declared canvas width and height (measured height for auto-height layouts).
For print, author at 96 CSS pixels per inch and pass dpi=300 to render directly
at 300/96 times that canvas, with PNG density metadata. This preserves source
typography and print CSS; do not enlarge the HTML's fonts or spacing for DPI.
dpi accepts 10–384; total render pixel limits still apply. Without dpi, the
export has exactly the authored pixel dimensions.
Keep the editable bundle/source alongside the PNG in a delivery. Do not search
internal caches for rendered files or install another renderer.

Example:
  png = await stimma.rasterize_layout(42, out="applications/launch.png")
  print_png = await stimma.rasterize_layout(43, out="applications/card.png", dpi=300)""",
        group="image",
        is_async=True,
    ),
    "ffmpeg": SDKMethodHelp(
        name="ffmpeg",
        signature="await stimma.ffmpeg(*args, timeout=600.0, check=True) -> AVToolResult",
        summary="Run ffmpeg in the chat workspace (concat, trim, remux, extract frames).",
        details="""\
Runs ffmpeg with the workspace as cwd. Paths must stay inside the chat
workspace (or shared project workspace); use workspace-relative paths.
Args can be flat strings, a single list, or one command string. Raises
RuntimeError with ffmpeg's stderr on nonzero exit unless check=False.

Example — concatenate two clips losslessly:
  open("list.txt", "w").write("file 'a.mp4'\\nfile 'b.mp4'\\n")
  await stimma.ffmpeg("-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
                      "-c", "copy", "joined.mp4")
  saved = await stimma.library.save("joined.mp4")""",
        group="image",
        is_async=True,
    ),
    "ffprobe": SDKMethodHelp(
        name="ffprobe",
        signature="await stimma.ffprobe(*args, timeout=120.0, check=True) -> AVToolResult",
        summary="Inspect media files with ffprobe (duration, streams, fps).",
        details="""\
Same workspace rules as stimma.ffmpeg. The result's .stdout holds ffprobe's
output.

Example:
  r = await stimma.ffprobe("-v", "error", "-show_entries", "format=duration",
                           "-of", "json", "clip.mp4")
  print(r.stdout)""",
        group="image",
        is_async=True,
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


_GROUP_ORDER = ["core", "display", "library", "packages", "image", "similarity", "ai"]
_GROUP_LABELS = {
    "core": "Core",
    "display": "Display",
    "library": "Library",
    "packages": "Packages",
    "image": "Image",
    "similarity": "Similarity",
    "ai": "AI",
}
_GROUP_DESCRIPTIONS = {
    "core": "generated tools, parallel batches, progress, shared project paths",
    "display": "show, show_grid",
    "library": "search, browse, get, by_hash, save, export, lineage, regeneration",
    "packages": "assemble, preview, edit and save deliverable packages",
    "image": "adjust, filters, rasterize, ffmpeg",
    "similarity": "faces and CLIP: detect_faces, same-person search, similar images, pairwise matrices",
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
  First inspect .stimma/tools/<category>/ with glob/read_file to get the exact name, then:
    from stimma.tools.<category> import <name_from_catalog>
    r = await <name_from_catalog>(prompt="a cat", width=1024)   # r.media_id, r.path, r.seed
  stimma.show(r, role="final") commits+displays produced results ("intermediate" = display only); asyncio.gather() for parallel batches.
  Library: await stimma.library.schema() for fields; .query(filters, limit=20, offset=0)
    returns items/total/has_more; .options('loras') discovers recorded names.
    .inspect([ids]) reads metadata/history without copying files.
    .lineage(media_ids=[ids], direction='ancestors') returns paginated source/output edges.
  Existing package: pkg = await stimma.packages.open(media_id); inspect manifest() and preview(); replace_member()/rerun() for sources, replace_file(extra_ref, path) for extras.
  Packages: pkg = stimma.packages.new(title); await pkg.add_member(x, role=..); await pkg.run(recipe, inputs, params);
    await pkg.manifest() lists output paths; await pkg.preview() writes a workspace snapshot; pkg.set_cover('cover.html');
    await pkg.preview_pdf() returns {draft, pdf, page_count, pages}; inspect the page PNGs with view_image before save.
    In the next call, packages.open(preview_folder) resumes those unsaved edits; opening the original media id starts over.
    media_id = await pkg.save(); stimma.show(media_id=media_id, role='final') is for a FIRST delivery.
    For package revisions, show(..., role='final', revises=existing_asset_id, revision_note='What changed').
    Same title alone creates a separate asset. Verify asset_id and revision number in the display receipt.
    await stimma.packages.recipes() lists recipes.
  Editable layout delivery: await stimma.export_layout_html(layout_id, out="application.html") embeds fonts/images; add that file to the package.
  stimma.* also has: .library (search/browse/get/save), .llm(), .show(), .detect_faces(),
    face_similarity/find_faces_like (same person?), clip_similarity/find_similar/pairwise_similarity (looks alike?),
    await stimma.ffmpeg(...) / stimma.ffprobe(...) for workspace-jailed video/audio processing.
NOT available in run_code (use as agent tools outside run_code): create_layout, bash, view_image, ask_user, browse_web, skill"""
