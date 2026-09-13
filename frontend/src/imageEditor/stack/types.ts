import type { ToneCurve } from './toneCurve.ts'

/**
 * The op-stack image editor's document model.
 *
 * The stack is a COMPOSITION, not a log. Chronology appears nowhere: undo (session)
 * and the version chain (materialized saves) are the only histories. Ops are
 * addressed by stable id, never by index — the UI, undo, and any future agent
 * tooling all need a name for a step that survives reordering.
 *
 * Ops only ever reference the composite below them (dumb references). That is
 * what makes "drag a row" mean exactly one thing everywhere: change what this
 * step applies on top of.
 */

/**
 * There is no whole-image class, and adding one back would be a mistake.
 *
 * An op that replaces the composite occludes everything below it, and a layer
 * that fully occludes the stack beneath it is not a layer — it is a new base.
 * Those live in the version chain, where they are visible and forkable, rather
 * than as a frozen row that the rest of the list's physics contradict.
 */
export type OpClass = 'parametric' | 'patch' | 'container'

export interface OpBlend {
  feather_px: number
  opacity: number
}

export interface Candidate {
  id: string
  /** One user-triggered generation invocation; candidates in a batch share a UI row. */
  batch_id?: string
  /** Bbox-cropped patch PNG — the only region the composite ever keeps. */
  patch_ref?: string
  /**
   * Complete affine from this compact patch's local pixels into the permanent
   * document space established by the base image.
   */
  payload_to_document?: number[]
  /** Read compatibility: top-left of the patch in its authored input frame. */
  patch_origin?: [number, number]
  /** Raw model output — context-owned Media, never a library Asset. */
  media_id: number
  file_hash: string
  job_id?: string
  /**
   * Content hash of the input composite this candidate was sampled against.
   * Compared at render time against the op's current input to derive staleness;
   * nothing about staleness is stored.
   */
  sampled_input_hash: string
}

/**
 * A durable library-backed image supplied after the edited target image.
 * Order is meaningful: prompts can refer to "reference 1", "reference 2", etc.
 */
export interface ModelReferenceImage {
  media_id: number
  file_hash: string
  filename?: string
}

export interface BaseOp {
  id: string
  class: OpClass
  enabled: boolean
  label: string
  /**
   * Complete affine from this op's full-frame spatial payloads into permanent
   * document space. New documents use this as the positional authority.
   *
   * Crops only change document-to-stage geometry; they never rewrite this
   * transform or the master payload.
   */
  payload_to_document?: number[]
  /**
   * The geometry below this op when its spatial payloads were created — the
   * anchor that makes those pixels addressable in the ORIGINAL image's
   * coordinates.
   *
   * Everything spatial an op owns (its mask, its raster layer, the candidates
   * generated against its mask) lives in this frame. The compositor
   * carries them into whatever the geometry is now with `M_now ∘ M_created⁻¹`.
   * Read compatibility for documents written before `payload_to_document`.
   * The compositor derives the canonical transform from this authored frame.
   */
  payload_frame?: { matrix: number[]; width: number; height: number }
}

export interface ParametricOp extends BaseOp {
  class: 'parametric'
  exec: { kind: 'crop' } | { kind: 'adjust' } | { kind: 'backend-filter'; tool_id: string }
  params: Record<string, any>
}

export interface GenerativeOp extends BaseOp {
  class: 'patch'
  exec: { kind: 'tool'; tool_id: string; task_type: string }
  /**
   * The editor verb; distinct from the provider task used to fulfill it.
   *
   * `cutout` (Remove background) inverts the compositing contract: the picked
   * candidate's ALPHA multiplies the input's alpha instead of its pixels being
   * drawn over the input. The color below stays live — an adjustment under the
   * cutout keeps showing through the kept foreground.
   */
  operation?: 'remove' | 'repaint' | 'expand' | 'erase' | 'cutout'
  /** STP parameters as submitted, minus the inputs. */
  params: Record<string, any>
  /** Ordered auxiliary images submitted after the edited target image. */
  reference_images?: ModelReferenceImage[]
  /** The mask this patch was sampled through. */
  mask_ref?: string
  /**
   * The composition the op's effective mask is composed from, once the mask has
   * been made composite — same contract as RetouchRegion.mask_components,
   * with one generative difference: `mask_ref` is NOT cleared. It remains
   * the record of the mask the existing candidates were SAMPLED through
   * (and what an older build renders with), while the component list is the
   * sole authority for compositing and for the next submission. Candidates
   * keep compositing live through the composed mask; coverage the samples
   * never painted shows the input until a regenerate settles the debt.
   */
  mask_components?: MaskComponent[]
  blend?: OpBlend
  /** null while candidates are staged and none has been picked yet. */
  picked: string | null
  candidates: Candidate[]
}

