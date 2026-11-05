# DESIGN.md — the Stimma design language ("Atelier v3")

This file is the law for all UI work in this repo. Read it before building or
restyling any screen. One sentence of intent: **a gallery at night** — media on
near-black mattes, square-cornered artwork, quiet chrome structured by
hairlines/whitespace/typography, teal accent, indigo selection, magenta live.
Light theme is the same gallery at noon (see the two-lights law).


Status: **Atelier v3, in force** (2026-07-18). All prior open questions are
decided: General Sans display, teal accent, indigo selection, magenta live,
sentence-case labels, two-lights law. Patterns reference semantic tokens.

This file is the answer to "how do we do X in this app." If a pattern isn't
here, extend this file first, then build. It is derived from the 2026-07-17
outside the OSS repos; once approved, a distilled version ships in the repo
(likely `frontend/DESIGN.md`) so working agents see it.

## 1. Foundations

### 1.1 Tokens (additions to style.css / tailwind.config.js)

Existing semantic tokens stand (base/surface*/content*/edge*/overlay*/flow-*).
New:

```
--accent(-rgb)            interactive accent. Light: 11 120 110 (deep teal).
                          Dark: 18 166 150 (brightened teal).
--accent-on(-rgb)         label/glyph colour ON an accent fill: white on the
                          light fill (5.35:1), near-black 7 8 10 on the dark
                          fill (6.6:1). Always write `text-accent-on` on a
                          `bg-accent` element, never `text-white`.
--accent-selection(-rgb)  selection accent, DECIDED 2026-07-17: indigo family
                          (dark ~#818cf8, light #6366f1). Never an alias of
                          teal: selection ≠ action.
--color-matte(-rgb)       media matte. Dark: near-black (7 8 10). Light: paper (234 233 230), a clear step darker (L* 92.3 against the panel's 96.2) than the 245 244 242 panel beside it.
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
z-overlay   50   full-screen takeover modes (slideshow, compare). Compare
                 must be able to open OVER a running slideshow: both sit at
                 z-overlay and compare teleports to body, so it paints later.
z-modal     200  modal dialogs & their backdrops (nested confirm: 210)
z-menu      220  context menus, dropdowns, popovers, pickers, tooltips
                 (+10 for submenus). ABOVE modals: menus teleport to body,
                 so they compete with modals in the root stacking context,
                 and a menu opened from inside a modal (Settings kebab
                 menus, SettingsDropdown, MarkerPicker) must paint over it.
                 Safe because menus are transient and close on any outside
                 interaction.
z-toast     300  toasts
z-top       400  boot/first-run overlays only (lock screen, first-run tour)
```

Takeovers must sit BELOW z-menu, never at z-top: context menus, pickers,
and modals teleport to body at their own tiers, and a takeover parked above
them swallows every popover opened from inside it (the slideshow
"More menu shows nothing" bug). The same failure hit menus inside modals
when z-menu sat below z-modal (the Settings→Folders "3-dots does nothing"
bug) — hence menus above modals.

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
  Light neutrals are ONE warm family: surface 245 244 242, raised 230 229 226,
  hover 214 213 209, borders the same cast, and the matte 234 233 230 (CIELAB
  b* +1.1 to +2.1), so the sidebar, top bar and matte never read as two
  temperatures. The field fill is black at 5.5% (1.13:1 on white, 1.12 on the
  panel). Fields stay fill-only; no hairline was needed.

Practically: panels/menus/modals carry BOTH a border token and a shadow
token; dark resolves the shadow to none, light resolves the border to
transparent. Shadow strength is a token: `--shadow-page-a` (sm, default, md)
and `--shadow-pop-a` (lg, xl, 2xl, `shadow-black/NN`) scale opacity per theme;
light is 0.4 / 0.85 of dark, so in-page lift is a whisper and true overlays
stay distinguishable. A surface never carries a visible border AND a shadow
beyond `shadow-sm` in the light theme; pick one. Radius scale in both themes: controls 6px, containers 10px,
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

**Text contrast (measured, WCAG AA 4.5:1 on base/surface/raised).** The text
ladder is primary > secondary > tertiary > muted, and every step is readable;
disabled state is `disabled:opacity-50`, never a text token. Dark
(base 13 15 20, surface 18 20 26, raised 26 29 37): secondary 8.4 / 7.7,
tertiary 6.5 / 6.0, muted 5.5 / 5.0 (surface / raised). Light (white, 245,
230): secondary 9.5 / 8.2, tertiary 7.3 / 6.3, muted 5.8 / 5.1. Light
`accent-hi` (13 106 98, 6.7 on white) is for teal text; `accent` is the
fill and carries a white label at 5.35:1. Muted on a hover/active fill can dip toward 4.1.
Placeholders are the muted step in both themes (a global `::placeholder` rule in
style.css; fields write `placeholder:text-content-muted`, never `placeholder-white/NN`).

- UI sans (system): `text-xs` default dense UI, `text-sm` primary content,
  `text-lg font-semibold` in-page headings. View titles are display voice
  (`font-brand font-semibold`), 20px on a collection header and 16px on a
  workspace header (§2 PageHeader). `font-medium` is the emphasis weight; `font-bold` is banned outside
  display voice.
- **Facts = mono**: ids, paths, seeds, dimensions, file sizes, counts,
  durations, timestamps, params. `font-mono tabular-nums`. Bordered mono =
  editable; bare/chip mono = read-only (codifying the one convention the app
  already keeps). Names and context (project subtitle, provider and task line
  under a tool name) are UI sans, not mono. Applied everywhere, rows
  included: a chat or flow row's date, a board's asset count, a sidebar
  detail line, a slider readout are all mono.
  **One date format** (`utils/timeFormat.js`, nothing else formats a date):
  within a week, relative (`now`, `5m`, `3h`, `2d` in rows; `5m ago` in
  panels); beyond that `Aug 13` in the current year and `Aug 13, 2026`
  otherwise (`formatDate`); detail panels and account or sharing facts always
  carry the year; an exact timestamp (tooltips, the Created fact) is
  `Aug 13, 2026, 11:36 PM`. The numeric locale form (`8/13/2026`) is retired.
  **One noun for what a board holds: "assets"** (`1 asset`, `20 assets`) in
  the sidebar, board cards, pickers and the browse count; "items" is not used
  for board contents. A status value shown to people is sentence case
  (`Your turn`) even where the stored vocabulary keeps `Your Turn`
  (`displayFlowStatus`).
- **Display = General Sans** (decided 2026-07-17; already bundled as
  `font-brand`): view heroes, empty-state titles, view titles, onboarding.
  600 default; the hero's `font-bold` also resolves to 600
  (`--display-weight-hero`; 700 crowded the counters). Tracking is
  `--display-tracking` (-0.005em), applied to every `font-brand` element that
  doesn't set its own `tracking-[..]` (the wordmark does), so `tracking-tight`
  is a no-op there. Never in controls, menus, or body text.
  Network fonts stay banned in-app.
- **Dense-control tier**: `text-ctl` (13px / 18px) is the size for actionable
  labels in tool, flow and editor forms: section labels, prompt utilities
  (Enhance, Translate), the resolution trigger's caption. `text-xs` (12px)
  stays for facts and secondary text; mono facts are not enlarged.
