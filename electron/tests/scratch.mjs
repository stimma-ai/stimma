import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const scratchDirs = new Set()
let handlersInstalled = false

/**
 * A tree that a just-exited app may still be writing to (an AppImage's
 * squashfs mount, a backend flushing logs) can lose the race with a single
 * recursive rm and fail with ENOTEMPTY after the test itself has passed.
 * Retry rather than fail a green run on its own cleanup.
 */
function removeTree(dir) {
  fs.rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 250 })
}

function cacheHome() {
  return process.env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache')
}

function cleanupScratchDirs() {
  for (const dir of scratchDirs) {
    removeTree(dir)
    scratchDirs.delete(dir)
  }
}

function installCleanupHandlers() {
  if (handlersInstalled) return
  handlersInstalled = true
  process.once('exit', cleanupScratchDirs)
  for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.once(signal, () => {
      cleanupScratchDirs()
      process.kill(process.pid, signal)
    })
  }
}

/**
 * Make build/test scratch space on the disk-backed cache filesystem.
 *
 * The returned cleanup is idempotent. Exit and termination-signal handlers
 * are also installed so callers do not strand large trees on failure.
 */
export function makeScratchDir(prefix) {
  const root = path.join(cacheHome(), 'stimma', 'scratch')
  fs.mkdirSync(root, { recursive: true })
  const dir = fs.mkdtempSync(path.join(root, prefix))
  scratchDirs.add(dir)
  installCleanupHandlers()
  return {
    dir,
    cleanup() {
      removeTree(dir)
      scratchDirs.delete(dir)
    },
    preserve() {
      scratchDirs.delete(dir)
    },
  }
}
