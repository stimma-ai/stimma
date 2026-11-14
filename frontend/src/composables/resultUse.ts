import type { InjectionKey } from 'vue'

/**
 * Use (in your prompt) on a result tile: Tool View provides it so the tiles in its strip can
 * offer it for images made from slots, without every grid in between passing it along. Tiles
 * elsewhere (the queue panel) find nothing and show nothing.
 */
export interface ResultUse {
  /** Whether this job's image can offer Use now. */
  can: (job: { parameters?: string | Record<string, unknown> | null }) => boolean
  /** Open its list, hung from `at` (the image). */
  open: (job: { parameters?: string | Record<string, unknown> | null }, at: Element | DOMRect) => void
}

export const RESULT_USE: InjectionKey<ResultUse> = Symbol('resultUse')
