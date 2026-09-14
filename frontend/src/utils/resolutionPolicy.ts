/**
 * Output-size policy for tools with width/height (freeform or a fixed list).
 *
 * A tool always remembers a fixed shape (ratio) and size (megapixels, or a
 * short-edge tier for list-constrained tools). On top of that, each axis may
 * follow the first input image. Following only bites while an image is
 * present, so with no images an all-in-one model behaves as a plain
 * text-to-image tool showing its fixed values.
 *
 * `resolveResolution` is the single place that turns (policy, image, schema)
 * into concrete width/height. ToolView, the flow form, chain steps and tool
 * hops all go through it so the same inputs always give the same answer.
 */
import { detectResolutionControls, snapDimsToGrid } from './resolutionControls.ts'

export const RATIO_CHOICES = ['9:16', '2:3', '3:4', '4:5', '1:1', '5:4', '4:3', '3:2', '16:9', '21:9'] as const

export interface ResolutionPolicy {
  /** 'W:H'. Either one of RATIO_CHOICES or a reduced custom ratio from typed dims. */
  ratio: string
  /** Megapixel budget for freeform tools. */
  mp: number
  /** Short edge in px for list-constrained tools (480 → "480p"). */
  tier: number
  /** Shape follows the first input image while one is present. */
  followShape: boolean
  /** Size follows the first input image while one is present. */
  followSize: boolean
}

export interface ImageDims {
  width: number
  height: number
  name?: string
}

export interface ResolvedResolution {
  width: number
  height: number
  /** Display label for the shape ('3:4', or '~3:4' when only close). */
  ratioLabel: string
  /** Chip that should light up, if any ratio choice is within tolerance. */
  ratioChoice: string | null
  mp: number
  /** Short edge of the chosen pair (list tools). */
  tier: number | null
  shapeFromImage: boolean
  sizeFromImage: boolean
  /** Set when a fixed ratio disagrees with the image, so the input gets cropped. */
  cropWarning: string | null
  /** True when the remembered tier isn't offered at this ratio and a neighbour was used. */
  tierMissing: boolean
}

export interface TierGroup {
  ratio: string
  ratioValue: number
  /** Pairs sorted by area ascending. */
  pairs: [number, number][]
}

type SchemaProps = Record<string, any> | null | undefined

export function ratioValue(ratio: string): number {
  const [a, b] = ratio.split(':').map(Number)
  if (!a || !b) return 1
  return a / b
}

function gcd(a: number, b: number): number {
  while (b) { ;[a, b] = [b, a % b] }
  return a
}

/** Reduced 'W:H' for arbitrary dims, e.g. 1216×1344 → '19:21'. */
export function customRatio(width: number, height: number): string {
  const g = gcd(Math.round(width), Math.round(height)) || 1
  return `${Math.round(width) / g}:${Math.round(height) / g}`
}

/** Nearest of `choices` to width/height by log-ratio distance. */
export function nearestRatio(width: number, height: number, choices: readonly string[] = RATIO_CHOICES): string {
  let best = choices[0]
  let bestDist = Infinity
  const target = Math.log(width / height)
  for (const c of choices) {
    const d = Math.abs(Math.log(ratioValue(c)) - target)
    if (d < bestDist) { bestDist = d; best = c }
  }
  return best
}

/** Ratio choice within ~4% of width/height, or null. */
export function matchingRatio(width: number, height: number, choices: readonly string[] = RATIO_CHOICES): string | null {
  const near = nearestRatio(width, height, choices)
  const d = Math.abs(Math.log(ratioValue(near)) - Math.log(width / height))
  return d < 0.04 ? near : null
}

export function formatMegapixels(mp: number): string {
  if (!Number.isFinite(mp) || mp <= 0) return '0MP'
  const s = mp < 1 ? mp.toFixed(2) : mp.toFixed(1)
  return `${s.replace(/\.?0+$/, '')}MP`
}

export function formatTier(shortEdge: number): string {
  return `${shortEdge}p`
}

/** Group a tool's allowed pairs by ratio, tallest first, pairs by area. */
export function tierGroups(allowed: [number, number][]): TierGroup[] {
  const groups = new Map<string, TierGroup>()
  for (const [w, h] of allowed) {
    // Group under the nearest common ratio when it's reasonably close (~12%),
    // so 3168×1296 sits with 21:9 instead of getting its own '22:9' tile.
    const near = nearestRatio(w, h)
    const dist = Math.abs(Math.log(ratioValue(near)) - Math.log(w / h))
    const label = dist < 0.12 ? near : customRatio(w, h)
    let g = groups.get(label)
    if (!g) { g = { ratio: label, ratioValue: ratioValue(label), pairs: [] }; groups.set(label, g) }
    g.pairs.push([w, h])
  }
  for (const g of groups.values()) g.pairs.sort((a, b) => a[0] * a[1] - b[0] * b[1])
  return [...groups.values()].sort((a, b) => a.ratioValue - b.ratioValue)
}

