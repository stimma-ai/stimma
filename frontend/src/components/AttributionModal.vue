<template>
  <Modal :show="show" size="custom" custom-class="w-[760px] max-w-[calc(100vw-2rem)] flex flex-col max-h-[85vh] overflow-hidden" @close="$emit('close')">
    <template #header>
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-semibold text-content">Open Source Attribution</h3>
        <IconButton @click="$emit('close')">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
          </svg>
        </IconButton>
      </div>
    </template>

    <div v-if="loading" class="px-6 py-12 flex items-center justify-center gap-3 text-sm text-content-tertiary">
      <div class="w-4 h-4 border-2 border-content-muted border-t-accent rounded-full animate-spin"></div>
      Loading attribution…
    </div>

    <div v-else-if="error" class="px-6 py-10 text-center">
      <div class="text-sm text-content-secondary">Couldn't load the attribution document.</div>
      <div class="text-xs text-content-muted mt-1.5">Check your connection, or view it on GitHub instead.</div>
      <div class="mt-4 flex items-center justify-center gap-2">
        <Button variant="secondary" size="sm" @click="load">Try Again</Button>
        <Button size="sm" @click="openOnGitHub">View on GitHub</Button>
      </div>
    </div>

    <div v-else class="px-6 py-5 overflow-y-auto attribution-body text-sm text-content-secondary" v-html="rendered" @click="handleLinkClick"></div>
  </Modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import Modal from './ui/Modal.vue'
import IconButton from './ui/IconButton.vue'
import Button from './ui/Button.vue'
import { renderSafeMarkdown } from '../utils/sanitizeHtml'

// The document is intentionally NOT baked into builds: it's fetched from the
// repo's main branch so corrections reach users without an app update. Plain
// fetch, not axios — the global axios interceptors attach X-Profile-* headers
// that force a CORS preflight (same reasoning as useReleaseNotes.ts).
const ATTRIBUTION_RAW_URL = 'https://raw.githubusercontent.com/stimma-ai/stimma/main/ATTRIBUTION.md'
const ATTRIBUTION_GITHUB_URL = 'https://github.com/stimma-ai/stimma/blob/main/ATTRIBUTION.md'

const props = defineProps<{ show: boolean }>()
defineEmits<{ close: [] }>()

const loading = ref(false)
const error = ref(false)
const rendered = ref('')

async function load() {
  loading.value = true
  error.value = false
  try {
    const response = await fetch(ATTRIBUTION_RAW_URL)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const markdown = (await response.text()).trim()
    if (!markdown) throw new Error('empty document')
    // The modal header already titles the document; drop a leading H1.
    const body = markdown.replace(/^#\s+[^\n]*\n+/, '')
    rendered.value = renderSafeMarkdown(body, { breaks: false })
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

// Open document links in the system browser instead of navigating the webview
// (same pattern as ChatView's handleLinkClick).
function handleLinkClick(e: MouseEvent) {
  const anchor = (e.target as HTMLElement).closest('a[href]')
  if (!anchor) return
  const href = anchor.getAttribute('href')
  if (!href) return
  e.preventDefault()
  if (href.startsWith('#')) return
  // Relative links in the document (e.g. LICENSE) point at repo files.
  const url = /^https?:\/\//.test(href)
    ? href
    : `https://github.com/stimma-ai/stimma/blob/main/${href.replace(/^\.?\//, '')}`
  openExternal(url)
}

async function openExternal(url: string) {
  try {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(url)
  } catch {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}

function openOnGitHub() {
  openExternal(ATTRIBUTION_GITHUB_URL)
}

watch(
  () => props.show,
  (show) => {
    if (show && !rendered.value && !loading.value) load()
  },
)
</script>

<style scoped>
/* Not text-base: this app defines a color named `base`, which wins the
   utility-name collision and turns text-base into background-colored text. */
.attribution-body :deep(h2) {
  @apply text-content font-semibold text-[16px] mt-6 mb-2 first:mt-0;
}
.attribution-body :deep(h3) {
  @apply text-content font-medium text-sm mt-4 mb-1.5;
}
.attribution-body :deep(p) {
  @apply mb-2 leading-relaxed;
}
.attribution-body :deep(ul) {
  @apply list-disc pl-5 space-y-1 mb-3;
}
.attribution-body :deep(a) {
  @apply text-blue-400 hover:underline;
}
.attribution-body :deep(code) {
  @apply bg-overlay-subtle px-1 py-0.5 rounded text-[12px];
}
.attribution-body :deep(table) {
  @apply w-full text-xs my-3 border-collapse;
}
.attribution-body :deep(th) {
  @apply text-left text-content-secondary font-medium px-2 py-1.5 border-b border-edge;
}
.attribution-body :deep(td) {
  @apply px-2 py-1 border-b border-edge-subtle align-top;
}
</style>
