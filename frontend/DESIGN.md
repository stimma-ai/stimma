# DESIGN.md — the Stimma design language ("Atelier v3")

This file is the law for all UI work in this repo. Read it before building or
restyling any screen. One sentence of intent: **a gallery at night** — media on
near-black mattes, square-cornered artwork, quiet chrome structured by
hairlines/whitespace/typography, teal accent, indigo selection, magenta live.
Light theme is the same gallery at noon (see the two-lights law).


Status: **Atelier v3, in force** (2026-07-18). All prior open questions are
decided: General Sans display, teal accent, indigo selection, magenta live,
sentence-case labels, two-lights law. Recipes reference semantic tokens.

This file is the answer to "how do we do X in this app." If a pattern isn't
here, extend this file first, then build. It is derived from the 2026-07-17
outside the OSS repos; once approved, a distilled version ships in the repo
(likely `frontend/DESIGN.md`) so working agents see it.

## 1. Foundations

### 1.1 Tokens (additions to style.css / tailwind.config.js)

Existing semantic tokens stand (base/surface*/content*/edge*/overlay*/flow-*).
New:

```
--accent(-rgb)            interactive accent. Light: 13 148 136 (teal #0d9488).
                          Dark: brightened teal, contrast-checked (TBD, ~#2dd4bf family).
--accent-selection(-rgb)  selection accent, DECIDED 2026-07-17: indigo family
                          (dark ~#818cf8, light #6366f1). Never an alias of
                          teal: selection ≠ action.
--color-matte(-rgb)       media matte. Dark: near-black (7 9 13). Light: paper (245 245 244).
--color-live(-rgb)        DECIDED 2026-07-18: magenta (dark 244 114 182 /
                          light 219 39 119). "Live" = autonomous/continuous
                          operation the user set running: forever mode armed,
                          slideshow/video transport actives (play, loop,
                          shuffle, unmuted, focus mode). Deliberately fun.
                          Never a resting control, never selection, never a
                          job status. Resolves the pink-transport open item.
--radius-media            0–2px. Media tiles/viewers only.
```

Rules:
- **All new solid tokens are RGB channels** (`R G B`), never rgba strings, so
  Tailwind `/NN` works. Never convert the existing rgba tokens (overlay-*,
  border-subtle, backdrop) to /NN usage — they silently no-op.
- **No new colors, ever, without editing this file.**
- Retirements (enforced at migration, banned in new code now): `blue-500` as
  interactive accent (allowed for Info/Processing status only), `indigo-500`
  as button color, raw `bg-white/[0.0N]` washes (use overlay-* steps), raw
  `border-white/N` (use edge tokens), raw hex colors in templates.

### 1.2 Z-index scale (new tokens; the ONLY allowed z values)

```
z-chrome    30   sticky headers, in-page floating chrome
z-menu      100  context menus, dropdowns, popovers, pickers (+1 for submenus)
z-modal     200  modal dialogs & their backdrops (nested confirm: 210)
z-toast     300  toasts
z-top       400  boot/first-run overlays; full-screen takeover modes
                 (slideshow, compare). Compare must be able to open OVER a
                 running slideshow: both sit at z-top and compare teleports
                 to body, so it paints later. Never put a takeover on
                 z-modal — it will lose to slideshow.
```

Arbitrary `z-[NNNN]` is banned. Known bugs this fixes: DeleteConfirmModal at
z-2000 rendering behind modals; TopBar's unexplained z-[20000]; three identical
context menus 20k apart.

### 1.3 Radius roles

| Role | Token | Use |
|---|---|---|
| Media | `rounded-media` (0–2px) | tiles, viewers, thumbnails, anything showing user artwork |
| Controls | `rounded-md` (6px) | buttons, inputs, chips, menu items |
| Containers | `rounded-lg` (8px) | the one raised container per region, modals, popovers |
| Circular | `rounded-full` | dots, avatars, toggle tracks, count badges |

`rounded-sm`, `rounded-xl+` are banned in new code (xl+ already renders 8px).
Radius signals *what a thing is*; never mix roles for visual taste.