function nearestGroup(groups: TierGroup[], width: number, height: number): TierGroup {
  const label = nearestRatio(width, height, groups.map(g => g.ratio))
  return groups.find(g => g.ratio === label) ?? groups[0]
}

function pairByTier(group: TierGroup, tier: number): { pair: [number, number]; exact: boolean } {
  let best = group.pairs[0]
  let bestDist = Infinity
  for (const p of group.pairs) {
    const d = Math.abs(Math.min(p[0], p[1]) - tier)
    if (d < bestDist) { bestDist = d; best = p }
  }
  return { pair: best, exact: bestDist === 0 }
}

function pairByArea(group: TierGroup, area: number): [number, number] {
  let best = group.pairs[0]
  let bestDist = Infinity
  for (const p of group.pairs) {
    const d = Math.abs(p[0] * p[1] - area)
    if (d < bestDist) { bestDist = d; best = p }
  }
  return best
}

/**
 * Megapixel range the tool can actually reach at `ratio`, from the schema's
 * per-axis minimum/maximum. This is what the size slider spans, so its top
 * end is where the model really stops (a 2048-per-axis model tops out at
 * ~3.1MP for 4:3, ~4.2MP for 1:1).
 */
export function megapixelBounds(props: SchemaProps, ratio: number): { min: number; max: number } {
  const p = props || {}
  const maxW = Number(p.width?.maximum) || 4096
  const maxH = Number(p.height?.maximum ?? p.width?.maximum) || 4096
  const minW = Number(p.width?.minimum) || 256
  const minH = Number(p.height?.minimum ?? p.width?.minimum) || 256
  const r = ratio > 0 ? ratio : 1
  const hiW = Math.min(maxW, maxH * r)
  const hiH = Math.min(maxH, maxW / r)
  const loW = Math.max(minW, minH * r)
  const loH = Math.max(minH, minW / r)
  const max = (hiW * hiH) / 1_000_000
  const min = Math.min((loW * loH) / 1_000_000, max)
  return { min, max }
}

export function dimsForMegapixels(mp: number, ratio: number, props: SchemaProps): { width: number; height: number } {
  const h = Math.sqrt((mp * 1_000_000) / ratio)
  const w = h * ratio
  return snapDimsToGrid(withDefaultStep(props), w, h)
}

/** Freeform tools without an explicit step still want sensible rounding. */
function withDefaultStep(props: SchemaProps): Record<string, any> {
  const p = props || {}
  const fix = (axis: any) => (axis && axis['x-step']) ? axis : { ...(axis || {}), 'x-step': 16 }
  return { ...p, width: fix(p.width), height: fix(p.height) }
}

/**
 * Turn a policy into concrete dimensions.
 * `image` is the first input image (or start frame), or null.
 */
export function resolveResolution(policy: ResolutionPolicy, image: ImageDims | null, props: SchemaProps): ResolvedResolution {
  const allowed = detectResolutionControls(props).allowedDimensions
  const hasImage = !!(image && image.width > 0 && image.height > 0)
  const shapeFromImage = policy.followShape && hasImage
  const sizeFromImage = policy.followSize && hasImage

  if (allowed && allowed.length) {
    const groups = tierGroups(allowed)
    const group = shapeFromImage
      ? nearestGroup(groups, image!.width, image!.height)
      : (groups.find(g => g.ratio === policy.ratio) ?? nearestGroup(groups, ratioValue(policy.ratio), 1))
    let pair: [number, number]
    let tierMissing = false
    if (sizeFromImage) {
      pair = pairByArea(group, image!.width * image!.height)
    } else {
      const r = pairByTier(group, policy.tier)
      pair = r.pair
      tierMissing = !r.exact
    }
    return {
      width: pair[0],
      height: pair[1],
      ratioLabel: group.ratio,
      ratioChoice: group.ratio,
      mp: (pair[0] * pair[1]) / 1_000_000,
      tier: Math.min(pair[0], pair[1]),
      shapeFromImage,
      sizeFromImage,
      cropWarning: cropWarning(hasImage && !shapeFromImage ? image : null, group.ratioValue, group.ratio),
      tierMissing,
    }
  }

  // Freeform
  let width: number
  let height: number
  let rv: number
  if (shapeFromImage) {
    rv = image!.width / image!.height
  } else {
    rv = ratioValue(policy.ratio)
  }
  if (shapeFromImage && sizeFromImage) {
    ;({ width, height } = snapDimsToGrid(props, image!.width, image!.height))
  } else {
    const mp = sizeFromImage ? (image!.width * image!.height) / 1_000_000 : policy.mp
    ;({ width, height } = dimsForMegapixels(mp, rv, props))
  }
  const choice = matchingRatio(width, height)
  return {
    width,
    height,
    ratioLabel: choice ?? `~${nearestRatio(width, height)}`,
    ratioChoice: choice,
    mp: (width * height) / 1_000_000,
    tier: null,
    shapeFromImage,
    sizeFromImage,
    cropWarning: cropWarning(hasImage && !shapeFromImage ? image : null, rv, choice ?? policy.ratio),
    tierMissing: false,
  }
}

