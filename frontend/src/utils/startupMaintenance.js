/**
 * Optional background maintenance (marketplace sync, update checks, account
 * refresh, release notes) is not needed to use the app. It waits until the
 * shell is usable and then runs one task at a time, so on a constrained
 * connection it does not compete with the screen the person is looking at or
 * open a burst of simultaneous requests.
 *
 * Every scheduled task still runs: if startup never reports a usable shell
 * (an error path), the queue starts on its own after a bounded wait.
 */

export function createMaintenanceQueue({
  settleMs = 1500, // after the shell is usable, before the first task
  gapMs = 250, // between tasks
  taskBudgetMs = 15_000, // a slow task stops holding the queue after this
  startAnywayMs = 20_000, // start even if the shell never reports usable
  timers = globalThis,
} = {}) {
  const queue = []
  const queued = new Map() // key -> pending job promise
  let usable = false
  let running = false
  let settled = false
  let fallback = null

  const sleep = ms => new Promise(resolve => timers.setTimeout(resolve, ms))

  async function pump() {
    if (running || !usable) return
    running = true
    try {
      if (!settled) {
        await sleep(settleMs)
        settled = true
      }
      while (queue.length) {
        const job = queue.shift()
        queued.delete(job.key)
        let budget
        const finished = Promise.resolve().then(job.task).then(job.resolve, job.reject)
        await Promise.race([finished, new Promise(resolve => { budget = timers.setTimeout(resolve, taskBudgetMs) })])
        timers.clearTimeout(budget)
        if (queue.length) await sleep(gapMs)
      }
    } finally {
      running = false
    }
    if (queue.length) void pump()
  }

  function markUsable() {
    if (fallback) timers.clearTimeout(fallback)
    fallback = null
    if (usable) return
    usable = true
    void pump()
  }

  /**
   * Run `task` after startup. A task with the same key that has not started
   * yet is not queued twice; the caller shares its result.
   */
  function schedule(key, task) {
    if (queued.has(key)) return queued.get(key)
    let resolve, reject
    const promise = new Promise((res, rej) => { resolve = res; reject = rej })
    // Callers fire and forget; a failed task must not surface as unhandled.
    promise.catch(() => {})
    queue.push({ key, task, resolve, reject })
    queued.set(key, promise)
    if (!usable && !fallback) fallback = timers.setTimeout(markUsable, startAnywayMs)
    void pump()
    return promise
  }

  return { schedule, markUsable, isUsable: () => usable }
}

const shared = createMaintenanceQueue()

export const scheduleMaintenance = shared.schedule
export const markStartupUsable = shared.markUsable
