/**
 * Keyframes: stills or short clips pinned at times on a video tool's output
 * (STP `x-control: "keyframes"`). The tool view keeps rich items for display
 * and editing; `toWire` produces the `{media, at, from, length, sound}` objects
 * the tool schema declares.
 */

export interface KeyframesConfig {
  /** Parameter name, usually `keyframes`. */
  name: string
  max: number
  /** `ends` restricts pins to Start and End. */
  positions: 'any' | 'ends'
  /** Parameter the timeline's length follows (`x-timeline.duration`). */
  durationParam: string
  fps: number
  /** Valid clip lengths in frames are `min + k * step`; null means stills only. */
  clipFrames: { min: number; step: number } | null
  /** Whether a clip can carry its sound. */
  sound: boolean
}

export interface KeyframeItem {
  id: string
  /** Library media id of the source (image, or the video a frame/clip comes from). */
  mediaId?: number
  hash?: string
  /** The still sent for an image or a frame; for a clip, the source video. */
  path: string
  isVideo: boolean
  sourcePath?: string
  sourceDuration?: number
  sourceFps?: number
  /** Seconds into the source video. */
  from?: number
  /** Clip length in seconds; 0/undefined pins a single frame. */
  length?: number
  sound?: boolean
  /** Seconds into the output. */
  at: number
  /** Start/End pins follow the timeline's ends when the duration changes. */
  anchor?: 'start' | 'end' | null
  /** Still shown on the strip for video-sourced items (a frame grab). */
  thumbPath?: string
}

export interface WireKeyframe {
  media: string
  at: number
  from?: number
  length?: number
  sound?: boolean
}

export function keyframesConfigFromSchema(name: string, schema: any): KeyframesConfig {
  const timeline = schema?.['x-timeline'] || {}
  const clip = schema?.['x-clip-frames']
  const itemProps = schema?.items?.properties || {}
  return {
    name,
    max: Number(schema?.['x-max-items'] ?? schema?.maxItems ?? 6),
    positions: schema?.['x-positions'] === 'ends' ? 'ends' : 'any',
    durationParam: timeline.duration || 'duration',
    fps: Number(timeline.fps) || 24,
    clipFrames: clip && itemProps.length ? { min: Number(clip.min) || 1, step: Math.max(1, Number(clip.step) || 1) } : null,
    sound: !!itemProps.sound,
  }
}

export function isClip(item: KeyframeItem): boolean {
  return !!(item.isVideo && item.length && item.length > 0)
}

export function effectiveAt(item: KeyframeItem, duration: number): number {
  if (item.anchor === 'start') return 0
  if (item.anchor === 'end') return Math.max(0, duration - (isClip(item) ? item.length! : 0))
  return item.at
}

/** Clip lengths (seconds) the model accepts, capped by the source and the output. */
export function clipLengths(config: KeyframesConfig, limit: number, count = 4): number[] {
  if (!config.clipFrames) return []
  const out: number[] = []
  for (let k = 0; out.length < count; k++) {
    const seconds = (config.clipFrames.min + k * config.clipFrames.step) / config.fps
    if (seconds > limit + 1e-6) break
    out.push(seconds)
  }
  return out
}

export function toWire(items: KeyframeItem[], duration: number): WireKeyframe[] {
  return [...items]
    .sort((a, b) => effectiveAt(a, duration) - effectiveAt(b, duration))
    .map((item) => {
      const clip = isClip(item)
      const wire: WireKeyframe = {
        media: clip ? (item.sourcePath || item.path) : item.path,
        // End pins send the duration itself: "at the end" survives the model
        // rounding its length up to a frame grid.
        at: item.anchor === 'end' && !clip ? duration : round3(effectiveAt(item, duration)),
      }
      if (clip) {
        wire.from = round3(item.from || 0)
        wire.length = round3(item.length!)
        if (item.sound) wire.sound = true
      }
      return wire
    })
}

/** Library ids for lineage, positional with `toWire`'s order. */
export function lineageIds(items: KeyframeItem[], duration: number): (number | null)[] {
  return [...items]
    .sort((a, b) => effectiveAt(a, duration) - effectiveAt(b, duration))
    .map((item) => (typeof item.mediaId === 'number' ? item.mediaId : null))
}

/** Rebuild display items from a past job's parameters ("Generate more like this"). */
export function fromWire(wire: unknown, mediaIds: unknown, duration: number): KeyframeItem[] {
  if (!Array.isArray(wire)) return []
  const ids = Array.isArray(mediaIds) ? mediaIds : []
  return wire
    .filter((w): w is WireKeyframe => !!w && typeof w === 'object' && typeof (w as any).media === 'string')
    .map((w, i) => {
      const clip = !!(w.length && w.length > 0)
      const isVideo = clip || isVideoPath(w.media)
      const at = Number(w.at) || 0
      return {
        id: newKeyframeId(),
        mediaId: typeof ids[i] === 'number' ? ids[i] : undefined,
        path: w.media,
        isVideo,
        sourcePath: isVideo ? w.media : undefined,
        from: clip ? Number(w.from) || 0 : undefined,
        length: clip ? Number(w.length) : undefined,
        sound: clip ? !!w.sound : undefined,
        at,
        anchor: at <= 0 ? 'start' : (duration && at >= duration ? 'end' : null),
      }
    })
}

export interface KeyframesProblem { id: string; reason: string }

export function keyframesProblems(items: KeyframeItem[], duration: number, config: KeyframesConfig): KeyframesProblem[] {
  const problems: KeyframesProblem[] = []
  for (const item of items) {
    const start = effectiveAt(item, duration)
    const end = start + (isClip(item) ? item.length! : 0)
    if (start < 0 || end > duration + 1e-6) problems.push({ id: item.id, reason: 'Past the end of the video' })
  }
  if (items.length > config.max) {
    problems.push({ id: items[items.length - 1].id, reason: `Up to ${config.max} keyframes` })
  }
  return problems
}

export function newKeyframeId(): string {
  return `kf_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

const VIDEO_EXT = /\.(mp4|mov|avi|mkv|webm|m4v)$/i

export function isVideoPath(path: string): boolean {
  return VIDEO_EXT.test(path)
}

function round3(n: number): number {
  return Math.round(n * 1000) / 1000
}
