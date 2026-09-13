/**
 * Composite masks: a region's effective mask as an ordered COMPOSITION of editable
 * components rather than one flattened bitmap.
 *
 * The first component is the base; later components are modifiers, each
 * meeting the coverage composed so far through its mode. Composition is soft —
 * every operand is a 0..1 alpha field, never a binary set:
 *
 *   add:       acc = max(acc, c)
 *   subtract:  acc = acc × (1 − c)
 *   intersect: acc = acc × c
 *
 * A region without `mask_components` still IS a one-component mask — the
 * synthesized view here is how the UI shows every existing document's region
 * as `Mask → base` without touching the stored document. Storage only
 * upgrades when the user makes a structural mask edit, and from then on the
 * component list is the sole authority.
 *
 * Everything except `composeMaskCanvases` is DOM-free so it can be tested
 * directly, matching regionMask.ts.
 */
import type {
  MaskComponent,
  MaskComponentMode,
  RetouchRegion,
} from './types.ts'
import { isDegenerate, isGradientMask } from './regionMask.ts'

export function hasMaskComponents(
  region: Pick<RetouchRegion, 'mask_components'>,
): boolean {
  return (region.mask_components?.length ?? 0) > 0
}

/**
 * The id the synthesized base of a legacy region carries. Deterministic so
 * selection and hover can address it before the region has ever been
 * upgraded; a real upgrade re-mints ids through the caller.
 */
export function legacyBaseComponentId(region: Pick<RetouchRegion, 'id'>): string {
  return `${region.id}:base`
}

/**
 * The component view of a region's mask, whatever generation wrote it.
 *
 * Regions with an explicit list return it. Legacy regions return their single
 * mask as a synthesized base component sharing the region's own anchors — a
 * VIEW of the stored document, never a mutation of it. A legacy region with
 * no coverage yet has no components.
 */
export function regionMaskComponents(
  region: Pick<
    RetouchRegion,
    | 'id' | 'mask' | 'mask_ref' | 'mask_components'
    | 'payload_origin' | 'payload_to_document' | 'payload_frame'
  >,
): MaskComponent[] {
  if (region.mask_components?.length) return region.mask_components
  const gradient = isGradientMask(region.mask)
  if (!gradient && !region.mask_ref) return []
  return [{
    id: legacyBaseComponentId(region),
    mode: 'add',
    enabled: true,
    ...(gradient ? { mask: region.mask } : {}),
    ...(region.mask_ref ? { mask_ref: region.mask_ref } : {}),
    ...(region.payload_origin ? { payload_origin: region.payload_origin } : {}),
    ...(region.payload_to_document
      ? { payload_to_document: region.payload_to_document }
      : {}),
    ...(region.payload_frame ? { payload_frame: region.payload_frame } : {}),
  }]
}

/** Coverage means the component can produce alpha: geometry or a payload. */
export function componentHasCoverage(
  component: Pick<MaskComponent, 'mask' | 'mask_ref'>,
): boolean {
  return isGradientMask(component.mask)
    ? !isDegenerate(component.mask)
    : !!component.mask_ref
}

/**
 * The component view of a GENERATIVE op's mask. A patch op with only the
 * legacy submission mask reads as one luminance base component sharing the
 * op's anchors; an explicit list is authoritative. Unlike a region, the op's
 * `mask_ref` is never cleared by an upgrade — it stays the record of what the
 * existing candidates were sampled through.
 */
export function opMaskComponents(
  op: {
    id: string
    mask_ref?: string
    mask_components?: MaskComponent[]
    payload_to_document?: number[]
    payload_frame?: { matrix: number[]; width: number; height: number }
  },
): MaskComponent[] {
  if (op.mask_components?.length) return op.mask_components
  if (!op.mask_ref) return []
  return [{
    id: `${op.id}:base`,
    mode: 'add',
    enabled: true,
    mask_ref: op.mask_ref,
    luminance: true,
    ...(op.payload_to_document
      ? { payload_to_document: op.payload_to_document }
      : {}),
    ...(op.payload_frame ? { payload_frame: op.payload_frame } : {}),
  }]
}

/**
 * Whether a generative op's mask is the editable kind. Expand's border mask
 * is derived from its edge parameters (there is nothing to author), and a
 * cutout's submission mask is the full frame (the mask worth editing is the
 * returned matte) — both are excluded rather than offered edits that cannot
 * be honored.
 */
export function generativeOpHasEditableMask(op: any): boolean {
  return op?.class === 'patch'
    && op.operation !== 'expand'
    && op.operation !== 'cutout'
    && !!(op.mask_ref || op.mask_components?.length)
}

/**
 * Rewrite a region to be composed from `components`, making the list the sole
 * mask authority. The legacy single-mask fields are cleared rather than
 * mirrored: two representations of one mask is how they drift apart.
 */
export function regionWithMaskComponents(
  region: RetouchRegion,
  components: MaskComponent[],
): RetouchRegion {
  const next: RetouchRegion = {
    ...region,
    mask_components: components,
  }
  delete next.mask
  delete next.mask_ref
  delete next.payload_origin
  delete next.payload_to_document
  return next
}

export interface MaskComposeEntry {
  /** Positioned coverage, 0..255; null when the component has none to give. */
  alpha: Uint8ClampedArray | null
  mode: MaskComponentMode
  enabled: boolean
}

