// What the composer's background strip says about one task (backend
// agent/v2/background.py). A count "of N" and a filling ring only when the
// run said how many it makes (a gather, or stimma.batch(total=N)); otherwise
// plain counts and a spinning ring, since anything else would be a guess.

export interface BackgroundTaskCounts {
  done: number
  failed: number
  cancelled: number
  generating: number
  queued: number
  preparing: number
  waiting: number
}

// What the run's result cards add up to (backend result_cards.py).
export interface BackgroundTaskProgress {
  title?: string | null
  open?: boolean
  done?: number
  failed?: number
  total?: number
}

export interface BackgroundTaskLine {
  title: string
  summary: string
  /** 0–1 when the run declared its total, else null (indeterminate). */
  fraction: number | null
}

interface TaskLike {
  label?: string
  counts?: Partial<BackgroundTaskCounts>
  items?: { kind?: string }[]
  progress?: BackgroundTaskProgress | null
  /** Set while the task's code hasn't started because another chat's code runs. */
  waiting_for?: string | null
}

const NOUNS: Record<string, string> = {
  image: 'images',
  video: 'videos',
  audio: 'audio clips',
}

function made(task: TaskLike): string {
  const kinds = new Set((task.items || []).map(i => i.kind).filter(Boolean))
  return kinds.size === 1 ? (NOUNS[[...kinds][0] as string] ?? 'items') : 'items'
}

function n(value: number | undefined): number {
  return value || 0
}

export function backgroundTaskLine(task: TaskLike): BackgroundTaskLine {
  const p = task.progress
  const c = task.counts || {}
  const started = n(c.done) + n(c.failed) + n(c.cancelled) + n(c.generating)
    + n(c.queued) + n(c.preparing) + n(c.waiting)

  const declared = p && !p.open && n(p.total) > 0
  const title = task.label || p?.title || (started ? `Generating ${made(task)}` : 'Working…')

  if (task.waiting_for) {
    return { title, summary: `Waiting for ${task.waiting_for}`, fraction: null }
  }

  if (declared) {
    const total = n(p!.total)
    const done = n(p!.done)
    const failed = n(p!.failed)
    return {
      title,
      summary: `${done} of ${total}` + (failed ? ` · ${failed} failed` : ''),
      fraction: Math.min(1, (done + failed) / total),
    }
  }

  const parts: string[] = []
  if (started) parts.push(`${n(c.done)} done`)
  if (c.generating) parts.push(`${c.generating} in progress`)
  const queued = n(c.queued) + n(c.preparing) + n(c.waiting)
  if (queued) parts.push(`${queued} queued`)
  if (c.failed) parts.push(`${c.failed} failed`)
  return { title, summary: parts.join(' · '), fraction: null }
}

/** "4m", "1h 12m": how long an item has been generating. */
export function shortDuration(seconds: number | undefined): string {
  const s = Math.max(0, Math.floor(seconds || 0))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  return m % 60 ? `${h}h ${m % 60}m` : `${h}h`
}
