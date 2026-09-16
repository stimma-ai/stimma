# Sprite package handoffs

The `stimma-sprites` pack supplies `sprite-assets`, a deterministic recipe for
approved sprite pixels. The Sprite Design skill handles generation, selection,
registration and visual review. The recipe exports those decisions; it never
authors a package cover or chooses artwork.

## Delivery layout

Run the recipe once per actor or coherent static set. Multiple runs, source
members, background images and an agent-authored guide belong to one package.
An actor's moves share a canvas, scale and pivot. Unrelated static objects may
use separate runs so a small projectile need not inherit a large beacon canvas.

Each run contains:

- `frames/<animation_key>/frame_000.png`: untrimmed RGBA frames.
- `atlas/<name>.png` and `.json`: sheet with explicit frame rectangles.
- `asset.json`: engine-neutral playback and placement metadata.
- `README.txt`: placement, playback and engine import instructions.
- Optional `godot/<name>.tres` plus its PNG: Godot 4 SpriteFrames.

`asset.json` paths are relative to the run folder. Animation arrays specify
frame order, integer `durations_ms`, inclusive loop bounds, facing and optional
mirror provenance. `once` holds its last frame. `loop` repeats its range after
any intro. `pingpong` reverses within the range without repeating endpoints.
The normalized anchor uses the full untrimmed frame, measured from its top-left;
x points right and y points down. Place a frame at
`position - anchor * frame_size`. Reflect attachments with the same transform.

`content_bounds` records visible alpha bounds per frame as
`[left, top, right_exclusive, bottom_exclusive]`, using alpha >= 32. This assists
inspection; wings, shadows and weapons are not a physics collision shape.
Game-facing `usage` is authored metadata, not inferred geometry. Suggested keys
include `kind`, `mirror_safe`, `collision_box: {x,y,w,h}`, named `attachments`
(such as `muzzle: {x,y}`), display scale, tile roles and repeat rules. Pixel
coordinates refer to the final frame. Inspect these decisions in a composed
scene before describing them as ready to use.

## Portable source archive

`spritekit.package_source` writes a ZIP containing `source.json` and numbered PNG
frames. It freezes selected pixels without workspace paths or library IDs.
The app's `sprite_source` module reads and validates this input. The recipe
reuses the canonical `sprite_export` writers, rather than maintaining a second
set of engine exporters.

```python
from spritekit import package_source
source = package_source([
    {"name": "run", "direction": "east", "frames": run_frames,
     "fps": 12, "loop": "loop"},
    {"name": "jump", "direction": "east", "frames": [jump_pose],
     "durations_ms": [100], "loop": "once"},
], "courier-source.zip", name="courier", anchor=(0.5, 1.0),
   usage={"kind": "character", "mirror_safe": True})
member = await pkg.add_member(str(source))
await pkg.run("sprite-assets", {"source": member},
              {"godot": True, "padding": 2, "pixels_per_unit": 32})
```

The source contract is version 1: `sprite_source`, `name`, `title`, `anchor`
(two normalized coordinates), `pixelated`, `usage`, and `animations`. Each
animation supplies `name`, optional `direction`, `fps`, `loop`, inclusive
`loop_start`/`loop_end`, `durations_ms`, optional `mirrored_from`, and relative
PNG `frames` paths. Names are lowercase identifiers. Frames must share one
canvas, timing must be positive, and decoded input is limited to 64 megapixels.
Loose native set/grid/sprite manifests resolve through the media library and are
rejected as package members/extras. Use portable source archives instead.
ZIP traversal/duplicate paths and oversized archives are rejected. ZIP entries
use fixed timestamps so unchanged sources and recipe runs reproduce the same
bytes.

`finalize_moves` shares a crop and scale across already registered moves. It
cannot remove root motion or find a character's body. Generate locomotion in
place; use held airborne poses when game physics supplies the jump trajectory.
A concept tile sheet must be prepared into usable pieces before packaging.
`registration_sheet` renders selected final frames with the authored pivot,
collider and named attachments, optionally mirrored around that pivot. This is
a diagnostic image, not a cover template or an automatic geometry detector.

## Engine scope

**Engine-neutral:** PNGs and explicit metadata are directly usable by a coding
agent. A JSON atlas is not a claim of native support in every engine.

**Godot 4:** the resource exports animation names, frame regions, durations and
full-cycle looping, including expanded pingpong order. Partial loop bounds are
rejected for this target instead of being silently discarded. Keep the PNG and
`.tres` together. Node pivot and collision setup remain game-owned. Headless
Godot 4.6.1 import was exercised with nested folders and delivered asset kits;
this is not a compatibility claim for every Godot release.
See [SpriteFrames](https://docs.godotengine.org/en/stable/classes/class_spriteframes.html)
and [AtlasTexture](https://docs.godotengine.org/en/stable/classes/class_atlastexture.html).

**Unity 6:** first-version support is PNGs with manual Single/Multiple sprite
import instructions, explicit sheet rectangles, pixels per unit and pivot
conversion. No Unity Editor import or plugin is validated. See the official
[Sprite texture importer](https://docs.unity3d.com/6000.0/Documentation/Manual/texture-type-sprite.html).

## Checks

Run `stimma test backend tests/test_sprite_document.py tests/test_sprite_packaging.py`.
The portable-source and core exporter tests run independently. The recipe
integration test additionally needs the sibling `stimma-skills` checkout and
skips when it is absent. It verifies repeatable bytes, exact atlas pixel regions,
frame metadata and the absence of recipe-authored cover HTML.

Visual acceptance remains separate: inspect alpha on light/dark backgrounds,
move transitions at one pivot, collision and muzzle placement, tile repetition,
responsive guide HTML and every PDF page. Successful serialization does not
establish successful artwork or a complete game handoff.


### Structured geometry checks

Source write/read rejects nonpositive or nonintegral `usage.tile_size`, frame
sizes not divisible by that tile size, and contradictory optional
`usage.tile_grid: {"columns": ..., "rows": ...}`. The recipe always computes
that grid from the PNG canvas and tile size when tile size is declared.
Attachment points require finite numeric x/y coordinates within the canvas.
These checks do not interpret prose captions or judge anatomy and registration.

Package inputs are retained Media, not automatically standalone library Assets.
Add source ZIPs directly with `pkg.add_member(path)`; loose ZIP/JSON/HTML/code
files are rejected by `library.save` and by Asset creation/revision services.
They remain valid package members/extras and workspace files.