/** One raster Paint layer. Many gestures rewrite the same pixel payload. */
export interface PaintLayerOp extends BaseOp {
  class: 'container'
  exec: { kind: 'paint' }
  state_ref?: string
  raster_ref: string
  sampled_input_hash?: string | null
  blend?: OpBlend
  params?: Record<string, any>
}

/**
 * Read compatibility only. Older builds called pixel-reading Paint layers
 * `retouch` (and an early build used `sketch`). They are still raster Paint
 * layers; new documents never write either executor name.
 */
export interface LegacyPaintLayerOp extends Omit<PaintLayerOp, 'exec'> {
  exec: { kind: 'retouch' | 'sketch' }
}

export interface AnnotationOp extends BaseOp {
  class: 'container'
  exec: { kind: 'annotate' }
  /** Shapes are normalized against the permanent base document dimensions. */
  shapes_in_document?: boolean
  params: { shapes: any[] }
}

export type RetouchRegionKind =
  | 'heal' | 'clone' | 'patch' | 'remove'
  | 'adjust' // read compatibility for the first local-adjustment build
  | 'light' | 'color' | 'detail'
  | 'mixer' | 'point' | 'grade'
  | 'effects' | 'stylize'
  /** A Looks tile scoped to a selection: many groups at once, one region. */
  | 'look'

/**
 * Finishing controls for one repair region.
 *
 * `match_*` are strengths rather than booleans so Auto can be backed off
 * without turning into a second mode. The photographic controls are explicit
 * overrides applied after matching and before the region is composited.
 */
export interface RetouchRegionSettings {
  opacity: number
  feather_px: number
  match_color: number
  match_noise: number
  exposure: number
  brightness: number
  contrast: number
  highlights: number
  shadows: number
  whites: number
  blacks: number
  gamma: number
  curve: ToneCurve
  temperature: number
  tint: number
  hue: number
  saturation: number
  vibrance: number
  colorizeHue: number
  colorizeAmount: number
  defringe: number
  texture: number
  clarity: number
  dehaze: number
  moire: number
  blur: number
  sharpen: number
  sharpenRadius: number
  sharpenDetail: number
  sharpenMasking: number
  noiseReduction: number
  noiseReductionDetail: number
  noiseReductionContrast: number
  colorNoiseReduction: number
  colorNoiseReductionDetail: number
  colorNoiseReductionSmoothness: number
  noise: number
  grainSize: number
  grainRoughness: number
  /**
   * The Effects and Stylize groups. Vignette and Glow are frame-relative: in a
   * scoped region they are computed over the whole frame and then shown only
   * through the mask.
   */
  vignette: number
  glow: number
  halftone: number
  halftoneAngle: number
  vhs: number
  glitch: number
  glitchBlockSize: number
  chromaticAberration: number
  /** Set when this region came from a Looks tile; names which one. */
  look?: string
  /** Mixer: `mixer{Hue|Sat|Lum}{Band}` sliders, -100..100. */
  [key: `mixer${string}`]: number
  pointHue: number
  pointSat: number
  pointLum: number
  pointHueShift: number
  pointSatShift: number
  pointLumShift: number
  pointRange: number
  gradeShadowHue: number
  gradeShadowSat: number
  gradeShadowLum: number
  gradeMidHue: number
  gradeMidSat: number
  gradeMidLum: number
  gradeHighlightHue: number
  gradeHighlightSat: number
  gradeHighlightLum: number
  gradeBlend: number
  gradeBalance: number
}

/**
 * A mask whose strength ramps along a direction, rather than one drawn as
 * pixels. `x1,y1` is where the effect is at full strength and `x2,y2` where it
 * reaches zero, both in the region's authored frame — so the ramp survives a
 * later crop the same way a payload does, and stays re-draggable forever.
 */
export interface LinearGradientMask {
  kind: 'linear'
  x1: number
  y1: number
  x2: number
  y2: number
  /** 0 = a straight ramp, 100 = a long eased one. */
  softness: number
}

