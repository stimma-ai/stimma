/**
 * The share page's provenance panel, as a self-contained bundle
 * (`npm run build:provenance-view` → dist-provenance/).
 *
 *   window.StimmaProvenance.mount(el, { sidecar, theme: 'dark' | 'light' })
 *     → { unmount() }
 *
 * `sidecar` is the published history (GET /api/s/:code/history, v2 or v3).
 * Styles are scoped under `.stimma-pv`, so the host page's CSS and this
 * panel's don't touch each other.
 */
import { createApp } from 'vue'
import PublicRoot from './PublicRoot.vue'
import './provenance-view.css'

export interface MountOptions {
  sidecar: unknown
  theme?: 'dark' | 'light'
  /** Section heading above the steps. */
  title?: string
}

export function mount(el: Element, options: MountOptions): { unmount(): void } {
  const wrapper = document.createElement('div')
  wrapper.className = 'stimma-pv'
  el.appendChild(wrapper)
  const app = createApp(PublicRoot, {
    sidecar: options.sidecar,
    theme: options.theme === 'light' ? 'light' : 'dark',
    ...(options.title ? { title: options.title } : {}),
  })
  app.mount(wrapper)
  return {
    unmount() {
      app.unmount()
      wrapper.remove()
    },
  }
}
