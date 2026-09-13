/**
 * Content hashing for the op stack.
 *
 * `hash(i+1) = H(hash(i), canonical(op(i)))`, so any edit invalidates exactly
 * the ops at and above it and everything below is a cache hit. Disabled ops
 * hash as identity, which is why toggling one off is instant, and reordering
 * swaps hash inputs the same way — there is no special dirty logic anywhere.
 *
 * Kept free of rendering imports so the parts that only need to REASON about a
 * stack (staleness, blast radius) do not drag in a canvas.
 */

import type { Op, StackDocument } from './types.ts'
import { pickedCandidate } from './types.ts'

/** FNV-1a over a string. Fast, stable, and only ever compared for equality. */
function hashString(input: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(16).padStart(8, '0')
}

/**
 * The part of an op that changes its output. Anything not in here must not
 * affect pixels — labels and selection state deliberately do not.
 */
export function canonicalOp(op: Op): string {
  if (!op.enabled) return 'identity'
  const anyOp = op as any
  const picked = pickedCandidate(op)
  return JSON.stringify([
    op.class,
    anyOp.exec,
    anyOp.params ?? null,
    anyOp.shapes_in_document ?? null,
    // Retouch is the one container with editable children. Child order is
    // render order, so it is deliberately part of the parent's pixel identity.
    anyOp.regions ?? null,
    anyOp.defaults ?? null,
    anyOp.mask_ref ?? null,
    // A generative op's composite mask composition; absent hashes as before.
    anyOp.mask_components ?? null,
    anyOp.raster_ref ?? null,
    anyOp.payload_to_document ?? null,
    // Bumped when a payload is rewritten under the same ref, so a stroke added
    // to an existing layer actually invalidates the composite above it.
    anyOp._revision ?? 0,
    anyOp.blend ?? null,
    picked
      ? [
          picked.file_hash,
          picked.patch_ref ?? null,
          picked.payload_to_document ?? null,
          picked.patch_origin ?? null,
        ]
      : null,
  ])
}

/** Input hashes for every op, plus the hash of the finished composite. */
export function stackHashes(doc: StackDocument): { inputs: string[]; head: string } {
  let hash = doc.base.file_hash
  const inputs: string[] = []
  for (const op of doc.edits) {
    inputs.push(hash)
    // Disabled steps are pixel identities, but they remain distinct replay
    // states. Collapsing them onto their input hash lets one hash mean both
    // "the immutable base" and "a later stack position". That alias is unsafe
    // for stage/head caching and, in the worst case, can publish an edited
    // projection under the base file hash.
    hash = hashString(hash + '|' + canonicalOp(op))
  }
  return { inputs, head: hash }
}