/** An elliptical ramp: full strength at the centre, zero at the edge. */
export interface RadialGradientMask {
  kind: 'radial'
  cx: number
  cy: number
  rx: number
  ry: number
  /** Share of the radius spent fading out, 2..100. */
  feather: number
  /** Affect OUTSIDE the ellipse instead — the edge-burn case. */
  invert: boolean
}

/** Drawn pixels; the alpha lives in the region's `mask_ref` payload. */
export interface RasterMask {
  kind: 'raster'
}

/**
 * How a region knows which pixels it covers.
 *
 * Raster masks are baked by a gesture and uploaded. Gradient masks are
 * PARAMETERS, rasterised on demand at render time, which is the whole point:
 * a ramp you cannot re-drag after the fact is not the feature. Absent on a
 * region means raster — every document written before this existed.
 */
export type RegionMask = RasterMask | LinearGradientMask | RadialGradientMask

/** The gradient kinds, which carry geometry and own no payload. */
export type GradientMask = LinearGradientMask | RadialGradientMask

/** How a mask component meets the coverage composed before it. */
export type MaskComponentMode = 'add' | 'subtract' | 'intersect'

/**
 * One editable ingredient of a region's effective mask.
 *
 * A region has ONE effective mask; components are the composition it is computed
 * from — a base plus Add/Subtract/Intersect modifiers, composed in order in
 * soft alpha (add = max, subtract = ×(1−c), intersect = ×c). The first
 * component is the base: it seeds the coverage, and its stored mode is `add`.
 *
 * Components are authored at different times, so each carries its OWN payload
 * anchor — the same frame/transform contract a region's single mask has. That
 * is what lets a gradient modifier added after a crop co-transform correctly
 * while the base authored before it does too.
 */
export interface SelectionSemantic {
  prompt?: string
  intent?: 'subject' | 'background' | 'sky'
}

export interface MaskComponent {
  id: string
  mode: MaskComponentMode
  enabled: boolean
  label?: string
  /** Gradient geometry; absent means raster, the region-mask convention. */
  mask?: RegionMask
  /** Compact raster coverage payload; gradient components carry none. */
  mask_ref?: string
  /** Top-left of the compact payload in this component's authored frame. */
  payload_origin?: [number, number]
  /** Complete affine from this component's payload into document space. */
  payload_to_document?: number[]
  /** The geometry below the region when THIS component was authored. */
  payload_frame?: { matrix: number[]; width: number; height: number }
  /**
   * What this selection was a selection OF, when it came from a recomputable
   * semantic gesture ("sky", the subject). The raster payload is the cached
   * result; this names the thing so it can be re-segmented later.
   */
  semantic?: SelectionSemantic
  /**
   * The payload stores coverage as opaque white-on-black LUMINANCE rather
   * than alpha — the convention generative submission masks use. Composition
   * converts it before mixing with alpha-based components.
   */
  luminance?: boolean
}

/**
 * One editable repair inside a Retouch row. A brush gesture may define its
 * mask, but the region—not any individual dab—is the persistent child.
 */
export interface RetouchRegion {
  id: string
  kind: RetouchRegionKind
  enabled: boolean
  label?: string
  /**
   * Absent when `mask` is a gradient: those regions store geometry, not
   * pixels, and have no payload to reference.
   */
  mask_ref?: string
  /** Absent means `{kind:'raster'}` — see RegionMask. */
  mask?: RegionMask
  /**
   * The composition this region's effective mask is composed from, when the mask
   * has been made composite. Absent — every document written before this
   * existed, and every region whose mask is still one gesture — means
   * `mask`/`mask_ref` are the authority, exactly as before. Present means
   * this list is the SOLE authority and the legacy fields are cleared: a
   * region holding both would render one and silently ignore the other.
   */
  mask_components?: MaskComponent[]
  /**
   * Complete affine from this region's compact payload (or gradient geometry)
   * into permanent document space.
   */
  payload_to_document?: number[]
  /** Read compatibility and authored raster dimensions for older documents. */
  payload_frame?: { matrix: number[]; width: number; height: number }
  /** Heal/Clone/Patch donor anchor in the parent's authored pixel frame. */
  source?: { x: number; y: number }
  /** Destination anchor paired with `source` for canvas feedback. */
  target?: { x: number; y: number }
  /** New regions store source/target directly in permanent document space. */
  points_in_document?: boolean
  /** Cached or generated repair pixels, when this region has them. */
  result_ref?: string
  /** Top-left of the cropped mask/result payload in the authored frame. */
  payload_origin?: [number, number]
  sampled_input_hash?: string | null
  settings: RetouchRegionSettings
}

