import type { InjectionKey } from 'vue'

/**
 * Keep from this on a result tile: Tool View provides it so the tiles in its strip can
 * offer it for images made from slots, without every grid in between passing it along.
 * Tiles elsewhere (the queue panel) find nothing and show nothing.
 */
export interface ResultKeep {
  /** Whether this job's image can offer Keep from this now. */
  can: (job: { parameters?: string | Record<string, unknown> | null }) => boolean
  /** Open its checklist, anchored to `at`. */
  open: (job: { parameters?: string | Record<string, unknown> | null }, at: Element) => void
}

export const RESULT_KEEP: InjectionKey<ResultKeep> = Symbol('resultKeep')