function cropWarning(image: ImageDims | null, ratio: number, label: string): string | null {
  if (!image) return null
  const d = Math.abs(Math.log(image.width / image.height) - Math.log(ratio))
  if (d < 0.08) return null
  const imgLabel = matchingRatio(image.width, image.height) ?? `~${nearestRatio(image.width, image.height)}`
  return `${image.name ?? 'The image'} is ${imgLabel} and will be cropped to ${label}`
}

/** Default policy for a tool: its schema default size, following the image if it takes one. */
export function defaultResolutionPolicy(props: SchemaProps, hasImageInput: boolean): ResolutionPolicy {
  const p = props || {}
  const allowed = detectResolutionControls(p).allowedDimensions
  let w = Number(p.width?.default) || 0
  let h = Number(p.height?.default) || 0
  if (allowed && allowed.length) {
    if (!allowed.some(([aw, ah]) => aw === w && ah === h)) {
      // Prefer the most square pair, like the old picker did.
      let best = allowed[0]
      let bestDiff = Infinity
      for (const pair of allowed) {
        const diff = Math.abs(Math.log(pair[0] / pair[1]))
        if (diff < bestDiff) { bestDiff = diff; best = pair }
      }
      ;[w, h] = best
    }
  } else if (!w || !h) {
    w = 1024; h = 1024
  }
  return {
    ratio: matchingRatio(w, h) ?? customRatio(w, h),
    mp: roundMp((w * h) / 1_000_000),
    tier: Math.min(w, h),
    followShape: hasImageInput,
    // Video (list) tools keep their own size; image tools match the image.
    followSize: hasImageInput && !(allowed && allowed.length),
  }
}

export function roundMp(mp: number): number {
  return Number(mp.toFixed(3))
}

/** Adopt concrete dims (typed, preset, remix) as the fixed values. Never touches follow flags. */
export function policyWithDims(policy: ResolutionPolicy, width: number, height: number): ResolutionPolicy {
  return {
    ...policy,
    ratio: matchingRatio(width, height) ?? customRatio(width, height),
    mp: roundMp((width * height) / 1_000_000),
    tier: Math.min(width, height),
  }
}

/** What a hop carries: shape travels with the work, size stays with the tool. */
export interface CarriedSizePolicy {
  ratio: string
  followShape: boolean
}

export function carriedPolicy(policy: ResolutionPolicy, resolved: ResolvedResolution): CarriedSizePolicy {
  return {
    // A followed shape resolves to the concrete ratio so a t2i target can use it.
    ratio: resolved.ratioChoice ?? policy.ratio,
    followShape: policy.followShape,
  }
}

/**
 * Apply a carried policy to the target tool's remembered policy.
 * If the target matches image size, shape follows the image too: going into an
 * editor is always pixel for pixel.
 */
export function applyCarriedPolicy(target: ResolutionPolicy, carried: CarriedSizePolicy | null | undefined, hasImageInput: boolean): ResolutionPolicy {
  if (!carried || typeof carried.ratio !== 'string') return target
  const followShape = hasImageInput && (carried.followShape || target.followSize)
  return { ...target, ratio: carried.ratio, followShape }
}

/** Migrate the pre-policy lock flags (lockSize / lockArea) to a policy. */
export function policyFromLegacyLocks(base: ResolutionPolicy, lockSize: boolean, lockArea: boolean): ResolutionPolicy {
  if (lockSize) return { ...base, followShape: false, followSize: false }
  if (lockArea) return { ...base, followShape: true, followSize: false }
  return base
}

export function isResolutionPolicy(v: any): v is ResolutionPolicy {
  return !!v && typeof v === 'object' && typeof v.ratio === 'string' && typeof v.mp === 'number'
    && typeof v.tier === 'number' && typeof v.followShape === 'boolean' && typeof v.followSize === 'boolean'
}