- **Media actions** (markers, remix, trash on the band under a tool result; the
  slideshow's rail and the chat preview use the same grammar): a bare target at
  rest (glyph in `content-tertiary`, 36px, 44px on touch), no outline and no fill;
  hover = one overlay step; set = `overlay-light` backing plus the marker's own
  colour. Remix hovers in the accent, trash in danger. Only a set or active state
  gets a stronger backing, so the band never competes with the artwork. The band's
  targets reach past the picture by their own padding so the glyphs, not the
  invisible targets, line up with its edges. (`.result-action` in style.css now
  serves the auto-delete trigger only.)
- **Chat bubbles and composer**: bubbles are fill-only (user `surface-raised`,
  assistant `surface`), one padding (`px-4 py-2.5`), no border; paragraph
  spacing carries the structure inside, and the first and last block have no
  outer margin. The composer rests at one text line plus its control row.
  A chat result collection keeps one title row (title, count, menu), the
  artwork, and one action row where markers and "Add to message" share a
  baseline. Unset markers over artwork are a bare glyph with a soft shadow,
  never a filled rectangle.
- **Resolution trigger**: one control everywhere (tool and flow forms): a
  viewfinder aspect glyph drawn at the real shape, dimensions, chevron, on a
  single fill. A reference-image lock is a badge on the glyph plus a caption
  inside the same control.
- Section micro-label, THE one variant (replaces all five found):
  **sentence case** — `text-xs font-semibold
  text-content-secondary` (`text-ctl` in tool/flow forms), no uppercase, no tracking. The historical
  ALL-CAPS device is retired app-wide (tables too).
- `font-brand` (General Sans) = the display voice (widened from
  wordmark-only in Phase 3).

### 1.6 Spacing

Control padding `px-3 py-2`, tight `px-2 py-1`, gaps `gap-2` (within groups)
/ `gap-1.5` (icon+label); hairline-separated rows `py-2.5`. Half-steps are a
fine-tuning tier, not defaults. Nothing above p-8 without a reason.

**Page rhythm is two tokens per width band** (`style.css`, switched by
`data-width`; Tailwind `px-page`, `gap-section`, `space-y-section`):

| Band | `--page-margin` | `--section-gap` |
|---|---|---|
| narrow (< 600) | 16px | 20px |
| medium (600–839) | 20px | 24px |
| wide (≥ 840, every desktop window) | 24px | 28px |

Every non-media block (headers, titles, rows, cards, section labels, form
fields, filter bars) starts on `--page-margin` and ends on it: a trailing
text link ("View all", "Add assets"), a status line or a count sits on the
same right edge as the trailing button (a touch target's padding is pulled
back with a negative margin so the text, not the target, lands on the edge).
Rows with a hover tint run full bleed and pad themselves by `px-page`. **Media
grids may bleed** past the margin to the pane edge on 2px matte gutters, and
Browse and Board bleed the same way: no inset matte box. Sections are
separated by `--section-gap`, not per-screen numbers. A centered reading
column (chat transcript, home, search) keeps its own measure and takes the
margin only as its minimum side padding.

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
- **The selection law (2026-11-05).** Teal is action; indigo is selection;
  neither marks a tab. Selected media tiles take `ring-2 ring-accent-selection`
  inset. Selected rows, chips and option tiles (sidebar and settings nav rows,
  picker options, export tiles) take `bg-selection/15` with **primary text**
  (`text-content`) and the leading icon in `text-selection`; indigo is never
  the label colour (it measures 3.4:1 on its own wash in light). Selected tabs
  and segments (`SegmentedControl`, the Flow/Chat switch, Steps/Workflow/Code,
  the editor's family bar and panel tabs, mode switches inside tools) are a
  neutral fill two steps above their track (`bg-overlay-medium` on a
  `bg-overlay-subtle` track) with `text-content`; unselected segments are
  `text-content-secondary`. All segments of one control share one label style:
  all text, or all glyph plus text. A toggle that is
  merely on (a panel that is open, a mode that is armed) wears the same
  neutral fill or, for user-armed continuous modes, `live`; it never rests in
  indigo. Measured (text-content on the selection wash over surface): dark
  12.4:1, light 13.5:1; selected segment (text-content on raised): dark
  14.0:1, light 14.0:1; the selection-coloured icon on its wash: dark 5.0:1,
  light 3.4:1 (non-text, 3:1 required).
- Browse marker filters are one chip grammar at every width: individual chips, each with its own include and exclude state. A bare glyph (and label where there is room) at rest, no outline and no fill; backing plus the marker's colour when included; red backing, red minus and struck label when excluded. Spacing holds them together, never a group box. The strip's other controls follow it: Filters is a bare funnel and label that takes the neutral fill only while its panel is open or filters apply; the sort order is a secondary-weight label; every dropdown wears the one outline chevron.
- Filmstrips centre the current item only while it has neighbours on both sides; near either end the strip aligns to that edge.
- **Filmstrip tokens** (`--strip-*` in style.css, `utils/filmstrip.ts`): the tool
  result strip and the slideshow strip share one tile size by available height
  (52px for the phone strips, 96px for a full row), one gap, and one ring: 2px
  selection ring with a 2px offset on the matte, drawn outside the tile. Tiles
  that are not current dim to 80%, never lower. Aspect handling stays per strip
  (natural aspect in the tool strip, square crops in the slideshow).
- **Secondary toolbar on a phone** (browse filters, tools filters, a board's
  section row, the flow's status and workspace row): one band under the header,
  `bg-surface`, a 48px minimum height with 44px targets and no vertical
  padding, 12px side padding, 4px gaps inside a group, a `border-edge-subtle`
  hairline underneath. Each surface keeps its own controls.
- **Fields** (`bg-field`): text fields, selects and the composer take one small
  luminance step above the surface in dark (`--color-field`), and the same quiet
  wash in light. Fill-only; the focus ring appears only on focus.
- **Unavailable thumbnails** are a neutral tile (`bg-surface-raised`) with a quiet
  outline glyph and, where the tile is wide enough, the label "Unavailable".
  Same geometry as a loaded tile; no cross, no alarm colour.
- Filter states keep the documented pair: include `bg-blue-500/15
  border-blue-500/50 text-blue-400` → migrate to accent equivalents in Phase 2;
  exclude = red equivalents.
- Drop target: `ring-1 ring-accent/50 bg-accent/10`. The green "additive drop"
  variant stays (tool inputs), documented as the ONE exception.

### 1.8a Escape dismisses layers

Escape dismisses the top visible transient layer and consumes the keypress.
Dismissal must never pop the app's or browser's navigation stack. Nested viewers
are separate layers: screen → slideshow → set means the first Escape dismisses
the set, the second dismisses the slideshow, and the screen stays put. Grid
cells, source views, menus, sheets, compare views and dialogs follow the same
one-layer-at-a-time rule.

Context-specific shortcuts, such as stopping an active chat or cancelling an AI
selection request, keep their existing behavior when no higher layer owns the
keypress. This is a layer-dismissal rule, not a ban on contextual cancellation.

Dialog and menu roots use `data-modal-layer` or `data-escape-layer` and
`isTopmostEscapeLayer` so visual stacking, rather than listener registration
order, determines the owner. A handled dismissal calls `consumeEscape` so the
same keypress cannot dismiss an underlying layer.

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

`waiting_for_tool` is presented as **Tool unavailable**, never as generic
Waiting. Pending descendants blocked by that equation inherit the same
unavailable signal so the cause remains visible through a sequential flow.
It uses the warning/amber bucket; when the missing provider is Stimma Cloud
and the person is signed out, show the cloud-branded Log in action.

Never inline a status→color switch in a component again. Amber is
warning-family ONLY: the boards-amber association, countdown badges, and the
set/grid type icon migrate off amber in Phase 2 (countdown badges adopt the
existing tiered `getRemainingTimeColor()`; type icons go monochrome).

### 1.10 Iconography

Heroicons-outline style, **one stroke width**: `--icon-stroke` (1.75). A global
rule in style.css draws every outline glyph on the 24px grid at that width
whatever `stroke-width` attribute it ships with; a glyph that needs its own
(a check inside a 12px badge) opts out with `data-stroke="own"`. **Three
sizes**, tokens in style.css and Tailwind (`w-icon-*`, `h-icon-*`):
`icon-inline` 14px inside text, chips and menu rows; `icon-nav` 16px for the
sidebar, toolbars, filter chips, settings nav, header and tool actions and
field adornments; `icon-canvas` 18px for canvas and transport controls and for the phone
header's 44px touch targets
(slideshow, compare, video transport). Nothing is 20px: hero and empty-state
art is illustration, not an icon. Tool icons via `ToolIcon.vue`/`taskTypeIcons.ts` +
provider badge — the only sanctioned tool iconography (existing rule).
Menus, rows and the sidebar draw every glyph outline at 1.75; fill is reserved
for an active toggle (a set heart or bookmark), so an unset toggle never looks
set. Every marker toggle (browse filters, selection bar, slideshow rail and info
panel, tool output settings, the context menu) follows one rule: outline in
`content-tertiary` at rest (`marker-glyph-off` in style.css), filled in the
marker's own color on a `bg-overlay-light` backing when set. A browse filter's
exclude state is the set look plus a red minus. Display-only markers on a tile
are the monochrome black-glass chip (`TileMarkers`). Each destination in the sidebar rail has its own glyph; saved views take
the glyph of the filter they hold (marker, clock for expiring, else funnel).
Pinned and open tool rows show the task-type glyph from `taskTypeIcons.ts` at
nav-icon size and weight, not the vendor mark. The rail has two row shapes: the
icon row (16px glyph in a 24px slot, then label) and the two-line row with a
24px thumbnail, plus the Editing thumbnails (32px, 44px on touch). A tool row is one line; its
provider line appears only for a cloud tool, a tool that is not ready, or a name
another row shares. Rows have ONE height (32px, 44px on touch) and one
two-line variant (40px) for rows with a second line of detail; the rail never
draws a hairline between groups. Within a group rows sit 2px apart. Groups
separate by whitespace alone, always 16px: a break after Home and the saved
views, then each group label (Projects, Pinned, Editing, Open: small semibold
tertiary text) sits 16px under the last row of the group above. Every resting
row is the secondary text step (a pinned tool's name is no brighter than
Assets); the selected row is primary text. Open takes the height the rest of
the rail leaves and scrolls inside it (a short fade marks more below); the rail
itself only scrolls in a window too short to leave Open a few rows. Other groups
collapse from their labels. A saved view that a profile starts with ("My
library", "Expiring soon") shows in sentence case; any other name shows as
stored. On a phone the app beside the open drawer is dimmed with
the backdrop token.

### 1.11 Small screens and touch (adopted 2026-09-04)

Stimma runs in a phone browser against a serving Stimma Server before it
runs in any native shell. One component tree, no `Mobile*.vue` twins, no
`/m` routes, no second stylesheet. Mobile behaviour is an additive branch
that a desktop-sized window never trips.

- **One source of truth.** `composables/useViewport.ts` exposes `isCompact`
  (< 768px, or a native phone shell), `isMedium` (768–1023), `isWide`
  (≥ 1024) and `isCoarsePointer`. Nothing else evaluates a width or pointer
  media query for a layout decision (popover geometry arithmetic is fine).
  `?viewport=compact` pins the compact tier in a desktop window for dev and
  tests. Tailwind `md:` = medium, `lg:` = wide — the same lines.
- **Room is separate from chrome (adopted 2026-09-22).** The chrome tier is
  sticky on a phone shell (switching it remounts the app); the window's
  width is not, because a foldable changes it constantly. `useViewport`
  therefore also exposes a live `width` band — `narrow` < 600, `medium`
  600–839, `wide` ≥ 840, Android's own window size classes (Z Fold: 360
  folded, 752 unfolded) — and `isRoomy` = compact chrome with a
  medium-or-wider window. Tailwind `narrow:` / `medium:` / `wide:` /
  `roomy:` follow `data-width`. `?width=medium` pins the band for dev and
  tests. Roomy surfaces open up INSIDE the compact shell (docked drawer,
  side-by-side tool columns); nothing switches chrome, so folding and
  unfolding mid-task loses no state. In the compact shell the drawer docks
  by default only at `wide` (≥ 840px), where content keeps a useful width.
  At `medium` (a 752px fold) hubs open on the closed drawer: a docked rail
  there narrows rows, recent cards and the tool catalog to one column. Docking
  at medium is the person's choice, kept per profile once made. Detail routes
  dock only at `wide`. Where docking is possible the header's menu button
  becomes the dock toggle (a sidebar glyph, not a hamburger); the closed
  drawer still opens by edge swipe. A drawer that would leave a detail
  surface under ~470px stays a drawer.
- **Chrome.** Every route declares `meta.surface`: `hub`, `detail` or
  `overlay`. Wide = sidebar + top bar. Compact = the SAME sidebar as a
  drawer (NavigationSidebar with `is-mobile`: 276px, pushes the app aside
  rather than floating over it, opened by the header's Menu button or an
  edge swipe, closed by any navigation or a tap on the pushed app) plus a
  60px header (`--header-h-mobile`) on hub and detail routes, and the same
  row in Settings and the editor: Menu (hubs) or back chevron (details),
  title (`font-brand` 18px), then the right strip (the transient background-work
  indicator, provider managers, search, create). No tab bar: the phone keeps
  the desktop's navigation model — library links, projects, boards, chats,
  flows, tools, the working set, and the footer (account, server, feedback,
  settings) all live in the one sidebar, so nothing is renamed or re-homed
  between the two. The account row in the drawer footer opens the account
  sheet (server picker, profile picker, settings, feedback). Overlays
  (slideshow, compare, image editor, PIN lock, connection screen) hide the
  header; an overlay carries its own back control. The header keeps
  mounting under the slideshow (v-show) because views teleport controls
  into it. A view never renders its own navigation chrome. Detail pages
  show the entity name in that header, with tap-to-rename where supported and
  one entity-options drawer. Desktop title rows and their menus are hidden on
  compact; execution controls may remain in a content toolbar. Every phone
  header button is one style (`compact/headerStyles.ts`): a bare 44px target,
  secondary glyph at the canvas icon size, no fill; a toggle that is on takes
  the neutral raised fill, and the only filled button is a primary create
  or Run. One vertical centre for every phone header (hub, detail, Settings,
  editor, slideshow): the title never moves between routes. The first and last
  button are pulled into the row's padding so their glyphs sit on the 16px page
  margin, not on the button edge. A filled primary is a 36px fill inside its
  44px target; when it is last in the strip, the fill's edge sits on the margin.
  Settings is the same row (back and close). On a project's Home the title is
  the project's name; the other project screens keep it as the subtitle.
- **Touch targets.** Interactive controls are ≥ 44×44 px on coarse pointers
  (`min-h-11 min-w-11` under `[data-pointer=coarse]`). Dense desktop rows
  keep their 28px icon buttons on fine pointers; the kit does the switch.
- **Keyboard focus.** `useViewport().allowsAutofocus` gates passive text-field
  focus on navigation, activation and opening browsing pickers. Compact or
  coarse-pointer surfaces wait for a tap on the field, even on wide foldables.
  Explicit text editing, PIN entry, dictation and keyboard shortcuts may focus
  their inputs; non-input focus for accessibility is unaffected.
- **Hover is an accelerator.** Anything revealed on hover (`group-hover:`
  controls, tooltips) is also reachable by tap, long-press or a menu. On
  coarse pointers hover-revealed controls render visible or move into the
  row's context sheet.
- **Drag is an accelerator.** Every drag/drop action has a menu twin: Send
  to board / chat / flow / tool, reorder by long-press. Never a drag-only
  path. Touch drag is not attempted.
- **Menus and modals.** The ContextMenu shell renders a bottom sheet on
  coarse pointers; submenus stack as a second sheet with a back caret.
  Modal renders as a full-screen sheet on compact. Both keep their z-tier.
  No sheet components outside the kit. Interactive provider managers use the
  kit Sheet's expandable mode: open at 75dvh, drag or tap the handle to expand
  to the top safe area, and keep iframe content mounted while resizing.
- **One sheet, one dismissal.** Every bottom sheet on a coarse pointer comes
  from one of exactly two places: the kit `Sheet` component (its own
  full-screen layer, `data-sheet-layer`, is the backdrop) or the global
  coarse-pointer conversion in `style.css` + `useContextMenuPosition`
  (which puts the shared `data-sheet-backdrop` under the converted menu).
  Both also dismiss by a downward swipe (`useSheetSwipe`, installed once
  for the document): pulled from the sheet, or from its content once that
  is scrolled to the top, past a third of its height or flicked; a shorter
  pull springs back. Kit Sheets that are not light-dismissable, or are
  expandable (their handle owns the gesture), opt out.
  Both dismiss on ONE tap outside, always: the shared backdrop forwards the
  tap as an outside click and then Escape. A full-screen `inset-0` box at
  the menu tier is a backdrop, never a menu, and is never converted. Never
  hand-roll a bottom panel, and never ship a sheet you have not tapped
  outside of on a phone.
- **Sheet geometry is tokens, not numbers.** `style.css` `:root` owns every
  sheet dimension and every sheet reads it: `--sheet-row-h` 44px (a row is
  one touch target, never taller), `--sheet-row-px` 16px, `--sheet-row-gap`
  12px, `--sheet-font` 14px, `--sheet-font-detail` 12px mono,
  `--sheet-icon` 20px, `--sheet-radius` 12px, handle 32×4 at 6px,
  `--sheet-pad-top` 16px, `--sheet-header-pb` 8px (under a sheet's title
  row), `--sheet-max-w` 480px (100% on a narrow phone), `--sheet-menu-max-h`
  62dvh (menus), `--sheet-panel-max-h` 85dvh (pickers, info, forms),
  `--sheet-drawer-h` 75dvh (expandable drawers), `--sheet-backdrop`.
  **The sheet is the column.** From the medium band up the sheet itself is
  `--sheet-max-w` wide and centred (kit Sheet, converted menus and inline
  dropdowns alike, via `.sheet-panel` and the coarse-pointer rule); rows fill
  it edge to edge, so a rule never floats inside a wider panel. No sheet
  content builds its own centred inner column.
  Rows are `.sheet-row` (icon first, `.sheet-row-icon`; trailing fact in
  `.sheet-row-detail`; group label `.sheet-section`). Sheets never show a
  scrollbar: the content overflows and the user tugs it. Sheets are dense,
  not toy-sized: no row padding beyond the tokens, no per-sheet sizes.
- **The tool view on a phone.** Narrow: hero, the queue strip, then the
  bottom drawer (prompt pinned, controls beneath). The drawer and its
  content are one surface: a drag anywhere on it outside text fields and
  sliders moves the drawer until it is full and only then scrolls the
  content; pulling down at the top of the content shrinks it; a flick goes to
  the next height. The drawer opens at half height: 50% of the column once there is a result,
  55% for an empty tool, so the prompt and the first controls form a working
  area and the picture still holds most of the width. The picture, its action
  row (44px targets, 4px gap) and the strip sit tight; a glyph on the picture's
  corner opens it full screen (tapping the picture does the same).
  The strip and a slice of the hero stay visible at every
  height. Only the prompt is pinned; resolution is the first control under
  it, and the output settings (auto-markers, auto-delete) live in the sheet
  Run's long-press opens. Compact shows their state in words on a New outputs row in
  the controls (tap opens that sheet) and a small settings glyph on Run while either is on. Roomy: no drawer. Controls on the left; on the right the hero, with
  the same sideways strip of results as the phone (taller) directly under its
  action band as one media unit. A wrap of results scrolling under the hero read as a second
  scroll region. The agent is opt-in: the header's agent
  button docks it full width beneath, as on desktop, and the choice is kept
  per device (docked by default, it read as the prompt field). Short
  screens never dock it. Undocked (always, on a narrow phone), the button
  opens it as a second sheet layered over the drawer, never a centred modal.
- **Bottom edge.** One docked bar per screen (composer, run dock,
  selection bar), padded with `pb-safe`. Never two docked bars.
  Safe-area tokens describe space still needed inside the web viewport.
  The Android shell already insets its WebView, so its frontend tokens are
  zero; browser and iOS viewports retain the CSS environment insets.
- **One matte.** Every surface that places artwork (browse, board, editor, tool,
  slideshow with its strip and its viewers) sits on `--color-matte`: near-black
  in dark, paper in light. `--color-slideshow-matt` is an alias of it.
- **Browse toolbar.** Upload is the toolbar's one create action and the
  view's one primary (solid accent, glyph only on compact), at the right end
  of the filter strip, never a floating button over the grid.
- **Composite previews.** Set and grid covers are baked server-side on the matte (`set_bg`/`grid_bg` in `THEME_PALETTES` equal the matte token values: #07080a dark, #eae9e6 light), so the tile shows no second frame. Change a matte value and the palette together, and bump the container's `CONTAINER_PREVIEW_VERSIONS` entry so cached previews rebake.
- **Media grids.** Square tiles, 2px gutters, on matte; `rounded-media` and
  the selection ring unchanged. Tap = open, long-press = select. Column count
  follows the pane's width, never the layout tier (see Tile grids, §3).
- **The sidebar inside a project** keeps the global rail's rows and wears two
  extra rows above them in the same top slot the stimma wordmark holds
  globally: a labelled return row (`Back to everything`, chevron in the icon
  column) and the project's name as the one prominent identity (display voice,
  switcher chevron). Content screens repeat the project only as a quiet
  subtitle. The return row is the same size and place on desktop, the drawer
  and a docked drawer.
- **The media menu on a phone** is a first level without scrolling: direct
  actions (Edit, Tags, Remix, Share link, Print, Export, Move to Trash) plus
  named rows that open the next stacked sheet: Boards and projects, Send to
  (Tool, Chat, Flow), Explore, Share. A group with one visible row shows that
  row directly. Every action is at most one extra tap. Destinations keep their
  full accessible names (`Send to Chat`); only the visible label drops the
  prefix inside the group sheet. Desktop uses the same groups as hover
  submenus: Boards and projects, Send to, Explore (and Share when it has two
  rows) open a panel beside the menu, and a destination inside it (Boards,
  Tool, Chat, Flow) opens its usual submenu beside the panel. Edit, Tags and
  Boards and projects (organization) stay direct; Remix, Send to and Explore
  are one group; sharing and export are one group; the destructive row stays
  separated at the bottom. A rule exists only between those groups, desktop and
  sheet alike.
- **Voice.** Facts are real facts: one mono fact per row, status as a word, with a
  dot only for states that want attention (a flow at rest is just the word). Never invented rollups (`6 · 2 running · 1 unsaved`).
- **Type.** Body stays `text-sm`; row labels are 15px on compact via the
  kit; mono facts stay 12–12.5px. Long transcript text on a phone uses the
  reading tier, `text-read` / `compact:prose-read` (16px at 1.5, lists indented
  1.25em); facts and controls keep their dense tiers.

**Greppable rules** (enforced as a ratchet by `stimma lint frontend`;
counts may only go down): a width/pointer `matchMedia` outside
`useViewport.ts` · `innerWidth` compared against a number · a fixed
`w-[NNNpx]` ≥ 360 with no breakpoint prefix · `group-hover:opacity-100`
with no coarse-pointer fallback. The phone acceptance lane
(`stimma test acceptance --viewport=phone`) fails any route with
horizontal overflow or a visible sub-44px control unless the route is on
the spec's ratchet list; the desktop geometry guard fails any change that
moves the sidebar or top bar at 1440×900.

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
stacked full-width outline buttons), `SectionLabel`, `PageHeader` (two tiers, see below), `Tabs`/`SegmentedControl` (one active
treatment: neutral `bg-surface-raised text-content`, see §1.8), `Toggle`, `Checkbox`, `Radio`,
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

**PageHeader** (`ui/PageHeader.vue`, desktop; phones use CompactHeader) is the
one header. Two tiers, one height and one title size per tier, one left inset
(`--page-margin`), one slot order: **title, meta, actions, menu**.

| Tier | Screens | Height | Title |
|---|---|---|---|
| standard | collections: boards, chats, flows, tools, board detail, trash | 64px (`h-header`) | `font-brand text-xl font-semibold` |
| compact | workspaces: chat, flow, tool, editor | 52px (`h-header-compact`) | `font-brand text-base font-semibold` |

Rules: the title is the entity's name (editable in place where it can be
renamed); meta is quiet `text-xs` tertiary (status, provider and task, an
unsaved dot); actions are ordered secondary first and the one primary last;
the menu slot holds the overflow button, last on the right. The bottom
hairline is the header's only boundary. A tool's page teleports its
controls into a slot that wears `pageHeaderClass('compact')`
(`ui/pageHeader.ts`). A second row under a header (the flow's view tabs)
shares the margin and takes no second height token.

**One overflow glyph**: horizontal dots (`OverflowButton`), bare, 32px
(`IconButton size="lg"`) on a header, never boxed, never vertical dots;
44px on coarse pointers. **One caret**: the outline chevron-down
(`ui/Caret.vue`), flipped when open, on every select, disclosure and
picker trigger; no solid triangles. A toggle that is on (a panel open, a
layout armed) takes `IconButton active`: a neutral raised fill, never
teal or indigo.

**Select** (`ui/Select.vue`) is the trigger of every dropdown: fill-only
(`bg-overlay-subtle`, no outline), label, caret; `active` tints it accent
while a filter narrows the list. The menu or sheet it opens stays with the
caller. **SearchField** (`ui/SearchField.vue`) is every search or filter
field: fill-only, glass at the left, an accent border only once the person
types (`focusQuietly()` for focus on page load). **Button** carries the
secondary treatment (`variant="secondary"`, raised fill) and the one
primary create (`variant="primary"`, solid accent): a filled button is only
ever a primary create or Run. A screen offers one search entry: a list page's
own field is it, so the phone header drops its global-search icon there
(Tools); global search stays reachable from every other hub.

**Action roles (one hierarchy, three roles).**

| Role | Treatment | Used for |
|---|---|---|
| Primary | solid accent (`Button` primary; on a phone a 36px fill in a 44px target) | the one create or run action of a view: New (collections), Add assets (a board), Upload (browse), Run, Start. At most one per view. |
| Secondary | raised fill, primary text (`Button` secondary; `ProviderRow`'s action) | a labelled supporting action: Configure, Manage, Sign in, Edit inputs |
| Tertiary | bare glyph or secondary-colour text, fill only on hover or when on | toggles, filters, per-section adds, overflow, anything repeated down a list |

Adding content is one treatment: the primary of the view that adds. A second
add action in the same view (a section's own Add assets on a board with several
sections) is tertiary. Teal text is a link or a selected label, never a button.
Configure, Manage and Sign in share the secondary style in every state of a
settings row; the Stimma account's gradient is the one exception and is
cloud-reserved. A screen's global search rests quiet where the page has its own
list field (boards, chats, flows, tools): the list field is the visible search,
and the top bar's field keeps its geometry and shortcut but drops its fill.

A board whose only section is unnamed has no band of its own on desktop: the
page header carries the count and Add assets, the matte starts directly below,
and "Name this section…" floats over the matte's corner on hover and focus.

Kit-wide contracts: both themes from day one; focus-visible built in;
disabled = `disabled:opacity-50 disabled:cursor-not-allowed` (the one
spelling); loading states built into Button/Tile, never hand-rolled spinners.

## 3. Canonical patterns (pre-kit and for review)

Until a kit component exists, new code uses these exact patterns:

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
- **Collection row** (`lists/CollectionRow.vue`; chats, flows): thumbnail,
  content column (title, one-line preview), a fixed right-aligned facts column
  (a status, or message and image counts in two fixed cells), then the date.
  Rows run the pane's full width so the hover tint is full bleed (press steps
  it once more), but their content stops at the list measure (56rem,
  `lists/listMeasure.ts`) and sits centred in it on a broad pane; the page
  header pads itself to the same measure, so the title, the header controls,
  the thumbnails and the date column share two edges. Below 56rem plus margins
  the measure is the page margin. The preview truncates before any fact. Height
  follows content: padding above the title and after the last line, a small
  gap between a record's lines, a clearly larger one between records (the
  facts on a phone never sit near the next record's name). Narrow (< 600) gives the name first
  claim on width: it shares its line only with a bounded date, the preview
  takes the next line and the facts sit together beneath, both counts for a
  chat. A flow row shows no extra output strip; its thumbnail is the first
  output. Preview text is plain: Markdown syntax is stripped
  (`lists/previewText.ts`). **Status in a flow row**: a flow at rest (Done,
  Idle) is muted text with no dot; Running and Paused keep their dot, "Your
  turn" is accent and semibold, a failure is red. The word shows at every width.
- **Row thumbnail** (`lists/RowThumb.vue`): a 40px square on the matte when
  there is art. A set shows its cover (the top card of its stack, cropped to
  fill), transparent art (a vector, or a file with an alpha channel) is drawn
  whole on the transparency checker (a vector never waits on a raster
  renderer) and optically sized: its opaque bounds are measured on load and the
  art is centred and enlarged to fill the slot, by at most 1.6x, so a sticker
  with empty margin does not read as a tiny mark beside a photo. Anything else
  uses its thumbnail. With no
  art, or art that will not load, the slot holds the type's glyph alone at half
  strength: no box, no tile.
- **Tools list** (All tools; `lists/ToolRow.vue`): inside a task section a tool
  family is a header row (task glyph at nav size, the family name in semibold,
  and the facts all its variants share) with its variants as rows indented one
  step past the name, in regular weight, each led by a distinguishing label at primary contrast: the unmarked one is
  "Standard", the lightning mark becomes the label of its speed badge ("Fast",
  "Turbo 4-step"), a parenthetical in the name is kept. Variants that still
  match are told apart by their full name, then by tool id (mono). A family with
  one variant is one row. Rows come in two heights only: one line (32px, 44px
  on touch) and two lines (52px, for a description or, on a narrow window,
  facts); names never wrap. Facts sit beside the name they qualify (beneath it
  when narrow), neutral tertiary text, at most three with `+N`; "fast" is just a
  fact, never accent. Facts a whole section shares sit once on the section
  header's right. Between families the gap is 20px and inside a family it is none; sections are further apart still. A
  tool row is a target: hover and press tint, and a chevron (the options button
  replaces it on a user's own tool). A container wide enough (60rem) lays
  sections in two columns, never splitting a section; rows there hover as
  inset rounded tints rather than full bleed.
- **Modal**: backdrop `fixed inset-0 z-modal bg-overlay-backdrop
  backdrop-blur-sm` (token, never bg-black/NN); card `bg-surface border
  border-edge rounded-lg shadow-2xl`; Esc closes; `@click.self` closes unless
  destructive-in-progress.
- **Menu/popover**: `bg-surface border border-edge-subtle rounded-lg
  shadow-lg py-1 min-w-[160px] z-menu`; rows `px-3 py-2 text-xs
  hover:bg-overlay-subtle`; destructive rows `text-red-400` (themed: `--color-danger-fg-rgb`,
  light #be2626, 5.47:1 on the menu, 5.14:1 on hover).
- **Media tile**: `rounded-media bg-matte overflow-hidden` + MediaImage;
  selected `ring-2 ring-accent-selection ring-inset`; NO border, NO
  hover-scale; hover = overlay controls fade-in.
- **Tile signals** (`TileChip`, `TileMarkers` in `components/media/`): three fixed
  places, one grammar. Kind (type, duration, member count) is a black-glass
  chip top-right; facts (similarity, time left, revisions) are black-glass
  chips bottom-left; state (markers, including edited) is a row of bare white
  glyphs with a soft shadow bottom-right, no plate, so it never reads as a
  button. A chip is `h-5`, `bg-black/55 backdrop-blur`, mono facts, white
  glyphs, same in both themes. At most two signals show at rest, in the order
  similarity or time left, kind, state; the rest (revisions always) fade in on
  hover on a fine pointer and live in the detail view. The only color on a
  tile is an active favorite heart. No per-type icon colors, no bare counts,
  no dog-ears. Set and grid covers are centred on their own backdrop so the
  tile has no blank band.
- **Board section headings:** a named section's title is `text-sm font-semibold
  text-content` with a mono asset count on the right. An unnamed section shows
  one quiet muted line (`Name this section…` and a pencil), never a band: on
  compact it is always there (its 44px target overlaps the gutter instead of
  adding height); on desktop it appears on hover. Every section carries the
  same quiet action, `Add assets`, beside the mono count at the right margin.
- **Tile grids** (`utils/tileGrid.ts`, one rule for browse and boards): the
  column count is `max(3, floor((width + 2) / (minimum + 2)))` from the pane's
  real content width, so a folded phone, an unfolded one and a desktop pane
  all ask the same question and tiles never get small because a layout tier
  said "compact". Three columns is the floor (the phone's rhythm). Tiles share
  the width left after 2px gutters, which equal the 2px outer matte padding;
  tiles sit on `bg-matte` with no separate fill; a short last row keeps the
  tile size. Density is a choice per surface: `browse` minimum 200px (scanning
  many assets), `board` minimum 220px (a curated sheet, a touch larger). Strips
  that sit beside these grids (home recents) take the same function and the
  `browse` density. Board landing covers use 1, 2 or 4 tiles by asset count;
  the name takes its own line above the mono facts.
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
- **Level grammar:** Phase = header row (quiet mono `Phase N` index + row-size
  semibold title + mono rollup right), no container. The phase's status dot and
  label appear only while it needs attention (running, your turn, error, tool
  unavailable); a finished phase is silent because its steps carry the checks.
  Metrics sit in fixed columns shared by phase and step rows (output strip,
  duration, actions). Row actions (reference in chat, re-run) show on hover or
  focus on fine pointers and always on coarse ones.
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
  compute times, wall-clock at rollups (existing flow-duration rule).
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
  One row grammar (`settings/ProviderRow.vue`): icon, name + description left,
  the same trailing structure in every state: a quiet secondary status (when
  there is one), then ONE action in a fixed column (`Configure` / `Sign in`
  while not connected, `Manage` once connected: one secondary style for all
  three, and the status stays in this trailing area beside the action in every
  layout). On compact the row
  is a grid: the name and the action share the first line (the action in one
  fixed 96px column, text centred), and the description and status run the
  full row beneath on one line. No chevrons, no teal text verbs. Descriptions
  wrap to two lines on wider windows.
  The Stimma Cloud gradient CTA is the only other filled treatment in a list.
  A provider's description says what connecting it adds, from what the app
  does with it (which models appear), never the vendor's slogan.
  The section's own title is hidden on compact (the header already shows it).
- **Settings page**: the content pane opens with a display-voice title
  (`font-brand text-xl`, hidden on compact where the header names the page)
  and a one-line description beneath. The modal's own title is the only
  "Settings"; the app-wide group in the nav is "App". Both panes fade where
  content clips at the bottom. On compact the list level shows the title,
  Close and the search field; a section shows Back and its title only.
- **Settings nav**: row-sized text (13px, 15px on compact), selected row =
  `bg-selection/15 text-content` with a `text-selection` icon, the same as
  the app sidebar (§1.8).
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

**Header strip:** the compact-tier PageHeader (§2): tool icon chip (accent-wash
square) + name (General Sans 600, 16px) + hop-to-tool disclosure, then the
provider and the first task as meta on the same row (the other tasks and the
output destination are the tooltip; a destination chip shows only when a
project is set). Presets and the layout
toggle are ghosts on the right; the layout toggle is neutral raised while
Stage is on. RemixBanner, when active,
is a single hairline row under the header (purple text accent per §1.9
special) — not a filled banner.

**Run bar:** left = context ghosts (resolution `1216 × 832 · 3:2 ▾`, marks);
right = retention ghost, forever-mode icon ghost, then the split Run button
(primary + `×N` count chip + dropdown segment). Batch count lives IN the Run
button; no separate stepper in the bar.

**Desktop ownership:** the controls column carries no box (no border, no
fill): the generation prompt is its first block and the only tall field. The
agent dock beneath is the shared composer shape on `bg-field`: at rest one row
(Agent label, an uninterrupted text field, tools and send at the trailing edge;
undo and redo appear only when there is something to undo). Focus or text opens
it into the composer layout: the field on its own full-width row, the controls
row beneath, label at the left and tools plus send at the trailing edge. Schema-supplied
labels are rendered in sentence case at display time
(`components/generation/displayLabel.ts`); the data is unchanged.

**Desktop alignment (2026-11-05):** the prompt and the artwork share one top
edge (16px under the header; on the fold the matte runs to the screen edge
with `--page-margin` inside it, matching the form's left inset). The hero is
top-aligned, never centred, except on a narrow phone. In Stage the agent
prompt docks under the result's action band at the artwork's width (page-wide in
Studio and on the fold). On the fold the hero, its action band and the strip are
one media unit stacked from the top, and the form column sits on the panel
surface (`surface`) with the matte behind the result only; the strip is never
pegged below a gap.
The header's right side is one quiet icon group (presets, layout, forever
mode; forever is a ghost until it runs, then `live`), then Run, then the
queue-options menu. **New outputs** is one collapsed row in the
subsystem grammar below, reading as its state (`Off`, `Favorite · delete 1h`);
it opens a popover with Auto-mark and Auto-delete, one tap each, never a copy
of the result's marker row. The result band's facts (generation time, auto-trash
countdown) are quiet mono readouts, not outlined actions; the time carries a
caret because it opens details. Collapsed subsystems read value-first: label
left; at the right edge a quiet mono state (`None`, `2 on`, `3 steps`,
`4 settings`) and then either a labelled `+ Add` (it adds) or the one caret
(it discloses). One row height (32px, 44px on touch) and one gap
(`ToolSectionHeader`) serve reference images, LoRAs, post-processing, advanced
settings and new outputs; an optional input with nothing in it is that row
(`None` + `Add`, and still a drop target), and its media tile with its height
appears only once there is media or the tool requires one. The prompt editor's keybinding, font and syntax-help
controls sit behind one overflow button.

**Prompt editor:** fill-only field (§3 input pattern), min-height ~3 lines.
The action bar is a single quiet row under the field: Enhance toggle +
translate chip on the left; editor toggles (mono/vim), help, and the AI
sparkle on the right — all ghost text/icons, 11px, no pills. The sparkle
uses accent color; it is the only colored glyph in the bar.

**Parameters (seed/guidance/steps/schema params):** the §3 KeyValueList
grammar, editable variant — label left, **mono value right; click value to
edit in place, drag to scrub numerics**. Non-default values read accent
(same modified signal as prep rows); Reset appears in the row's context
menu. **On a coarse pointer nothing scrubs**: the value is a chip, and a tap
anywhere on the row opens a kit Sheet with the value large, −/+ (hold to
repeat), a full-width slider with a finger-sized thumb, typed entry and
Reset. A finger that drifts while tapping, or starts near a screen edge,
must never change a value. Seed gets shuffle + lock glyphs (lock = accent when locked). Grouped
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
- **Notes** (tool page only): a row whose provider gives its file a content
  fingerprint gets a note icon in the hover cluster, always visible once a note
  exists. It expands an inline editor under the row (wash inset, not a popover,
  so the image stays visible). Rows that are on show their trigger words on a
  quiet mono second line; with Enhance off, a word missing from the prompt
  becomes a warning with Insert. A row without a fingerprint shows none of this.

### 3.5 Attached controls on input media (prep rows)

The reference-image slot is the densest control surface in the app
(MediaPicker.vue's Scale / Extend Canvas / Preprocess rows). The current
*structure* (rows + disclosure) is right and is hereby codified; the drift to
kill is in value display, modified-state signaling, and inset styling
(mock §11 is the reference). Note this grammar is shared by ToolView's
parameter rows (§3.3) — value-first rows are ONE pattern app-wide:

- **The media is the slot's hero**: square (`radius-media`), on matte,
  slot-header row above it (micro-label + mono dims + hover-revealed
  replace/remove ghosts). Empty slot = fill-only drop zone (`bg-overlay-faint`, no border, no dashes); drag-over takes the §1.8 drop-target ring.
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

### 3.6a The image editor on a phone (adopted 2026-09-10, revised 2026-09-11)

The compact editor is the desktop editor re-homed, never a second editor
(§1.11). It borrows the shape every phone editor converges on: one toolbar
row that drills down in place (CapCut), the current tool's parameters as
values with one dial (iOS Photos), and the picture itself as the slider
(Snapseed).

On desktop the history column folds away while a document has no edits; the
Edits button at the end of the family row reopens it. The selection island
rests as one compact Select control, as on the phone; arming a tool (or having
a selection) opens it into three separated groups, tool, combine mode and
selection action (shown only once there is a selection), naming the armed tool
and the active combine mode. The phone, top to bottom:

- **One header row**: back chevron, then Edits straight after it (the stack,
  labelled, with its step count: history is the document's, not a tool), the options button
  (an anchored menu: Compare, the stack, Save as, Revert), undo, redo, Save.
  No title.
- **The picture**, with the glass chips in two fixed zones, whatever the
  picture's shape: zoom and Compare on the stage's top edge, the selection
  pill on its bottom edge just above the deck, all 12px from the sides (the
  header's padding). The pill is the only selection chrome: idle it arms
  the last tool, armed it names the tool in the selection color.
- **The deck** (`EditorToolStrip` under a panel): a single row of cells.
  At the root it is the six families, in the desktop's order (Crop,
  Retouch, Generate, Adjust, Annotate, Paint); inside a
  family it becomes ‹ plus that family's pickable things (brushes, verbs,
  Adjust's groups, crop aspects and turns, paint engines); while a
  selection tool is armed it is ‹ plus the selection tools. Above the row,
  the panel holds only what the current pick needs: the tool's parameters
  (`ParamDeck`), Generate its prompt and Run, the wells and popovers a
  tool has beyond numbers. No drawer, no dock, nothing to drag.
- **The stack** (Edits / Output / Info) is a kit Sheet behind the header's
  Edits button. Tapping a step closes the sheet and opens it where it is
  edited.

**One way out.** The row's left cell is ‹, and it goes up exactly one
level: out of a selection tool to the family beneath it, out of a family
to the root. Nothing else is a way out — re-tapping a cell never leaves,
Adjust's Auto and Looks are panel states of Adjust rather than levels, and
no panel carries its own Done. The armed pill still hands the pointer back
as a shortcut; it is not the mechanism.

**One parameter grammar** (`ParamDeck`, `DeckSegments`, `ParamDial`), the
same for Adjust, the brushes, the selection tools, Crop and Annotate:

- The tool's numeric controls are a **grid of cells** — name left, mono
  value right, three to a row — all visible at once, nothing to scroll
  sideways for. The chosen cell wears the panel's single selection wash (`bg-selection/15`, primary text);
  values away from their default read in the accent. A single parameter is
  just the dial.
- Where a tool has more numbers than one screen wants, a **segment row**
  above the grid chooses which set it shows (Mixer's channel, Grading's
  range, Detail's presence / sharpen / noise / color noise) — the hierarchy
  the desktop draws with section headers. Segments underline their active
  option rather than filling it and carry a dot when their set holds
  values. The same row serves a tool's few peer modes (a brush's tonal
  range, a text preset, how the next selection gesture combines).
- **One dial** scrubs the chosen value by relative drag; with an Adjust
  parameter on it, a one-finger drag across the picture moves it too, with
  a readout under the finger. Reset is a long press on a cell or the dial
  (or a double tap on the dial): nothing on screen for it.
- **Segments stand still.** A segment row never moves when one of its
  segments is tapped: the grid beneath holds the height of the largest set
  (Detail's four). Different groups and tools may differ in height; only
  the sets a segment row switches between must not.
- **Large controls take a drawer** (`DeckDrawer`). The tone curve and the
  color pickers are too tall to share the panel with a grid. Choosing one
  raises a drawer in the deck's place — the picture resizes above it,
  nothing is covered — holding everything the control needs (the curve's
  channel segments, plot, numerics, presets and reset; a picker's wells as
  segments and the picker). Its handle dismisses it by tap or a downward
  swipe, and the row returns exactly as it was. It is not a level of the
  row: ‹ in the row always means the row's own level, never a drawer.

### 3.5a Image collections in chat (adopted 2026-11-03)

An agent's output images are one collection with two views and two homes
(`MediaCollection`). Tiles are `OutputImage`, so status, markers, job info and
the media menu stay in one place.

- **Starting view.** Grid when the whole set fits without paging (12 on wide, 9
  on compact), otherwise Preview. One image has no view toggle.
- **Grid** is one matte wall with 2px gutters, showing whole images. It collapses
  to three rows and the last tile carries mono `+N`. While expanded, the header
  sticks to the top of the chat with Show fewer.
- **Preview** is the picture and a strip. Everything on the picture is §3.3 black
  glass: pick top-left, slideshow and menu top-right, facts bottom-left (the
  position is editable). Add to message bottom-right is the only labelled chip on
  the picture (paging and opening are bare icon glass): a secondary fill, never an
  outline, and once added it dims and reads In message. A set or grid carries the browse `TileChip`
  (monochrome glyph, mono member count), never a colored icon. The picture, strip and
  header fit the chat together, so paging through a set never needs a vertical
  scroll. The strip crops like the slideshow strip, and the current tile takes
  the selection ring while the rest dim.
- **Clicks.** A grid tile opens Preview; the picture opens the slideshow. Touch
  swipes the picture and long-presses to select (§1.11).
- **Panel.** A collection can move into the artifact panel (full screen on
  compact). A chip holds its place in the transcript, and the panel's previous
  contents return when it leaves.
- **Selection** belongs to one collection at a time and docks on the composer
  like the message queue, keeping one bottom bar (§1.11).

### 3.5b Composer and flow header (adopted 2026-11-05)

- **One transcript column.** Messages, media and the composer share one centred
  column (880px; 640px when the chat is docked beside a tool or flow). Everything
  the assistant says or shows, media included, starts on the column's left edge
  (bubble fill, step chevron and artwork card line up) and keeps its own cap on
  the right. On a phone the column sits on `--page-margin`.
- **Home and project overview share one spacing scale** (the `--hub-*` tokens in
  style.css): top offset 80px (16px on compact), hero to composer 32px (16px),
  composer to content 56px (24px), hero size 32px (24px). Hero, composer, tool
  shortcuts, section headings and recent work share one 840px column
  (`--hub-column`); nothing on the page starts further left than the composer.
  Media on the page (recent assets, project art, jump-back covers, flow output
  previews) sits on `bg-matte`, never on the page colour.
  The hero floats in spare height only when nothing sits below it. Inside a
  project the composer carries no "Working in" line (the heading and header say
  it). Recent media sits on the matte and fills the rest of the fold. On compact,
  Jump back in is single-column rows (80px thumbnail, title up to two lines, one
  preview line led by the quiet type label); two columns once the window is roomy.
  The tool shortcuts under the composer are the same row on every layout; on compact
  it is one line that scrolls sideways, subordinate to the composer.

- **The composer is fill-only** (`bg-surface`, no hairline; a focus ring only
  while it has focus). It rests one line tall and grows with its text. Its one
  optional context line (`context` on the shared composer, 11px muted, e.g. where
  a new chat lands), placeholder and model picker share one left edge (16px). A message queue
  or selection bar docked on top uses the same fill. The control row has two groups:
  the model picker on the left; attach, skills and voice as one cluster on the
  right with send standing apart from it. A collection's selection checkbox shows
  on hover or in selection mode only; touch selects by long press.
- **Send is one control** (`ui/SendButton.vue`, used by the chat, flow and
  prompt-agent composers): a 32px `rounded-md` shape, never a disc, inside a
  target that grows to 44px on coarse pointers. Enabled = `bg-accent
  text-accent-on` (hover `bg-accent/90`). Disabled = the faint `overlay-subtle`
  fill with a muted glyph at `opacity-50`: the quietest shape in the composer,
  never a grey solid. Stop uses the same shape with a square glyph.
- **Chat markdown renders inline code as a mono chip**, never with literal
  backticks (the typography plugin's `code::before/after` content is cleared in
  `ChatMarkdown`). Step labels in the transcript are UI sans; mono stays for
  facts and previews.
- **A set is drawn from its own members** (`SetStackPreview`): the first image
  as the picture (78% of the square), the next two as narrow 3% reveals faded
  into the matte, no outlines, on the ordinary matte. The fade is theme-specific:
  light is a light scrim plus a soft shadow so a pale layer stays visible on
  paper; dark exposes less (2%) under a very heavy scrim, so a layer keeps a trace of its
  image without becoming a grey plane. Flow output groups draw
  a set the same way. It falls back to the server's baked thumbnail only when
  no member can be read. **Grids sit on the backdrop their thumbnail was drawn
  on**, so a preview never shows two mattes. On a phone the chips live in bands above and
  below the artwork instead of on it.
- **The agent glyph** is the bot (`components/icons/AgentIcon.vue`), the one
  glyph for opening the agent in tool, chat and flow workspaces (tool header
  and sheet, the dock row with the label "Agent", the flow's Chat segment,
  Settings > Agent). Sparkles stay with prompt enhancement, the wand with
  Enhance, the wrench with configuration.
- **Flow header:** the workspace (Flow | Chat) and the view (Steps | Workflow |
  Code) are both the kit `SegmentedControl`. Start/Resume is the one accent
  action; Pause is a ghost while the run is live and moves into the entity menu
  once the run is done. Status is a quiet label beside the name (dot plus text,
  left-aligned; the compact strip leads with it), never a control. Save custom
  tool is a ghost (icon only on compact). The workspace switch and its sessions
  chevron are one group on one fill at every width, and both segments carry a
  glyph (bolt for Flow, the bot for Chat). Inputs, phases and outputs are all flat
  sections on the page (the §3.1 rail for phases, no cards), separated by the
  section gap; the Steps column holds a 960px measure and every section shares
  one left edge. Inputs is a quiet label with its one action (Edit inputs) at
  the right; its summary values are mono when they are facts (seeds, sizes) and
  sans when they are names. Each output group has one heading with a mono
  count and its artwork sized around the content (a lone result is large); a
  group with nothing to show leaves no heading or gap. The chat's context hint
  is the composer's placeholder, so nothing changes height when typing starts. A step title never
  truncates for its provider pill: the pill wraps below. The compact header's
  title slot keeps a 96px minimum, ellipsizes at the end and never shrinks the
  action buttons.

### 3.6 Flow-graph nodes — the quiet card (adopted 2026-07-19)

The graph canvas nodes follow the same one-signal discipline as the rest of
the app (supersedes the old tinted-card treatment; the §5 flow-graph
carve-out is repealed for nodes/edges — the flow type/status token *values*
in style.css remain the palette):

- **One quiet surface for every node**: `bg-surface border-edge` at 12px
  radius (canvas nodes are the sanctioned exception to the 8px container
  radius; capsules are `rounded-full` pills). No status-tinted fills, no
  flag stripes, no colored dividers. Icon tiles are circular coins.
- **Type = icon tile**: a soft-tinted rounded-md square with a friendly
  outline glyph (`utils/flowNodeVisuals.ts` is the single vocabulary; tool
  nodes use the task-type glyph). ALL-CAPS type chips are retired.
- **Status lives in exactly one place**: the header-corner glyph — ✓ done,
  spinner + a 2px bottom progress hairline when running, ✕ failed, dashed
  ring queued, pulsing accent dot for "your turn", refresh for stale.
  Terminal states get no footer announcement; footer words are quiet,
  sentence-case, user-side ("Waiting its turn", "Didn't finish").
- **Only two states may touch the border**: failed (`border-flow-fail-soft`)
  and actionable awaiting-input — the ONE raised card
  (`bg-surface-raised border-accent/50` + soft accent glow), per §3.1
  elevation = actionability. Pending/skipped dim instead.
- **Wires are plumbing**: neutral `--color-lineage-edge` hairlines at rest;
  only edges feeding a running step light up in accent. The per-type edge
  rainbow is retired.
- **Selection is indigo** (`ring-selection`), on nodes and super-nodes alike
  — selection ≠ action, same as media tiles.
- flow-* tokens are hex vars, NOT RGB channels — never use `/NN` opacity
  modifiers on them (they silently break); use the -soft/-tint variants.

## 4. Greppable review rules

A change is off-standard if it adds any of:
`z-[` (any arbitrary z) · `bg-black/` on a backdrop · new `rounded-xl`/`2xl`
· `bg-white/[` or `border-white/` · a status color switch outside
statusColors.ts · `focus:ring` without `focus-visible` · `hover:scale` on a
control · a `<Transition>` with a new one-off name · `animate-pulse` on a
status dot · inline `<svg class="animate-spin">` · a new all-caps label class
string · `bg-blue-500`/`bg-indigo-500` on a button · raw hex colors ·
`title=` where a Tooltip is warranted (interactive controls) · a bordered box
around read-only text · any §1.11 small-screen rule.

## 5. What is deliberately NOT changing

The flow type/status color *values* in style.css (the node treatment itself
is §3.6); cloud-gradient reservation and `.stimma-cloud-*` treatments; chat bubbles
(restyled via kit, not removed); LoRA pool undo isolation; toolview volume
scoping; segmented-control height matching rule; the RGB-channel alpha
convention; `custom-scrollbar` (and the chat-input native-scrollbar
exception); EXIF/contain-mode behaviors in AppImage.

### File references

File chips use a compact type badge, filename, and mono size with a format
subtitle. Their hover toolbar floats above the chip; touch actions use the kit
Sheet. The file-type badge palette is semantic, not interactive: code blue,
tables green, Markdown purple, archives orange, JSON yellow, images pink.
`--file-type-*-rgb` tokens in style.css provide the dark and light values;
selection still uses `selection`, and file actions still use `accent`.
Read-only code shares the flow editor's syntax palette.