**Hairline budget (added 2026-07-18, design decision):** rules mark SECTION
boundaries, not every row. Single-line fact rows (KeyValueList) may keep
per-row hairlines; any row tall enough to carry a description separates by
whitespace only — a rule under the group label, none between rows. A stack
of full-width rules between two-line rows reads as a wall of <hr>s.

### 1.3a The separator law (added 2026-07-18, distilled from the review)

A hairline is a SEPARATOR: it may only exist BETWEEN two things. Every rule
on screen must answer "which two peers am I separating?" — if it can't, it's
noise. This is app-wide, not a settings rule. Consequences:

- **Never above the first item, never below the last.** Lists draw rules
  with `divide-y divide-edge-subtle` (or `border-b … last:border-b-0`),
  which makes edge rules structurally impossible. A rule trailing a list is
  the most common violation.
- **Trailing actions are last children, not outsiders.** An "＋ Add …" row
  at the end of a list sits INSIDE the divide as the final child: one rule
  separates it from the items, nothing follows it.
- **Children are not peers.** Sub-controls that belong to a row above
  (sliders under a toggle, expanded step settings, nested params) are never
  fenced by rules — they indent under their parent and the group separates
  from the NEXT peer, not from its own header. A rule between a parent and
  its children cuts the wrong relationship.
- **One boundary per edge.** A card/box edge, a matte transition, or a
  zone gutter is already a boundary; adding a rule on top doubles it. Rule
  OR box OR gutter — never stacked. (Corollary of §1.4 hairline-or-fill.)
- **Headings are labels, not fences.** Never underline a heading; a
  micro-label plus whitespace introduces its section. The one sanctioned
  label rule is the §1.3 "rule under the group label" for KV groups —
  and even that separates the label block from the rows, not decorates it.
- **Tall content separates by whitespace.** Prompt editors, pickers, and
  any block that carries its own visual mass don't need a rule to read as
  distinct; per the hairline budget above, rules earn their keep only in
  runs of short single-line rows where whitespace alone would smear.

Litmus test when reviewing a screen: point at each hairline and name the two
siblings it separates. Anything you can't name two siblings for, delete.

### 1.3b The two-lights law (v3, ADOPTED)

**Geometry and typography are theme-invariant; only color temperature and
elevation rendering change with the theme.** A component never changes
shape, radius, label case, or spacing between themes. Elevation semantics
are identical in both, but render differently because the physics differ:

- Dark ("gallery at night"): cool-neutral tokens; elevation = hairlines
  (`border-edge-subtle`); shadows only on true overlays.
- Light ("gallery at noon"): warm paper tokens; elevation = fill + soft
  diffuse shadow; hairlines reserved for in-panel row separation.

Practically: panels/menus/modals carry BOTH a border token and a shadow
token; dark resolves the shadow to none, light resolves the border to
transparent. Radius scale in both themes: controls 6px, containers 10px,
overlays 12px, media `radius-media` (2px). KV rows are hairline-separated
in both (no zebra). Rows use a soft 6px hover tint in both.

### 1.4 Depth budget

Background + at most ONE raised container per region. Inside a container:
hairlines (`border-t border-edge-subtle`) and whitespace — never another
bordered/filled box. Shadows only on true overlays (menus `shadow-lg`, modals
`shadow-2xl`) — never on in-page elements. **Hairline OR fill, never both**:
inputs are fill-only; panels are hairline-only; a card that needs lift takes
one background step, not border+fill.

### 1.5 Type scale & voices

- UI sans (system): `text-xs` default dense UI, `text-sm` primary content,
  `text-lg font-semibold` in-page headings, `text-xl font-semibold` view
  titles. `font-medium` is the emphasis weight; `font-bold` is banned outside
  display voice.
- **Facts = mono**: ids, paths, seeds, dimensions, file sizes, counts,
  durations, timestamps, params. `font-mono tabular-nums`. Bordered mono =
  editable; bare/chip mono = read-only (codifying the one convention the app
  already keeps).
