// Tool View's prompt feature (PROMPT_BRAND) checks each image's choices fit together
// with a small model the app downloads at launch. A run that needs it waits for it,
// with one status line on the run's tile, and goes ahead without it only when the
// server says it can't be had (offline, Privacy Lockdown, a download that stopped).
// The server owns that decision (GET /prompt-programs/fix-judge): `waiting` while it's
// worth waiting, `unjudged` with the reason once it isn't.

export interface JudgeState {
  status?: string
  waiting?: boolean
  percent?: number
  /** Why a run would go without the check right now: unavailable, stalled, lockdown, error. */
  unjudged?: string
}

/** The tile's status while a run waits: "Getting Fluent ready… 62%". */
export function judgeWaitLabel(state: JudgeState | null | undefined, brand: string): string {
  const head = `Getting ${brand} ready…`
  const pct = state?.percent
  return state?.status === 'downloading' && typeof pct === 'number' && pct > 0 ? `${head} ${pct}%` : head
}

/** Whether to tell the user (once) that runs are going without the check: not under
    Privacy Lockdown, where the user chose no downloads (Generation details says so). */
export function tellsUnjudged(state: JudgeState | null | undefined): boolean {
  return !!state?.unjudged && state.unjudged !== 'lockdown'
}

/** Whether this session has said so already (module state: once per app session). */
export const judgeNotice = { told: false }

/** The one-time notice, with Try again beside it. */
export function unjudgedMessage(brand: string): string {
  return `${brand} couldn’t finish getting ready, so some choices may not fit together. It’ll keep trying.`
}

/** Generation details: one quiet line when this image's choices weren't checked. */
export function unjudgedNote(run: any, brand: string): string | null {
  const why = run?.fix?.skipped
  if (!why) return null
  return why === 'lockdown'
    ? 'Choices weren’t checked to fit together: Privacy Lockdown is on.'
    : `Choices weren’t checked to fit together: ${brand} wasn’t ready.`
}

export type JudgeWaitOutcome = 'ready' | 'unjudged' | 'cancelled'

export interface JudgeWaitDeps {
  /** GET /prompt-programs/fix-judge (`start` on the first ask). Throwing ends the wait. */
  fetch: (start: boolean) => Promise<JudgeState>
  /** Each state while waiting, for the tile. */
  onWaiting: (state: JudgeState) => void
  cancelled: () => boolean
  sleep?: (ms: number) => Promise<void>
  intervalMs?: number
}

/** Wait before a run while the server says it's worth waiting. Never longer: the
    server stops saying so once the download stops moving, so this never hangs. */
export async function waitForJudge(deps: JudgeWaitDeps): Promise<{ outcome: JudgeWaitOutcome; state: JudgeState | null }> {
  const sleep = deps.sleep ?? ((ms: number) => new Promise<void>(r => setTimeout(r, ms)))
  let state: JudgeState | null = null
  for (let first = true; ; first = false) {
    try {
      state = await deps.fetch(first)
    } catch {
      return { outcome: 'ready', state: null }  // can't ask: the server decides when the run arrives
    }
    if (deps.cancelled()) return { outcome: 'cancelled', state }
    if (!state?.waiting) return { outcome: state?.unjudged ? 'unjudged' : 'ready', state }
    deps.onWaiting(state)
    await sleep(deps.intervalMs ?? 1000)
    if (deps.cancelled()) return { outcome: 'cancelled', state }
  }
}
