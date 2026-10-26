/**
 * An overall deadline for a finite read: request, wait and body together.
 * Not every transport bounds a stalled read (desktop and iOS proxies drop
 * their timers once upstream connects), so screens that must recover on
 * their own abort the read rather than wait on it forever.
 *
 * The default is generous for weak cellular: the reads it guards are small
 * JSON lists, which move in a few seconds even at 1 Mbps, so 45 s is only
 * ever hit by a read that has stopped making progress.
 */
let readDeadlineMs = 45_000

export function getReadDeadlineMs() {
  return readDeadlineMs
}

/** Tests shorten the deadline; the app keeps the default. */
export function setReadDeadlineMs(ms: number) {
  readDeadlineMs = ms
}

/**
 * Run `read` with an AbortSignal that fires after the deadline. `read` must
 * consume the response body before resolving so the deadline covers it.
 * The signal is also aborted whenever `read` settles, so any request it
 * started and left behind (say, a sibling of one that failed) is cancelled
 * rather than left running without a deadline.
 */
export async function withReadDeadline<T>(read: (signal: AbortSignal) => Promise<T>, ms = readDeadlineMs): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), ms)
  try {
    return await read(controller.signal)
  } finally {
    clearTimeout(timer)
    controller.abort()
  }
}
