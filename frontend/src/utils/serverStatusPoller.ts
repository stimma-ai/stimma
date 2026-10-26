/**
 * Scheduling for the connected server's update status.
 *
 * Status is only interesting at a fast cadence while an update, restart, or
 * check is underway. An idle client refreshes rarely and otherwise relies on
 * events (reconnects, returning to the foreground, explicit checks). Idle
 * polling stops while the app is backgrounded or the device is offline, and a
 * single refresh runs when it returns. An operation in flight is not optional
 * and keeps its cadence.
 */
export const ACTIVE_STATUS_POLL_MS = 3_000
export const IDLE_STATUS_POLL_MS = 10 * 60_000
/** Keep the fast cadence briefly after a command, before the server reports it. */
export const COMMAND_BURST_MS = 15_000

export interface PollConditions {
  active: boolean
  foreground: boolean
  online: boolean
}

/** Milliseconds until the next status refresh, or null while polling is suspended. */
export function statusPollDelay({ active, foreground, online }: PollConditions): number | null {
  if (active) return ACTIVE_STATUS_POLL_MS
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
  refresh: () => Promise<void>
  isActive: () => boolean
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

  const suspended = () => (!foreground || !online) && !options.isActive()
  function clear() {
    if (timer !== undefined) timers.clear(timer)
    timer = undefined
  }
  function reschedule() {
    clear()
    if (stopped || running) return
    const delay = statusPollDelay({ active: options.isActive(), foreground, online })
    if (delay !== null) timer = timers.set(wake, delay)
  }
  function wake() {
    if (stopped) return
    if (suspended()) { clear(); return }
    if (running) { again = true; return }
    clear()
    running = true
    void options.refresh().catch(() => { /* Status is best-effort. */ }).finally(() => {
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
