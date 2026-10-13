<template>
  <div class="pv-root" :data-theme="theme" data-testid="provenance-view">
    <section v-if="view.steps.length">
      <h4 class="m-0 mb-3 text-xs font-semibold text-content-secondary">{{ title }}</h4>
      <ProvenanceSteps :steps="view.steps" />
    </section>
    <ProvenanceFileFacts :class="view.steps.length ? 'mt-6' : ''" :rows="view.file" />
    <div
      v-if="toast"
      class="fixed bottom-4 left-1/2 -translate-x-1/2 z-toast px-3 py-1.5 rounded-md bg-surface-raised text-content text-xs shadow-lg pointer-events-none"
      role="status"
    >{{ toast }}</div>
  </div>
</template>

<script setup lang="ts">
/**
 * The share page's "How it was made": the app's provenance components fed a
 * published sidecar, with the public host — thumbnails are the sidecar's own
 * data URIs, prompts copy, nothing navigates.
 */
import { computed, h, onBeforeUnmount, ref, type FunctionalComponent } from 'vue'
import ProvenanceSteps from '../ProvenanceSteps.vue'
import ProvenanceFileFacts from '../ProvenanceFileFacts.vue'
import { provideProvenanceHost } from '../host.ts'
import { publishedThumbnails, viewFromPublished } from '../fromPublished.ts'

const props = withDefaults(defineProps<{
  sidecar: unknown
  theme?: 'dark' | 'light'
  title?: string
}>(), {
  theme: 'dark',
  title: 'How it was made',
})

const view = computed(() => viewFromPublished(props.sidecar))
const thumbnails = computed(() => publishedThumbnails(props.sidecar))

const Thumb: FunctionalComponent<{ thumbRef: unknown; fallbackRef: unknown; alt: string; size: number }> = (p) => {
  const map = thumbnails.value
  const src = (typeof p.thumbRef === 'string' && map[p.thumbRef])
    || (typeof p.fallbackRef === 'string' && map[p.fallbackRef])
  return src
    ? h('img', { src, alt: p.alt, draggable: false, decoding: 'async', class: 'w-full h-full object-contain' })
    : null
}
Thumb.props = ['thumbRef', 'fallbackRef', 'alt', 'size']

const toast = ref('')
let toastTimer: ReturnType<typeof setTimeout> | null = null
function showToast(text: string) {
  toast.value = text
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 1600)
}
onBeforeUnmount(() => { if (toastTimer) clearTimeout(toastTimer) })

async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // Insecure contexts and older browsers: the selection fallback.
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    let ok = false
    try { ok = document.execCommand('copy') } catch { ok = false }
    area.remove()
    return ok
  }
}

provideProvenanceHost({
  thumbnail: Thumb,
  async copy(text) {
    showToast(await writeClipboard(text) ? 'Copied to clipboard' : 'Could not copy to clipboard')
  },
})
</script>
