/**
 * The tool families and their sub-tools — the MVP toolset, a superset of
 * the editor's former plugin groupings.
 *
 * Clicking a family enters a MODE and opens its sub-toolbar. It never edits the
 * stack: the step is created on the first real gesture — a paint stroke, a
 * Adjust slider, placed text, an explicit Run. Empty steps cannot exist, and
 * Esc leaves a mode with nothing to undo.
 *
 * Icons are inner-SVG fragments in the same shape `taskTypeIcons` uses, so they
 * render through the same 24×24 `currentColor` wrapper as every other tool
 * glyph in the app.
 */

import type { IconName } from '../ported/icons'

export type FamilyId =
  | 'crop' | 'retouch' | 'generate' | 'paint'
  | 'levels'
  | 'annotate'

export interface SubTool {
  id: string
  label: string
  /** A glyph from the ported registry; the label becomes its tooltip. */
  icon?: IconName
  /**
   * Show the label BESIDE the icon. The adjustment chips carry this: with six
   * of them on the bar, a glyph alone no longer says which is which.
   */
  labeled?: boolean
  /** Optional interaction help shown only in the tooltip. */
  hint?: string
  /** Not yet implemented; shown so the shape of the family is honest. */
  pending?: boolean
}

export interface ToolFamily {
  id: FamilyId
  label: string
  /** Keyboard shortcut, single key. */
  key: string
  icon: string
  subTools: SubTool[]
  defaultSub: string | null
}

export const FAMILY_ICONS: Record<FamilyId | 'select', string> = {
  crop:
    '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M2 6h14a2 2 0 0 1 2 2v14"/>',
  select:
    '<rect x="4" y="4" width="16" height="16" rx="2" stroke-dasharray="4 3"/>',
  retouch:
    '<path d="m8.4 4.2 11.4 11.4a3 3 0 0 1-4.2 4.2L4.2 8.4a3 3 0 0 1 4.2-4.2Z"/>'
    + '<path d="m9 9 6 6"/><path d="m12 6-6 6"/><path d="m18 12-6 6"/>',
  // Sparkles: the same glyph the rest of the app uses for model-backed work.
  generate:
    '<path d="M12 3v3"/><path d="M12 18v3"/><path d="M3 12h3"/><path d="M18 12h3"/>'
    + '<path d="M12 8.5 13.6 10.9 16 12l-2.4 1.1L12 15.5l-1.6-2.4L8 12l2.4-1.1Z"/>'
    + '<path d="m5.5 5.5 1.8 1.8"/><path d="m16.7 16.7 1.8 1.8"/>'
    + '<path d="m18.5 5.5-1.8 1.8"/><path d="m7.3 16.7-1.8 1.8"/>',
  paint:
    '<path d="M9.1 11.9l8.1-8.1a2.85 2.85 0 1 1 4 4l-8.1 8.1"/>'
    + '<path d="M7.1 14.9c-1.7 0-3 1.4-3 3 0 1.3-1.5 2-2 2 1.1 1.1 2.5 2 4 2 2.2 0 4-1.8 4-4a3 3 0 0 0-3-3z"/>',
  // Sliders: every parametric adjustment enters here, looks included.
  levels:
    '<line x1="4" y1="7" x2="20" y2="7"/><circle cx="14" cy="7" r="2.2"/>'
    + '<line x1="4" y1="12" x2="20" y2="12"/><circle cx="8" cy="12" r="2.2"/>'
    + '<line x1="4" y1="17" x2="20" y2="17"/><circle cx="16" cy="17" r="2.2"/>',
  annotate:
    '<path d="M4 7V5h16v2"/><path d="M9 19h6"/><path d="M12 5v14"/>',
}