- **Display = General Sans** (decided 2026-07-17; already bundled as
  `font-brand`): view heroes, empty-state titles, view titles, onboarding.
  600 default, 700 for heroes. Never in controls, menus, or body text.
  Network fonts stay banned in-app.
- Section micro-label, THE one variant (replaces all five found):
  **sentence case** — `text-xs font-semibold
  text-content-secondary`, no uppercase, no tracking. The historical
  ALL-CAPS device is retired app-wide (tables too).
- `font-brand` (General Sans) = the display voice (widened from
  wordmark-only in Phase 3).

### 1.6 Spacing

Control padding `px-3 py-2`, tight `px-2 py-1`, gaps `gap-2` (within groups)
/ `gap-1.5` (icon+label). Page gutter `px-6`; page header `px-6 py-5`;
section gap `space-y-6`; hairline-separated rows `py-2.5`. Half-steps are a
fine-tuning tier, not defaults. Nothing above p-8 without a reason.

### 1.7 Motion

- Color/opacity: `transition-colors duration-150` (default; don't write
  `transition-all` for color changes).
- Reveal/collapse: 180ms `ease` (`flow-expand` pattern is canonical for
  height-auto).
- Overlays: menus fade+scale 120ms in / instant-ish 80ms out; modals backdrop
  fade + card scale(0.98→1) 150ms; toasts keep their existing spec.
- Named Vue transitions come from ONE global stylesheet (`fade`, `expand`,
  `modal`, `menu`, `toast`) — per-component scoped copies are banned.
- `pulse-soft` for live status dots (never stock `animate-pulse`);
  `shimmer` for indeterminate progress.
- No hover scale/translate on controls (retire `hover:scale-105`,
  `-translate-y-px`); reserve transform motion for media-lightbox transitions.

### 1.8 Focus, selection, drag

- Focus: `focus-visible:outline-none focus-visible:ring-2 ring-accent/60`
  (+ `ring-offset-1 ring-offset-surface` on filled controls). Keyboard-only —
  adopt `focus-visible:`, never bare `focus:` ring styling. Text fields may
  additionally swap `border-accent` on `:focus` for pointer users.
- Selection (tiles/rows/chips): `ring-2 ring-accent-selection` inset for media
  tiles; `bg-accent-selection/15` for rows/chips. One treatment each.
- Filter states keep the documented pair: include `bg-blue-500/15
  border-blue-500/50 text-blue-400` → migrate to accent equivalents in Phase 2;
  exclude = red equivalents.
- Drop target: `ring-1 ring-accent/50 bg-accent/10`. The green "additive drop"
  variant stays (tool inputs), documented as the ONE exception.

### 1.9 Status colors — single source of truth

New `utils/statusColors.ts` (or composable `useStatusColor`) mapping semantic
buckets → classes; every surface (flow status, job progress, pipeline
segments, phase nodes, foreach counts, tab dots) consumes it. Buckets:

```
queued/idle    zinc      dot bg-zinc-500, text-content-muted
running        blue      bg-blue-500 (+ pulse-soft on dots)
llm/special    purple    bg-purple-500
awaiting-input teal      the ACCENT (bg-accent / text-accent-hi) — "your
                         turn" is actionable, so it wears the action color
                         (+ pulse-soft on dots). DECIDED 2026-07-18; was
                         purple. Purple stays llm/special only.
done           green     bg-green-500
failed         red       bg-red-500
warning/paused amber     bg-amber-500   ← yellow is deleted; paused = amber
skipped        zinc      at /50
```

Never inline a status→color switch in a component again. Amber is
warning-family ONLY: the boards-amber association, countdown badges, and the
set/grid type icon migrate off amber in Phase 2 (countdown badges adopt the
existing tiered `getRemainingTimeColor()`; type icons go monochrome).

### 1.10 Iconography

Heroicons-outline style, `stroke-width="1.75"` for new icons (existing 1.5/2
split migrates opportunistically). Sizes: `w-3.5` in dense rows, `w-4`
standard, `w-5` toolbar. Tool icons via `ToolIcon.vue`/`taskTypeIcons.ts` +
provider badge — the only sanctioned tool iconography (existing rule).