/**
 * Compose positioned component alphas into the effective mask, 0..255.
 *
 * Coverage starts at nothing and every enabled component applies its mode in
 * order. The base is stored with mode `add`, so it seeds the coverage by the
 * same rule everything else follows — and a DISABLED base honestly leaves
 * nothing for an intersect to keep. A component with no alpha yet is skipped:
 * "not authored / unreadable" must dim the composition, not black out the whole
 * mask through an intersect.
 */
export function composeMaskAlpha(
  entries: MaskComposeEntry[],
  length: number,
): Uint8ClampedArray {
  const acc = new Float32Array(length)
  for (const entry of entries) {
    if (!entry.enabled || !entry.alpha) continue
    const alpha = entry.alpha
    if (entry.mode === 'add') {
      for (let i = 0; i < length; i++) {
        const c = alpha[i] / 255
        if (c > acc[i]) acc[i] = c
      }
    } else if (entry.mode === 'subtract') {
      for (let i = 0; i < length; i++) acc[i] *= 1 - alpha[i] / 255
    } else {
      for (let i = 0; i < length; i++) acc[i] *= alpha[i] / 255
    }
  }
  const out = new Uint8ClampedArray(length)
  for (let i = 0; i < length; i++) out[i] = Math.round(acc[i] * 255)
  return out
}

/** What a component row calls itself when nobody has named it. */
export function maskComponentLabel(component: MaskComponent): string {
  if (component.label) return component.label
  const semantic = component.semantic
  if (semantic?.prompt) {
    const prompt = semantic.prompt.trim()
    if (prompt) return prompt.charAt(0).toUpperCase() + prompt.slice(1)
  }
  if (semantic?.intent === 'subject') return 'Subject'
  if (semantic?.intent === 'background') return 'Background'
  if (semantic?.intent === 'sky') return 'Sky'
  if (component.mask?.kind === 'linear') return 'Linear gradient'
  if (component.mask?.kind === 'radial') return 'Radial gradient'
  return 'Selection'
}

/**
 * The mode prefix a component row wears. An `add` in first position IS the
 * base and wears none; a subtract or intersect left first (its base was
 * deleted) keeps its prefix, because coverage starts at nothing and the mode
 * still means exactly what it says.
 */
export function maskComponentModeLabel(
  component: Pick<MaskComponent, 'mode'>,
  index: number,
): string | null {
  if (component.mode === 'subtract') return 'Subtract'
  if (component.mode === 'intersect') return 'Intersect'
  return index === 0 ? null : 'Add'
}

/**
 * Translate an opaque white-on-black luminance mask into the alpha-coverage
 * shape composition works in. Always a NEW canvas — sources may be shared,
 * cached payloads.
 */
export function luminanceToAlphaCanvas(
  source: CanvasImageSource,
  width: number,
  height: number,
): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, width)
  canvas.height = Math.max(1, height)
  const ctx = canvas.getContext('2d', { willReadFrequently: true })!
  ctx.drawImage(source, 0, 0, canvas.width, canvas.height)
  const image = ctx.getImageData(0, 0, canvas.width, canvas.height)
  for (let i = 0; i < image.data.length; i += 4) {
    const value = image.data[i]
    image.data[i] = 255
    image.data[i + 1] = 255
    image.data[i + 2] = 255
    image.data[i + 3] = value
  }
  ctx.putImageData(image, 0, 0)
  return canvas
}

export interface MaskComposeLayer {
  /** Positioned into the output frame already; null contributes nothing. */
  source: CanvasImageSource | null
  mode: MaskComponentMode
  enabled: boolean
}

/**
 * Compose positioned component canvases into the effective mask canvas, with
 * coverage in EVERY channel — the same contract gradientMaskCanvas satisfies,
 * because the two compositing paths disagree about whether a mask keeps its
 * coverage in alpha or in red.
 */
export function composeMaskCanvases(
  layers: MaskComposeLayer[],
  width: number,
  height: number,
): HTMLCanvasElement {
  const w = Math.max(1, width)
  const h = Math.max(1, height)
  const scratch = document.createElement('canvas')
  scratch.width = w
  scratch.height = h
  const scratchCtx = scratch.getContext('2d', { willReadFrequently: true })!

  const entries: MaskComposeEntry[] = layers.map(layer => {
    if (!layer.enabled || !layer.source) {
      return { alpha: null, mode: layer.mode, enabled: layer.enabled }
    }
    scratchCtx.clearRect(0, 0, w, h)
    scratchCtx.drawImage(layer.source, 0, 0, w, h)
    const data = scratchCtx.getImageData(0, 0, w, h).data
    const alpha = new Uint8ClampedArray(w * h)
    for (let p = 0, i = 3; p < alpha.length; p++, i += 4) alpha[p] = data[i]
    return { alpha, mode: layer.mode, enabled: true }
  })

  const composed = composeMaskAlpha(entries, w * h)
  const out = document.createElement('canvas')
  out.width = w
  out.height = h
  const ctx = out.getContext('2d')!
  const image = ctx.createImageData(w, h)
  for (let p = 0, i = 0; p < composed.length; p++, i += 4) {
    image.data[i] = composed[p]
    image.data[i + 1] = composed[p]
    image.data[i + 2] = composed[p]
    image.data[i + 3] = composed[p]
  }
  ctx.putImageData(image, 0, 0)
  return out
}
