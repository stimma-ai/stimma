/**
 * Timeline evaluation: "what is on screen at time t" as a pure function of
 * the document. Shared by the preview player, the sequencer strip, and any
 * future export path — there is exactly one implementation of timeline math.
 */

export interface TimelineClipMedia {
  media_id: number
}

export interface TimelineEntry {
  kind: 'clip' | 'slot'
  id: string
  media?: TimelineClipMedia
  in?: number
  out?: number
  duration?: number
  label?: string
  brief?: string
  notes?: string
  silence?: boolean
}

export interface TimelineTrack {
  kind: 'video' | 'audio'
  entries: TimelineEntry[]
}

export interface TimelineState {
  title: string
  fps: number
  width: number
  height: number
  tracks: TimelineTrack[]
}

export function entryDuration(entry: TimelineEntry): number {
  if (entry.kind === 'slot') return entry.duration || 0
  if (entry.out != null) return entry.out - (entry.in || 0)
  return entry.duration || 0
}

export function trackDuration(track: TimelineTrack): number {
  return track.entries.reduce((sum, e) => sum + entryDuration(e), 0)
}

export function timelineDuration(state: TimelineState): number {
  return Math.max(0, ...state.tracks.map(trackDuration))
}

export interface EntryPlacement {
  entry: TimelineEntry
  index: number
  /** Timeline time where this entry starts */
  start: number
  duration: number
}

export function trackPlacements(track: TimelineTrack): EntryPlacement[] {
  const placements: EntryPlacement[] = []
  let start = 0
  track.entries.forEach((entry, index) => {
    const duration = entryDuration(entry)
    placements.push({ entry, index, start, duration })
    start += duration
  })
  return placements
}

export interface EvalResult extends EntryPlacement {
  /** Offset into the entry (timeline seconds since it began) */
  localTime: number
  /** Source-media time for clips: in + localTime (clamped to out) */
  sourceTime: number
}

/**
 * The entry under the playhead for one track, or null past the track's end.
 */
export function evaluateTrack(track: TimelineTrack, t: number): EvalResult | null {
  for (const placement of trackPlacements(track)) {
    if (t >= placement.start && t < placement.start + placement.duration) {
      const localTime = t - placement.start
      return {
        ...placement,
        localTime,
        sourceTime: (placement.entry.in || 0) + localTime,
      }
    }
  }
  return null
}

export function evaluate(state: TimelineState, t: number): {
  video: EvalResult | null
  audio: EvalResult | null
} {
  const video = state.tracks.find((tr) => tr.kind === 'video')
  const audio = state.tracks.find((tr) => tr.kind === 'audio')
  return {
    video: video ? evaluateTrack(video, t) : null,
    audio: audio ? evaluateTrack(audio, t) : null,
  }
}

export function formatTimecode(seconds: number): string {
  const s = Math.max(0, seconds)
  const mins = Math.floor(s / 60)
  const secs = Math.floor(s % 60)
  const tenths = Math.floor((s % 1) * 10)
  return `${mins}:${secs.toString().padStart(2, '0')}.${tenths}`
}