## 2. The component kit

Everything below lives in `src/components/ui/`. Building one of these means
screens compose the kit; writing a bespoke button/input/modal/menu/tile is a
review rejection.

Tier 1 (unblocks the most drift):
`Button` (primary/secondary/ghost/danger/link × sm/md, loading + disabled
built in), `IconButton`, `TextInput`/`TextArea`/`SearchField`, `Select`,
`Modal` (shell: backdrop token, z-modal, Esc, focus trap, one transition),
`ConfirmDialog` (absorbs ConfirmModal + DeleteConfirmModal), `ContextMenu`
(shell over useContextMenuPosition; absorbs the 3 copies + ActionMenu),
`Tooltip` (new capability; replaces title= where discoverability matters),
`Spinner`, `ProgressBar`, `StatusDot` (+ statusColors.ts).

Tier 2:
`Card`/`Section` (hairline-only), `ListRow` (full-bleed hover tint, hover-
revealed row controls), `KeyValueList` (typeset facts: muted sans label left,
mono value right, hairline rules — replaces every `bg-overlay-subtle p-2
rounded` field tile), `ActionRow` (compact icon+label actions; replaces
stacked full-width outline buttons), `SectionLabel`, `PageHeader` (`px-6 py-5`
hairline; title slot, actions slot), `Tabs`/`SegmentedControl` (one active
treatment: `bg-accent/15 text-accent`), `Toggle`, `Checkbox`, `Radio`,
`Slider` (one thumb spec, webkit+moz), `Stepper`, `Combobox` (absorb
ChatModelPicker into SettingsDropdown's successor), `Badge`/`Chip` (semantic
variants only), `CountBadge`, `Avatar`, `MediaTile` chrome (square, matte,
selection ring — over MediaImage), `Table` (hairline rows, mono numerics),
`Drawer` (if a real need appears; none today), `Banner` (if needed; today
toasts + ConnectionError cover it), `SettingRow` (label/description/control
grammar of §3.2 — absorbs the ad-hoc settings-section layouts),
`PhaseHeader` + `RailStep` (the §3.1 hierarchy grammar — absorbs the
copy-pasted status-icon/duration blocks across flow row files),
`InputSlot` + `PrepRow` (the §3.5 attached-controls grammar — extracted from
MediaPicker.vue's inline Scale/Extend/Preprocess implementations),
`ValueRow` + `ScrubValue` (the editable mono-value grammar shared by §3.3
parameters, §3.4 LoRA weights, and §3.5 prep rows — drag-to-scrub +
click-to-type in one place), `LoraRow` + `LoraPool` (§3.4 — replaces
LoraChip/LoraGroupBox).

Kit-wide contracts: both themes from day one; focus-visible built in;
disabled = `disabled:opacity-50 disabled:cursor-not-allowed` (the one
spelling); loading states built into Button/Tile, never hand-rolled spinners.

## 3. Canonical recipes (pre-kit and for review)

Until a kit component exists, new code uses these exact recipes:

- **Primary button**: `bg-accent hover:bg-accent/90 text-white rounded-md
  px-3 py-2 text-sm font-medium` — hover always DARKENS in light / BRIGHTENS
  in dark via the hover token, one direction per theme, never both in one
  codebase.
- **Secondary**: `bg-surface-raised hover:bg-surface-hover text-content
  rounded-md px-3 py-2`.
- **Ghost**: `text-content-secondary hover:text-content hover:bg-overlay-subtle
  rounded-md` — no border, no bg resets needed.
- **Danger**: solid `bg-red-600 hover:bg-red-500 text-white` for confirm
  buttons; ghost-red (`text-red-400 hover:bg-red-500/10`) for row actions.
- **Text input**: fill-only — `bg-overlay-subtle rounded-md px-3 py-2 text-sm
  text-content placeholder:text-content-muted border border-transparent
  focus:border-accent focus-visible:ring-2 ring-accent/40 outline-none`.
  Never border+fill; never a bordered box for read-only values.
- **Read-only fact**: KeyValueList row — `flex justify-between py-2 border-b
  border-edge-subtle last:border-0`; label `text-xs text-content-tertiary`;
  value `text-xs font-mono text-content select-text`.
- **List row**: `w-full flex items-center gap-2.5 px-3 py-2 hover:bg-
  overlay-subtle` (full-bleed, no per-item borders); controls
  `opacity-0 group-hover:opacity-100`.
- **Modal**: backdrop `fixed inset-0 z-modal bg-overlay-backdrop
  backdrop-blur-sm` (token, never bg-black/NN); card `bg-surface border
  border-edge rounded-lg shadow-2xl`; Esc closes; `@click.self` closes unless
  destructive-in-progress.
- **Menu/popover**: `bg-surface border border-edge-subtle rounded-lg
  shadow-lg py-1 min-w-[160px] z-menu`; rows `px-3 py-2 text-xs
  hover:bg-overlay-subtle`; destructive rows `text-red-400`.
- **Media tile**: `rounded-media bg-matte overflow-hidden` + MediaImage;
  selected `ring-2 ring-accent-selection ring-inset`; NO border, NO
  hover-scale; hover = overlay controls fade-in.
- **Empty state**: EmptyState.vue (extended for display-serif titles in
  Phase 3); errors keep ConnectionError but gain a red-tinted icon circle to
  stop reading identical to empty.
- **Toast**: existing spec is canonical; unify warning icon to amber in both
  themes.

### 3.1 Deep hierarchy (flows: phase → step → iteration → trace)

The stress test for the depth budget. Rules (mock §9 is the reference):

- **Structure = indentation + rail, never nested boxes.** Each level indents
  16px under a 2px `border-edge-subtle` rail; step dots sit ON the rail
  (outlined in the surface color) and carry status via the §1.9 map.
- **Level grammar:** Phase = header row (mono `PHASE N` index + sm semibold
  title + status dot + mono rollup right), hairline-separated, no container.
  Step = rail row (name + type badge + mono duration right). Iteration =
  one more indent; media iterations render as a mini matte strip of
  `radius-media` thumbs + mono `+N` overflow. Trace/detail = disclosure only.
- **Two containments allowed in the entire tree, each with one meaning:**
  1. the *wash inset* (`bg-overlay-faint rounded-md`) for an EXPANDED
     trace/detail — deepest level only, collapsed by default;
  2. the *one raised card* (`bg-surface-raised shadow`) — reserved for
     "needs you" (HITL/awaiting-input). **Elevation = actionability.**
     Nothing else in a flow tree gets a box, ever.
- **Priority encoding:** actionable > running > terminal. The HITL card is
  raised + pulse; running rows get the pulsing dot; completed/pending rows
  are flat, pending additionally at ~55% opacity. Never expand transient
  states automatically (existing rule).
- Rollups (counts/durations) are mono, right-aligned, per level. Per-tile
  compute times, wall-clock at rollups (existing recipe-duration rule).
- The flow *graph* canvas keeps its own matte palette — these rules govern
  the run/trace panels, not the graph.

### 3.2 Settings grammar

Settings had the loosest patterns in the audit; this is now the only way to
build a settings surface (mock §10 is the reference):

- **Every setting is a hairline row**: label (13px content) + optional
  one-line description (11.5px tertiary) on the left, exactly ONE control on
  the right (toggle / select / stepper / button). `py-2.5`, hairline between
  rows, no row boxes, no zebra.
- **Groups** = section micro-label + hairline, `mt-6` between groups. Never
  a bordered group panel. Page content max-width ~680px.
- **Secrets/keys**: masked mono value under the label
  (`sk-ant-••••3kF9`), ghost `Reveal` / `Replace` actions on the right.
  Never an always-open text input holding a secret.
- **Service/provider rows**: leading status dot (§1.9 colors: green
  configured, amber needs-setup, zinc disabled) + name + mono detail;
  right side is a verb button (`Set up` secondary / `Manage` ghost).
  "Needs setup" is the amber dot + verb — no badge zoo.
- **Danger zone**: last group, micro-label in red, rows identical to normal
  settings but with `btn-danger-ghost` actions. No red panels/borders;
  destructive confirmation happens in the ConfirmDialog, not inline.
- Cloud/account rows may use the gradient treatment per the existing cloud
  CTA conventions; everything else in settings is monochrome + accent.

### 3.3 ToolView — the flagship surface

ToolView is the most important screen in the app; it gets its own spec
(mock §11–§12 are the reference). Zone rules first, then each subsystem.

**Composition (Studio mode):** controls column (left) · hero (center, flex-1)
· queue rail (right). The hero and queue rail are the only image-bearing
zones and both sit on matte. The controls column is quiet monochrome rows —
no fills, no borders-in-borders — so the run bar and results carry the
energy. **Exactly one solid-accent button on the whole screen: Run.**
Stage mode swaps proportions, same grammar.

**Header strip:** tool icon chip (accent-wash square) + name (General Sans
600) + hop-to-tool disclosure + mono subtitle (provider · task types).
Presets and layout toggle are ghosts on the right. RemixBanner, when active,
is a single hairline row under the header (purple text accent per §1.9
special) — not a filled banner.

**Run bar:** left = context ghosts (resolution `1216 × 832 · 3:2 ▾`, marks);
right = retention ghost, forever-mode icon ghost, then the split Run button
(primary + `×N` count chip + dropdown segment). Batch count lives IN the Run
button; no separate stepper in the bar.

**Prompt editor:** fill-only field (§3 input recipe), min-height ~3 lines.
The action bar is a single quiet row under the field: Enhance toggle +
translate chip on the left; editor toggles (mono/vim), help, and the AI
sparkle on the right — all ghost text/icons, 11px, no pills. The sparkle
uses accent color; it is the only colored glyph in the bar.

**Parameters (seed/guidance/steps/schema params):** the §3 KeyValueList
grammar, editable variant — label left, **mono value right; click value to
edit in place, drag to scrub numerics**. Non-default values read accent
(same modified signal as prep rows); Reset appears in the row's context
menu. Seed gets shuffle + lock glyphs (lock = accent when locked). Grouped
schema params use section micro-labels, never nested boxes. Collapsed
subsystems (post-processing chain, advanced) are §3.3 value-first rows
(`Post-processing chain … Off ▾`).

**Video params** (duration/FPS/frame count): same editable-KV rows; fixed
option sets render the standard Select, ranges render the §3.3 thin slider
inside a wash-inset disclosure.

**Hero:** media on matte, `radius-media`, no chrome border. All affordances
are black-glass overlay chips (`bg-black/55 backdrop-blur`, mono for facts):
jump-to-newest top-left; generation facts bottom-left (`4.2s · flux-pro ·
6d left`); remix/volume/trash bottom-right; marker toggles top-right.
Nothing outside the matte.

**Queue rail:** square tiles, 2px gutters, on matte. Generating tile =
pulse dot + thin progress bar centered on matte (no spinner-over-thumbnail).
Failed tile = dimmed thumb + red ✕ + Retry text. Selected (= hero) tile =
selection ring. Batch groups separate with a hairline, not a box.

#### 3.3.1 ToolView parity ledger — nothing gets silently lost

ToolView is dense because people live in it for hours; **every feature below
survives the reskin**. The mock (§12) is compositional, not parity-complete —
this ledger is the contract. Disposition key: *restyle* = same behavior, kit
skin; *grammar* = same behavior, moved onto a named grammar from this file.
If migration finds a feature not listed here, add it to the ledger BEFORE
touching the file — removal is never a silent side effect of restyling.

Header zone: hop-to-tool switcher menu (restyle, menu shell §7) · Edit
button on frozen-flow tools (restyle, ghost) · PresetPicker (restyle, menu
shell) · provider/task subtitle incl. renamed-instance condensed form +
archive glyph (restyle, mono facts) · RemixBanner active AND
dismissed-interstitial states (grammar: hairline row, purple accent) ·
resolution auto-change notification (restyle, toast or inline row —
decide in Phase 1, not dropped) · tool-unavailable overlay with cached UI
behind (restyle) · loading-generation-config overlay (restyle).

Run bar: all FOUR resolution pickers — Constrained (x-allowed-dimensions),
standard W×H, Gemini aspect-ratio, Megapixels (grammar: one trigger-ghost
look, each keeps its own popover contents; snapping/lock behavior untouched
per resolution-grid rules) · AutoMarkPicker (restyle) · BatchRunButton
split Run + batch-size dropdown incl. keyboard entry + spin-arrow
suppression (restyle) · ForeverModeButton incl. its running state (restyle;
loses its pink — uses accent + ∞ glyph) · AutoDeletePicker (restyle) ·
Studio/Stage layout toggle (restyle) · Queue options menu (restyle, menu
shell).

Prompt: AIPromptEditor with Enhance toggle (family-aware pipeline
untouched) · Translate chip + language menu · Vim/Reg toggle · Mono/Sans
toggle · help popover (wildcards, named wildcards, comments, verbatim,
enhance docs) · AI sparkle → inline prompt-only chat (all restyle; action
bar becomes the §3.3 quiet row, zero features removed) · Lyrics second
input for audio tools (restyle) · PromptAgentChat page-level dock (restyle,
chat grammar §8).

Inputs: MediaPicker multi-image/video incl. batch mode slot behavior,
drag-reorder, paste, add-tile popover with frecency recents
(MediaPickerPopover) · prep rows: Crop editor modal, Scale
(factor/megapixels/manual + aspect lock), Extend canvas (4 sides + fill
color), Preprocess (all controlnet options + per-preprocessor params +
busy spinner) — all grammar §3.5 · Reference audio picker (separate
section, stays separate per audio-input rules) · MaskEditor +
AIMaskAssistant for inpaint (restyle only; editor internals out of scope) ·
Frame images picker for i2v start/end (grammar §3.5; unified
frameImages shape untouched).

Params: Duration dropdown OR slider · FPS · legacy frame count (VACE) ·
UpscaleResolutionPicker · SchemaParamGroup dynamic params incl. checkboxes
and grouping (all grammar: editable value-rows §3.3) · PostProcessingPanel
chain toggle + ChainStepCard steps incl. per-step enable (grammar:
value-first collapsed row, §3.1 rail when expanded).

LoRA pool: add modal→picker (grammar §3.4) · filter field · overflow menu
incl. show-raw-paths mode · groups with rename + drag-to-group + new-group
drop zone + drag ghost · per-LoRA toggle, weight edit (typed values
preserved exactly — scrub is additive, typing stays), remove, context menu,
unavailable state (all grammar §3.4) · pool-outside-undo invariant.

Hero: empty state · image/video/audio heroes (MSE loop, AudioPlayer,
toolview volume scope kept separate from slideshow) · click→slideshow ·
jump-to-newest · auto-delete countdown · generation time chip →
GenerationDetailsModal · per-image marker toggles · volume/trash/remix
actions · CompareMode + SlideshowMode overlays (all restyle; overlay chips
become black-glass grammar §3.3).

Queue rail: JobsGrid in both modes with width tween · generating tiles
with real progress · BatchGroup grouping · FailedJobRow + JobErrorModal ·
stage strips hiding hero chrome · draggable seam with highlight (all
restyle).

### 3.4 LoRA pool

Its own system, unrelated to reference-image slots. Current LoraChip
(bordered card + toggle dot + bordered −/value/+ stepper pill + ✕ strip)
is retired. New grammar (mock §12 close-up):

- **A LoRA is a hairline row**: enable dot (accent filled = on, hollow =
  off; click toggles) + name + mono type badge (`XL`) + **weight as a mono
  scrub value** — drag horizontally to adjust in 0.05 steps, click to type.
  No −/+/✕ button strip on the row.
- Weight color: accent when ≠ 1.00, plain otherwise. Disabled row = 50%
  opacity, weight muted. Unavailable-for-this-tool = strikethrough + 50%,
  kept in pool (pool survives tool switches — existing invariant).
- Hover reveals ✕ (remove) and ⠿ (drag handle); everything else lives in
  the row context menu (rename group, move to group, copy trigger words…).
- **Groups are micro-labels + hairlines, not boxes** (LoraGroupBox's border
  goes away). Drag a row onto a group label to regroup; drop-below-last
  creates a group (dashed drop hint only during drag).
- Pool header: `LORAS` micro-label + mono `2/3 on` count + ghost `＋ Add` /
  filter / `⋯` on the right.
- **Picker**: the §7 menu shell (search field + list rows with media thumb +
  type badge; ✓ = already in pool, ＋ adds). No modal-with-checkmark-cards.
- LoRA pool state stays OUTSIDE prompt-editor undo (existing invariant).

### 3.5 Attached controls on input media (prep rows)

The reference-image slot is the densest control surface in the app
(MediaPicker.vue's Scale / Extend Canvas / Preprocess rows). The current
*structure* (rows + disclosure) is right and is hereby codified; the drift to
kill is in value display, modified-state signaling, and inset styling
(mock §11 is the reference). Note this grammar is shared by ToolView's
parameter rows (§3.3) — value-first rows are ONE pattern app-wide:

- **The media is the slot's hero**: square (`radius-media`), on matte,
  slot-header row above it (micro-label + mono dims + hover-revealed
  replace/remove ghosts). Empty slot = dashed `border-edge` drop zone.
- **Prep row grammar (value-first):** icon (content-tertiary) + label
  (12px content-secondary) + **current value in mono, right-aligned** +
  chevron. Value color IS the modified signal: `accent` when non-default,
  muted `—`/`Original` when untouched. No dots, no badges, no bold — a
  collapsed stack must read as a table of what's been touched.
- **Expansion = the wash inset** (`bg-overlay-faint rounded-md`) — the SAME
  disclosure grammar as flow traces (§3.1). One panel open per slot.
  Never a bordered sub-box, never `bg-white/[0.0N]` washes.
- **Inside an inset:** mode switches are the standard segmented control;
  sliders are thin (3px) with mono tabular readouts right-aligned at fixed
  width; paired dimension inputs keep the aspect-lock glyph between them;
  `Reset` is a ghost text button, bottom-right, present only when modified.
- **LoRA chips adopt the same row grammar**: thumb (`radius-media`) + name +
  mono weight (accent when ≠ default) + hover-revealed stepper/remove.
  Disabled = 50% opacity row, weight goes muted. No bordered chip cards.
- Busy state on a row (preprocessing in flight): the row's chevron slot
  swaps to the kit Spinner — never a second spinner elsewhere in the row.
- These rows are workspace state, not form fields: they never render as
  bordered inputs, and slot chrome never changes because of an unrelated
  feature flag (the ControlNet border-drop bug class).

## 4. Greppable review rules

A change is off-standard if it adds any of:
`z-[` (any arbitrary z) · `bg-black/` on a backdrop · new `rounded-xl`/`2xl`
· `bg-white/[` or `border-white/` · a status color switch outside
statusColors.ts · `focus:ring` without `focus-visible` · `hover:scale` on a
control · a `<Transition>` with a new one-off name · `animate-pulse` on a
status dot · inline `<svg class="animate-spin">` · a new all-caps label class
string · `bg-blue-500`/`bg-indigo-500` on a button · raw hex colors ·
`title=` where a Tooltip is warranted (interactive controls) · a bordered box
around read-only text.

## 5. What is deliberately NOT changing

The flow-graph matte palette and node/edge tokens; slideshow matte;
cloud-gradient reservation and `.stimma-cloud-*` treatments; chat bubbles
(restyled via kit, not removed); LoRA pool undo isolation; toolview volume
scoping; segmented-control height matching rule; the RGB-channel alpha
convention; `custom-scrollbar` (and the chat-input native-scrollbar
exception); EXIF/contain-mode behaviors in AppImage.
