/**
 * What the "how it was made" components need from wherever they render.
 *
 * The components in this directory are pure presentation: no store, router,
 * HTTP client, profile, or library-media component. Everything that differs
 * between the app and the public share page comes through one host object,
 * provided once above the tree:
 *
 *   app (components/media/ProvenanceAppHost.vue): thumbnails are library
 *     media (drag, context menu), inputs open and compare, steps get their
 *     action menu, copy toasts.
 *   share page (standalone/): thumbnails are data URIs from the sidecar,
 *     copy works, nothing navigates.
 *
 * Everything optional is a capability: absent means the control isn't drawn.
 */

import { inject, provide, type Component, type InjectionKey } from 'vue'
import type { ViewInput } from './types.ts'

export interface InputAction {
  label: string
  run: () => void
}

export interface ProvenanceHost {
  /**
   * Draws a thumbnail. Props: `thumbRef` (the opaque `thumb`/`preview`
   * reference), `fallbackRef` (drawn when `thumbRef` can't be, e.g. a preview
   * still resolving), `alt`, `size` (CSS px of the tile).
   */
  thumbnail: Component
  /** Hover label around a control. Props: `text`. Defaults to a `title`. */
  tooltip?: Component
  /** Copy text and tell the user it happened. */
  copy?: (text: string) => void | Promise<void>
  /** Open an input (a library item, a reference file, a preview). */
  openInput?: (input: ViewInput) => void
  canOpenInput?: (input: ViewInput) => boolean
  /** Links under an input tile (View, Compare, Processed | Original). */
  inputActions?: (input: ViewInput) => InputAction[]
  /** Show an import's raw external metadata. */
  openRawMetadata?: (text: string) => void
}

const HOST: InjectionKey<ProvenanceHost> = Symbol('stimma-provenance-host')

export function provideProvenanceHost(host: ProvenanceHost): void {
  provide(HOST, host)
}

export function useProvenanceHost(): ProvenanceHost {
  const host = inject(HOST, null)
  if (!host) throw new Error('provenance components need provideProvenanceHost() above them')
  return host
}
