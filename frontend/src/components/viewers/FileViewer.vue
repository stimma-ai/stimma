<template>
  <div class="flex flex-col h-full min-h-0 min-w-0 text-content" @click.stop>
    <Teleport :to="controlsTarget || 'body'" :disabled="!controlsTarget">
    <div v-if="isText" class="flex items-center gap-2 px-3 py-1 shrink-0">
      <Button variant="ghost" size="sm" :disabled="loading || !!error" @click="copy">{{ copied ? 'Copied' : 'Copy' }}</Button>
      <Button v-if="kind !== 'text'" variant="ghost" size="sm" @click="raw = !raw">{{ raw ? 'Preview' : kind === 'markdown' ? 'Source' : 'Raw' }}</Button>
      <span v-if="kind === 'table' && rows.length" class="font-mono text-xs text-content-muted">{{ rows.length - 1 }} rows</span>
    </div>
    </Teleport>
    <p v-if="error" class="p-4 text-sm text-content-muted">{{ error }} <a :href="url" download class="text-accent">Download</a></p>
    <p v-else-if="loading" class="p-4 text-content-muted text-sm">Loading…</p>
    <AppImage v-else-if="kind === 'image'" :src="url" :alt="name" container-class="w-full h-full" img-class="object-contain" />
    <video v-else-if="kind === 'video'" :src="url" controls playsinline class="w-full h-full object-contain" />
    <audio v-else-if="kind === 'audio'" :src="url" controls class="w-full m-auto" />
    <WorkspaceZipViewer v-else-if="kind === 'zip' && workspaceFile && chatId != null" :file="workspaceFile" :chat-id="chatId" @attach="$emit('attach', $event)" @save="$emit('save', $event)" />
    <ReadOnlyCode v-else-if="isText && (raw || kind === 'text')" :text="text" :name="name" class="flex-1" />
    <MarkdownViewer v-else-if="kind === 'markdown' && mediaId" :media-id="mediaId" />
    <div v-else-if="kind === 'markdown'" class="overflow-auto p-4 prose prose-sm max-w-none text-content" v-html="markdown" />
    <div v-else-if="kind === 'json'" class="overflow-auto p-3 font-mono text-xs"><JsonTree :value="jsonValue" /></div>
    <div v-else-if="kind === 'table'" ref="tableHost" class="overflow-auto flex-1 min-h-0" @scroll="scrollTop = tableHost?.scrollTop || 0">
      <table class="text-xs w-full border-collapse font-mono">
        <thead class="sticky top-0 bg-surface z-10"><tr><th v-for="(cell, i) in rows[0]" :key="i" class="px-3 py-2 text-left font-medium whitespace-nowrap">{{ cell }}</th></tr></thead>
        <tbody>
          <tr v-if="start"><td :colspan="rows[0]?.length" :style="{ height: `${start * 32}px` }" /></tr>
          <tr v-for="(row, ri) in windowRows" :key="start + ri" class="h-8 hover:bg-overlay-subtle"><td v-for="(cell, ci) in row" :key="ci" class="px-3 whitespace-nowrap max-w-80 truncate" :class="cell.trim() && Number.isFinite(Number(cell)) ? 'text-right tabular-nums' : 'text-left'">{{ cell }}</td></tr>
          <tr><td :colspan="rows[0]?.length" :style="{ height: `${Math.max(0, rows.length - 1 - start - windowRows.length) * 32}px` }" /></tr>
        </tbody>
      </table>
    </div>
    <div v-else class="m-auto p-6 text-center space-y-3">
      <div class="text-sm">{{ name }}</div><div class="font-mono text-xs text-content-muted">{{ fileSize(size) }} · {{ mime || 'Unknown file type' }}</div>
      <a :href="url" download class="inline-block p-2 text-accent text-sm">Download</a>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { AppImage } from '../media'
import Button from '../ui/Button.vue'
import ReadOnlyCode from './ReadOnlyCode.vue'
import JsonTree from './JsonTree.vue'
import MarkdownViewer from './MarkdownViewer.vue'
import WorkspaceZipViewer from './WorkspaceZipViewer.vue'
import { renderSafeMarkdown } from '../../utils/sanitizeHtml'
import { fileKind, fileSize, parseDelimited, type WorkspaceFile } from '../../utils/fileRefs'
const props = defineProps<{ url: string; name: string; mime?: string; controlsTarget?: HTMLElement | null; size?: number; mediaId?: number; workspaceFile?: WorkspaceFile; chatId?: number | string }>()
defineEmits<{ attach: [file: WorkspaceFile]; save: [file: WorkspaceFile] }>()
const text = ref(''), loading = ref(false), error = ref(''), raw = ref(false), copied = ref(false)
const tableHost = ref<HTMLElement | null>(null), scrollTop = ref(0)
const kind = computed(() => fileKind(props.name, props.mime))
const isText = computed(() => ['markdown', 'table', 'json', 'text'].includes(kind.value))
const rows = computed(() => kind.value === 'table' ? parseDelimited(text.value, props.name.endsWith('.tsv') ? '\t' : ',') : [])
const start = computed(() => Math.max(0, Math.floor(scrollTop.value / 32) - 5))
const windowRows = computed(() => rows.value.slice(1 + start.value, 1 + start.value + 100))
const jsonValue = computed(() => { try { return JSON.parse(text.value) } catch { return text.value } })
const markdown = computed(() => {
  const document = new DOMParser().parseFromString(renderSafeMarkdown(text.value), 'text/html')
  for (const image of document.querySelectorAll('img')) {
    const src = image.getAttribute('src') || ''
    if (!src || /^(?:[a-z]+:|[/][/]|[/])/i.test(src)) continue
    const url = new URL(props.url, window.location.href)
    const field = url.searchParams.has('entry') ? 'entry' : 'path'
    const current = url.searchParams.get(field)
    if (!current) continue
    const relative = new URL(src, 'https://workspace.invalid/' + current).pathname.slice(1)
    url.searchParams.set(field, decodeURIComponent(relative))
    image.setAttribute('src', url.toString())
  }
  return document.body.innerHTML
})
async function copy() { try { await navigator.clipboard.writeText(text.value); copied.value = true } catch { error.value = 'Unable to copy text' } }
watch(() => props.url, async (url, _, cleanup) => {
  const controller = new AbortController(); cleanup(() => controller.abort())
  text.value = ''; raw.value = false; copied.value = false; error.value = ''; scrollTop.value = 0; loading.value = false
  if (!isText.value) return
  const limit = 8 * 1024 * 1024
  if ((props.size || 0) > limit) { error.value = 'This file is too large for a text preview.'; return }
  loading.value = true
  try {
    const response = await fetch(url, { signal: controller.signal, cache: 'no-store' })
    if (!response.ok) throw new Error(response.status === 404 ? 'File no longer in workspace.' : 'Unable to read file.')
    const reader = response.body!.getReader(), decoder = new TextDecoder()
    let bytes = 0, content = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      bytes += value.byteLength
      if (bytes > limit) { await reader.cancel(); throw new Error('This file is too large for a text preview.') }
      content += decoder.decode(value, { stream: true })
    }
    if (!controller.signal.aborted) text.value = content + decoder.decode()
  } catch (e: any) { if (!controller.signal.aborted) error.value = e.message || 'Unable to preview file.' }
  finally { if (!controller.signal.aborted) loading.value = false }
}, { immediate: true })
</script>
