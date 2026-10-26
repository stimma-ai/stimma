/**
 * Run a long-lived loop in exactly one window, via a Web Lock held for as long
 * as the loop runs. If the owning window closes, a waiting window takes over.
 *
 * `run()` performs the loop's first pass and resolves true to keep holding the
 * lock (the loop continues on its own timers), or false to release it.
 *
 * The returned promise is about this window's startup work, not ownership: it
 * resolves when `run()`'s first pass settles, or at once if another window
 * owns the loop (this one then waits to take over without holding anything
 * up). Startup maintenance can therefore wait for real work to finish.
 */
export function startExclusiveLoop(locks, name, run) {
  if (!locks?.request) return Promise.resolve().then(run).then(() => undefined)
  return new Promise(resolve => {
    const hold = async lock => {
      if (!lock) {
        resolve()
        locks.request(name, hold).catch(() => {})
        return
      }
      let keep = false
      try {
        keep = await run()
      } finally {
        resolve()
      }
      if (keep) return new Promise(() => {})
    }
    locks.request(name, { ifAvailable: true }, hold).catch(() => resolve())
  })
}
