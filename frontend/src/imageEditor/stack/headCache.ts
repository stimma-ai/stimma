/**
 * The persisted fast-open projection of a stack document.
 *
 * The composition remains authoritative. These files only let a cold editor show
 * the exact last rendered head without replaying expensive pixel effects.
 * Hash mismatch means cache miss; no invalidation bookkeeping is needed.
 */

import type { StackDocument } from './types.ts'
import { stackHashes } from './stackHashes.ts'

export function headCacheHash(document: StackDocument): string {
  return stackHashes(document).head
}

export function headCacheImageRef(document: StackDocument): string {
  return `cache/head-${headCacheHash(document)}.png`
}