export const TOOL_FAMILIES: ToolFamily[] = [
  {
    id: 'crop',
    label: 'Crop',
    key: 'c',
    icon: FAMILY_ICONS.crop,
    defaultSub: null,
    subTools: [],
  },
  // Retouch is the non-generative photo-prep family: every tool here is a
  // brush whose gesture becomes an editable REGION of the retouch-regions
  // container. Heal/Clone/Patch store repair pixels; the photographic brushes
  // (dodge, burn, sponge, blur, sharpen) store a mask plus seeded adjustment
  // settings and re-render parametrically — strength stays adjustable after
  // the stroke, Lightroom-style, instead of baking dabs.
  {
    id: 'retouch',
    label: 'Retouch',
    key: 'r',
    icon: FAMILY_ICONS.retouch,
    defaultSub: 'heal',
    subTools: [
      { id: 'heal', label: 'Heal', icon: 'bandage' },
      { id: 'clone', label: 'Clone', icon: 'stamp', hint: 'Clone — alt-click a source, then brush' },
      { id: 'patch', label: 'Patch', icon: 'patch', hint: 'Patch — select an area, then drag to its source' },
      { id: 'dodge', label: 'Dodge', icon: 'sun', hint: 'Dodge — brush to lighten' },
      { id: 'burn', label: 'Burn', icon: 'moon', hint: 'Burn — brush to darken' },
      { id: 'sponge', label: 'Sponge', icon: 'sponge', hint: 'Sponge — brush saturation up or down' },
      { id: 'blur', label: 'Blur', icon: 'droplet', hint: 'Blur — brush to soften' },
      { id: 'sharpen', label: 'Sharpen', icon: 'focus', hint: 'Sharpen — brush to sharpen' },
    ],
  },
  // Every model-backed verb lives here; the family name carries the cost
  // meaning. The chips keep their text: their names communicate the semantic
  // job, and their icons say what the model does with the region — erase it,
  // or invent new content for it — rather than repeating one magic glyph.
  {
    id: 'generate',
    label: 'Generate',
    key: 'g',
    icon: FAMILY_ICONS.generate,
    defaultSub: 'remove',
    subTools: [
      // The two removals sit together — parallel names, parallel jobs — and
      // Regenerate, the open-ended directed edit, closes the group.
      { id: 'remove', label: 'Remove object', icon: 'eraser', labeled: true, hint: 'Remove an object or distraction' },
      // Whole-image, no selection: the model finds the subject itself. Its
      // output's alpha becomes a live matte over the composite, so the cut
      // stays a row — toggle it off and the background is back.
      { id: 'cutout', label: 'Remove background', icon: 'cutout', labeled: true, hint: 'Make the background transparent' },
      // "Regenerate": the base is a generated image, and this generates the
      // selection again under new instructions — not "Repaint", which read as
      // manual brushwork with a Paint family nearby.
      { id: 'repaint', label: 'Repaint', icon: 'sparkles', labeled: true, hint: 'Repaint — replace the selection with what you describe' },
      // Whole-frame like cutout, no selection: outpaint-image tools take the
      // original and grow the canvas themselves from the four edge percents.
      { id: 'expand', label: 'Expand', icon: 'expand', labeled: true, hint: 'Expand — grow the canvas outward' },
    ],
  },
  // Every parametric adjustment lives here: the Autos, the eight group edits
  // (Light, Color, Detail, Mixer, Point color, Grading, Effects, Stylize) and
  // the Looks strip. Filters used to be a second family beside this one, which
  // was always a fiction — its steps executed as the same `adjust` op through
  // the same pipeline, but the separate doorway kept them from ever consulting
  // a selection. Every entry here is an ADD: click, get a focused step, edit it
  // in Properties; with a selection live, the step is scoped to it.
  {
    id: 'levels',
    label: 'Adjust',
    key: 'l',
    icon: FAMILY_ICONS.levels,
    defaultSub: null,
    subTools: [],
  },
  {
    id: 'annotate',
    label: 'Annotate',
    key: 'a',
    icon: FAMILY_ICONS.annotate,
    // No 'select' sub-tool: object selection is the workspace's IDLE state
    // (and the island's pointer), not an annotate mode. Inside the family,
    // `sub = null` is select — where every drawing tool lands after its
    // one-shot creation.
    defaultSub: 'arrow',
    subTools: [
      { id: 'arrow', label: 'Arrow', icon: 'arrowUpRight' },
      { id: 'draw', label: 'Draw', icon: 'pencil' },
      { id: 'rectangle', label: 'Rectangle', icon: 'square' },
      { id: 'ellipse', label: 'Ellipse', icon: 'circle' },
      { id: 'line', label: 'Line', icon: 'slash' },
      { id: 'text', label: 'Text', icon: 'type' },
      { id: 'redact', label: 'Redact', icon: 'redact' },
    ],
  },
  // Last: the family a photo edit reaches for least. The order is the one order
  // the editor shows everywhere (desktop row, phone row).
  {
    id: 'paint',
    label: 'Paint',
    key: 'p',
    icon: FAMILY_ICONS.paint,
    defaultSub: null,
    subTools: [],
  },
]

export function familyById(id: FamilyId): ToolFamily {
  return TOOL_FAMILIES.find(family => family.id === id)!
}

/**
 * Raster Paint engines as chips, Krita-style. Paint is the illustration
 * family: engines lay down marks on a raster layer. The photographic
 * pixel-reading engines (heal, clone, patch, dodge, burn, sponge, blur,
 * sharpen) moved to Retouch, where a gesture becomes an editable region
 * instead of baked dabs; legacy layers painted with them still render — a
 * raster layer is just pixels.
 */
export interface PaintEngine {
  id: string
  label: string
  icon: IconName
  /** Optional interaction help shown in the tooltip instead of the label. */
  hint?: string
  /** Reads the composite below rather than laying down the color. */
  readsPixels?: boolean
  /** Not yet implemented. */
  pending?: boolean
}

