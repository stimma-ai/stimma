/**
 * Scheduling for the connected server's update status.
 *
 * Status is only interesting at a fast cadence while an update, restart, or
 * check is underway. An idle client refreshes rarely and otherwise relies on
 * events (reconnects, returning to the foreground, explicit checks). Idle
 * polling stops while the app is backgrounded or the device is offline, and a
 * single refresh runs when it returns. An operation in flight is not optional
 * and keeps its cadence, backing off while the server cannot be reached.
 */
export const ACTIVE_STATUS_POLL_MS = 3_000
export const IDLE_STATUS_POLL_MS = 10 * 60_000
/** Keep the fast cadence briefly after a command, before the server reports it. */
export const COMMAND_BURST_MS = 15_000
/** Cap for the active cadence while status requests keep failing. */
export const MAX_RETRY_POLL_MS = 60_000

/**
 * Active cadence after `failures` consecutive failed requests: 3 s, then
 * doubling to a 60 s cap, with ±20% jitter so clients do not retry in step.
 */
export function activePollDelay(failures: number, random: () => number = Math.random): number {
  if (failures <= 0) return ACTIVE_STATUS_POLL_MS
  const base = Math.min(MAX_RETRY_POLL_MS, ACTIVE_STATUS_POLL_MS * 2 ** failures)
  return Math.round(base * (0.8 + 0.4 * random()))
}

export interface PollConditions {
  active: boolean
  foreground: boolean
  online: boolean
  /** Consecutive failed status requests. */
  failures?: number
}

/** Milliseconds until the next status refresh, or null while polling is suspended. */
export function statusPollDelay({ active, foreground, online, failures = 0 }: PollConditions,
  random: () => number = Math.random): number | null {
  if (active) return activePollDelay(failures, random)
  return foreground && online ? IDLE_STATUS_POLL_MS : null
}

export interface PollTimers {
  set(callback: () => void, ms: number): unknown
  clear(handle: unknown): void
}

export interface StatusPoller {
  /** Refresh now (or once on return if suspended), then reschedule. */
  wake(): void
  /** Recompute the next refresh after the active state changed. */
  reschedule(): void
  setForeground(foreground: boolean): void
  setOnline(online: boolean): void
  stop(): void
}

export function createStatusPoller(options: {
  /** Resolves false when the server could not be reached. */
  refresh: () => Promise<boolean | undefined | void>
  isActive: () => boolean
  random?: () => number
  foreground?: boolean
  online?: boolean
  timers?: PollTimers
}): StatusPoller {
  const timers: PollTimers = options.timers ?? {
    set: (callback, ms) => setTimeout(callback, ms),
    clear: handle => clearTimeout(handle as ReturnType<typeof setTimeout>),
  }
  let foreground = options.foreground ?? true
  let online = options.online ?? true
  let timer: unknown
  let running = false
  let again = false
  let stopped = false
  let failures = 0

  const suspended = () => (!foreground || !online) && !options.isActive()
  function clear() {
    if (timer !== undefined) timers.clear(timer)
    timer = undefined
  }
  function reschedule() {
    clear()
    if (stopped || running) return
    const delay = statusPollDelay({ active: options.isActive(), foreground, online, failures }, options.random)
    if (delay !== null) timer = timers.set(wake, delay)
  }
  function wake() {
    if (stopped) return
    if (suspended()) { clear(); return }
    if (running) { again = true; return }
    clear()
    running = true
    // Events (reconnect, online, foreground) still refresh immediately; only
    // the timer backs off while requests fail.
    void options.refresh().then(result => { failures = result === false ? failures + 1 : 0 },
      () => { failures++ }).finally(() => {
      running = false
      if (again && !stopped) { again = false; wake(); return }
      reschedule()
    })
  }
  function setCondition(update: () => void) {
    const wasSuspended = suspended()
    update()
    if (suspended()) { clear(); return }
    // One catch-up refresh on return; the regular schedule follows it.
    if (wasSuspended) wake()
  }
  return {
    wake,
    reschedule,
    setForeground: value => setCondition(() => { foreground = value }),
    setOnline: value => setCondition(() => { online = value }),
    stop() { stopped = true; clear() },
  }
}
