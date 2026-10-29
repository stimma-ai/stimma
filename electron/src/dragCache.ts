/**
 * Temporary copies of remote media for native drag-out. The OS drop target
 * reads the file from disk, so a remote file has to land locally first.
 *
 * Copies are keyed by content so repeat drags reuse one file, and anything
 * not dragged for an hour is deleted. Without pruning, every drag left a
 * full-size copy behind in the OS temp directory forever.
 */

import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

export const DRAG_CACHE_MAX_AGE_MS = 60 * 60 * 1000
const ROOT_NAME = 'stimma-drag'
// Builds before this cache wrote one `stimma-drag-XXXXXX` mkdtemp directory
// per drag; sweep those up too.
const LEGACY_PREFIX = 'stimma-drag-'

export async function cacheDragFile(tempDir: string, filename: string, data: Uint8Array): Promise<string> {
  const name = path.basename(filename.replaceAll('\\', '/'))
  if (!name || name === '.' || name === '..') throw new Error('Invalid filename')
  // One directory per content+name preserves the filename the user sees on
  // drop and keeps two different files with the same name apart.
  const digest = crypto.createHash('sha256').update(name).update('\0').update(data).digest('hex').slice(0, 32)
  const directory = path.join(tempDir, ROOT_NAME, digest)
  const target = path.join(directory, name)
  const now = new Date()
  try {
    await fs.promises.utimes(directory, now, now)
    await fs.promises.access(target)
    return target
  } catch {
    // Not cached yet.
  }
  await fs.promises.mkdir(directory, { recursive: true })
  const partial = `${target}.${crypto.randomUUID()}.partial`
  try {
    await fs.promises.writeFile(partial, data)
    await fs.promises.rename(partial, target)
  } catch (error) {
    await fs.promises.rm(partial, { force: true })
    throw error
  }
  return target
}

export async function pruneDragCache(tempDir: string, now = Date.now()): Promise<void> {
  const cutoff = now - DRAG_CACHE_MAX_AGE_MS
  const stale = async (dir: string) => {
    try {
      return (await fs.promises.stat(dir)).mtimeMs < cutoff
    } catch {
      return false
    }
  }
  const root = path.join(tempDir, ROOT_NAME)
  const cached = await fs.promises.readdir(root).catch(() => [] as string[])
  const legacy = (await fs.promises.readdir(tempDir).catch(() => [] as string[]))
    .filter((entry) => entry.startsWith(LEGACY_PREFIX))
  for (const dir of [...cached.map((e) => path.join(root, e)), ...legacy.map((e) => path.join(tempDir, e))]) {
    if (await stale(dir)) await fs.promises.rm(dir, { recursive: true, force: true }).catch(() => {})
  }
}