export const PAINT_ENGINES: PaintEngine[] = [
  // The tip — soft, hard, ink, airbrush — is chosen in the brush picker that
  // hangs off the toolbar, so there is one Brush engine rather than one chip
  // per shape. What is listed here is what the engine DOES, which is the part
  // the picker cannot express.
  { id: 'paint', label: 'Brush', icon: 'paintbrush' },
  // Erase punches through the layer's own pixels (destination-out), never the
  // composite below — a raster layer without an eraser is not a layer.
  { id: 'erase', label: 'Erase', icon: 'eraser', hint: 'Erase — brush away this layer\'s paint' },
  // Flat and selection-scoped: region-finding belongs to the selection rail.
  { id: 'fill', label: 'Fill', icon: 'fill', hint: 'Fill — fills the selection, or the whole layer' },
  // Shares Fill's slot, Photoshop-style. The drag supplies direction and
  // extent; the picker in the subbar supplies the color spectrum.
  { id: 'gradient', label: 'Gradient', icon: 'gradientLinear', hint: 'Gradient — drag across the selection or layer' },
]

/** Paint tools that share the bucket slot and its press-and-hold flyout. */
export const PAINT_FILL_ENGINES = ['fill', 'gradient'] as const

export const PAINT_SWATCHES = [
  '#ffffff', '#000000', '#c9a276', '#5d4128', '#b0342c', '#2a4a6b', '#3f7a4f',
]

/**
 * The selection tools, on the rail at the left of the canvas — not a family.
 *
 * Selection is workspace state, not a mode: it cuts across every family (an
 * inpaint mask, a paint clip, an adjustment's region), so its tools live in
 * chrome that is always reachable rather than behind a mode that would have to
 * end the one you are in. Arming one SUSPENDS the open family — the pointer
 * belongs to the selection until it is disarmed, and the family's session, step
 * and controls all survive underneath.
 */
export type SelectToolId =
  | 'object' | 'rect' | 'ellipse' | 'lasso' | 'magnetic' | 'wand' | 'brush'
  | 'linear' | 'radial'

export const SELECT_TOOLS: Array<{
  id: SelectToolId
  label: string
  icon: IconName
  /** Extra interaction help; the gradients need it because they are drags. */
  hint?: string
}> = [
  { id: 'rect', label: 'Rectangle', icon: 'squareDashed' },
  { id: 'ellipse', label: 'Ellipse', icon: 'circleDashed' },
  { id: 'lasso', label: 'Lasso', icon: 'lasso' },
  { id: 'magnetic', label: 'Magnetic', icon: 'magnetLasso' },
  { id: 'wand', label: 'Wand', icon: 'wand' },
  // Painting a selection is how most model-backed region masks get made,
  // which is why the brush is a workspace selection tool.
  { id: 'brush', label: 'Brush', icon: 'paintbrush' },
  // AI select (SAM3): click segments the object under the pointer; its popup
  // over the island adds select-by-name. Last on the rail — the manual tools
  // read as one geometric group, and this one arms extra UI.
  { id: 'object', label: 'Object', icon: 'sparkles' },
  // Gradient masks: coverage that RAMPS instead of ending at a boundary, which
  // is the one thing none of the tools above can express — a graduated
  // darkening, an off-centre edge burn, a lit side. They sit on this rail
  // rather than in a panel of their own because they are mask authoring like
  // everything else here, so they inherit the combine modes for free.
  {
    id: 'linear',
    label: 'Linear gradient',
    icon: 'gradientLinear',
    hint: 'Linear gradient — drag from full strength to nothing',
  },
  {
    id: 'radial',
    label: 'Radial gradient',
    icon: 'gradientRadial',
    hint: 'Radial gradient — drag out from the centre of the effect',
  },
]

/**
 * The Select rail collapsed to six slots: kin tools (the two marquees, the two
 * lassos, the two gradients) share a slot with a flyout, Photoshop-style. The
 * slot shows whichever member was used last, so the common case stays one
 * click; the flyout is only for switching kin. Membership is by shape of
 * gesture, not implementation — that is what makes the pairs feel like one
 * tool with a variant.
 */
export const SELECT_TOOL_GROUPS: Array<{ id: string; members: SelectToolId[] }> = [
  { id: 'marquee', members: ['rect', 'ellipse'] },
  { id: 'lasso', members: ['lasso', 'magnetic'] },
  { id: 'wand', members: ['wand'] },
  { id: 'brush', members: ['brush'] },
  { id: 'object', members: ['object'] },
  { id: 'gradient', members: ['linear', 'radial'] },
]

/** Combine modes for Select — how a new selection meets the existing one. */
export const SELECTION_MODES = [
  { id: 'new', label: 'New', icon: 'selectionNew' },
  { id: 'add', label: 'Add', icon: 'selectionAdd' },
  { id: 'subtract', label: 'Subtract', icon: 'selectionSubtract' },
  { id: 'intersect', label: 'Intersect', icon: 'selectionIntersect' },
] as const

export type SelectionMode = typeof SELECTION_MODES[number]['id']

/**
 * Text style presets live in textStyles.ts, next to the property mapping they
 * stand for — the toolbar and the inspector both need that mapping, and a bare
 * list of labels here let the two drift apart.
 */
export { TEXT_STYLES } from './textStyles.ts'

export const SHAPE_KINDS = [
  { id: 'rectangle', label: 'Rectangle', icon: 'square' },
  { id: 'ellipse', label: 'Ellipse', icon: 'circle' },
  { id: 'line', label: 'Line', icon: 'slash' },
] as const