/**
 * The one intentional hierarchy level in the Edits stack. It remains one
 * top-level row while its regions are selected and edited on the canvas.
 */
export interface RetouchRegionsOp extends BaseOp {
  class: 'container'
  exec: { kind: 'retouch-regions'; version: 1 }
  /** Input beneath the container when its first pixel-reading region was made. */
  sampled_input_hash?: string | null
  defaults: RetouchRegionSettings
  regions: RetouchRegion[]
}

export type ContainerOp =
  | PaintLayerOp
  | LegacyPaintLayerOp
  | RetouchRegionsOp
  | AnnotationOp

export type Op = ParametricOp | GenerativeOp | ContainerOp

export interface DocumentBase {
  asset_id: number
  revision_id: number
  media_id: number
  /** The durable pixel reference; media ids are recyclable rowids. */
  file_hash: string
  width: number
  height: number
  /**
   * A payload in the document's own directory that supplies the base pixels
   * instead of the revision's media.
   *
   * Written only by the flatten migration, which bakes a document that still
   * had whole-image steps down to the pixels those steps produced. The
   * asset/revision ids stay as they were: the save path still commits against
   * the same revision, and the flattened pixels are what the stack now sits on.
   */
  payload_ref?: string
}

/**
 * The terminal stage, and deliberately NOT a row.
 *
 * Upscale is the one operation allowed to change the base, and it does that at
 * the save boundary — the only place a base change is legitimate. Keeping it
 * out of `edits` is what stops it becoming a fence: nothing in the stack reads
 * a composite it then replaces.
 *
 * `params` holds the TOOL's own parameters, by schema property name, exactly as
 * ToolView holds them. The editor knows nothing about any particular upscaler:
 * the `upscale-image` task defines the interface (`x-control: upscale_resolution`
 * → `scale_factor` or `resolution`, plus whatever else a tool declares), the
 * catalog defines the tool list, and the shared payload builder turns this into
 * an invocation. A hardcoded factor name here would work for one provider and
 * silently do nothing for the next.
 */
export interface OutputStage {
  /** Off by default: a save writes the working size unless asked otherwise. */
  enabled: boolean
  /** `photo` runs a catalog upscale-image tool; `resample` is client-side Lanczos. */
  method: 'photo' | 'resample'
  /** Recorded when method is `photo`; same picker semantics as any generative op. */
  tool_id: string | null
  /**
   * Tool parameters by schema property name, plus the upscale picker's own
   * state (`resolutionMode` / `scaleFactor` / `targetResolution`) under the
   * same names ToolView uses, so the payload builder resolves them identically.
   */
  params: Record<string, any>
}

export const DEFAULT_OUTPUT: OutputStage = {
  enabled: false,
  method: 'photo',
  tool_id: null,
  params: {},
}

export interface StackDocument {
  format: 'stimma-image-stack'
  version: 1
  base: DocumentBase
  canvas: { width: number; height: number }
  /** Bottom to top: index 0 composites first. */
  edits: Op[]
  /** Absent on documents written before the output stage existed: 1×. */
  output?: OutputStage
  /**
   * Whether this exact working state has changes not represented by a committed
   * Asset Revision. Autosaving document.json and reloading the app do not
   * change this boundary.
   */
  has_uncommitted_changes?: boolean
  /** Hash of the image-producing document state represented by last_commit. */
  committed_state_hash?: string
  /** The last Asset Revision this working state was committed to. */
  last_commit?: { asset_id: number; revision_id: number; autosave?: boolean }
}

/**
 * One document edit, as recorded in journal.jsonl. `inverse` carries whatever
 * undo needs to put the document back — for a removal, the whole op.
 */
export interface JournalEntry {
  seq: number
  ts?: string
  action: string
  op_id?: string
  /** Applied to move forward. */
  forward?: any
  /** Applied to move back. */
  inverse?: any
  /** Checkpoint entries carry a full document snapshot. */
  document?: StackDocument
}

export const DOCUMENT_FORMAT = 'stimma-image-stack'
export const DOCUMENT_VERSION = 1

export function isGenerative(op: Op): op is GenerativeOp {
  return op.class === 'patch'
}

/** The candidate currently supplying this op's pixels, if any. */
export function pickedCandidate(op: Op): Candidate | null {
  if (!isGenerative(op) || !op.picked) return null
  return op.candidates.find(c => c.id === op.picked) || null
}
