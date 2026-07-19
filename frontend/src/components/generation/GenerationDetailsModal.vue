<template>
  <Modal
    :show="show"
    size="custom"
    custom-class="max-h-[88vh] w-full max-w-5xl flex flex-col overflow-hidden"
    :close-on-esc="false"
    @close="$emit('close')"
  >
    <template #header>
      <div class="flex items-start gap-4">
            <div
              class="mt-0.5 flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg text-white"
              :class="headerIconBgClass"
            >
              <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" :d="headerIconPath" />
              </svg>
            </div>

            <div class="min-w-0 flex-1">
              <div class="text-[16px] font-semibold text-content">{{ title }}</div>
              <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-content-muted">
                <span v-if="toolTitle" class="font-medium text-content-secondary">{{ toolTitle }}</span>
                <span
                  v-if="providerLabel"
                  :class="providerIsStimmaCloud ? 'stimma-cloud-text font-medium' : ''"
                >{{ providerLabel }}</span>
                <span v-if="durationLabel">{{ durationLabel }}</span>
                <span v-if="statusText" class="inline-flex items-center gap-1">
                  <span class="h-2 w-2 rounded-full" :class="statusDotClass" />
                  <span>{{ statusText }}</span>
                </span>
              </div>
              <div
                v-if="stepCount > 1"
                class="mt-3 inline-flex items-center gap-1 rounded-full border border-edge-subtle bg-overlay-subtle px-1.5 py-1"
              >
                <button
                  type="button"
                  class="flex h-7 w-7 items-center justify-center rounded-full text-content-tertiary transition-colors hover:bg-overlay-hover hover:text-content disabled:cursor-default disabled:opacity-35"
                  :disabled="stepIndex <= 0"
                  title="Previous step"
                  @click="$emit('prev-step')"
                >
                  <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="m15 19-7-7 7-7" />
                  </svg>
                </button>
                <span class="min-w-[84px] text-center text-[11px] font-medium text-content-secondary">
                  Step {{ stepIndex + 1 }} / {{ stepCount }}
                </span>
                <button
                  type="button"
                  class="flex h-7 w-7 items-center justify-center rounded-full text-content-tertiary transition-colors hover:bg-overlay-hover hover:text-content disabled:cursor-default disabled:opacity-35"
                  :disabled="stepIndex >= stepCount - 1"
                  title="Next step"
                  @click="$emit('next-step')"
                >
                  <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="m9 5 7 7-7 7" />
                  </svg>
                </button>
              </div>
            </div>

            <div class="flex items-center gap-2">
              <button
                v-if="canRerun"
                type="button"
                class="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-edge-subtle bg-overlay-subtle text-content-secondary transition-colors hover:bg-overlay-hover hover:text-content"
                title="Re-run"
                @click="$emit('rerun')"
              >
                <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                </svg>
              </button>
              <button
                type="button"
                class="rounded-lg p-2 text-content-tertiary transition-colors hover:bg-overlay-subtle hover:text-content"
                title="Close"
                @click="$emit('close')"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-5 w-5">
                  <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                </svg>
              </button>
            </div>
      </div>
    </template>

    <div class="flex-1 overflow-y-auto px-5 py-4">
            <div class="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
              <section class="space-y-3">
                <slot name="preview">
                  <!-- Media on matte, radius-media, no chrome borders (§3.3 hero rules) -->
                  <div class="overflow-hidden rounded-media bg-matte">
                    <div
                      v-if="previewMediaIds && previewMediaIds.length"
                      class="grid gap-0.5 p-2"
                      :class="previewMediaIds.length === 1 ? 'grid-cols-1' : 'grid-cols-2'"
                    >
                      <div
                        v-for="mid in previewMediaIds"
                        :key="mid"
                        class="overflow-hidden rounded-media"
                      >
                        <MediaImage
                          :media-id="mid"
                          :thumbnail="true"
                          :thumbnail-size="512"
                          :contain="true"
                          container-class="aspect-square w-full"
                        />
                      </div>
                    </div>
                    <div
                      v-else
                      class="flex aspect-square items-center justify-center px-6 text-center"
                      :class="previewPlaceholder?.class || 'text-content-muted'"
                    >
                      <div>
                        <div class="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-overlay-subtle">
                          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" :d="previewPlaceholder?.iconPath || defaultPlaceholderIconPath" />
                          </svg>
                        </div>
                        <div class="text-[13px] font-medium">{{ previewPlaceholder?.title || 'No preview available' }}</div>
                        <div v-if="previewPlaceholder?.body" class="mt-1 text-[12px] text-content-muted">
                          {{ previewPlaceholder.body }}
                        </div>
                      </div>
                    </div>
                  </div>
                </slot>
              </section>

              <section class="space-y-4">
                <!-- Summary: micro-label + KeyValueList facts — no card, no
                     field tiles (read-only facts never look like inputs). -->
                <div>
                  <div class="text-xs font-semibold text-content-secondary mb-1">Summary</div>
                  <KeyValueList :rows="summaryRows" />
                </div>

                <div>
                  <div class="text-xs font-semibold text-content-secondary mb-1">Inputs</div>
                  <div v-if="loadingInputs" class="text-[12px] italic text-content-muted py-1.5">Loading inputs…</div>
                  <div
                    v-else-if="(prominentInputs?.length ?? 0) === 0 && (compactInputs?.length ?? 0) === 0"
                    class="text-[12px] text-content-muted py-1.5"
                  >
                    No recorded inputs for this generation.
                  </div>
                  <template v-else>
                    <!-- Prose inputs (prompt…): quiet block, whitespace-separated -->
                    <div
                      v-for="entry in (prominentInputs || [])"
                      :key="entry.key"
                      class="py-1.5"
                    >
                      <div class="flex items-center justify-between mb-1">
                        <span class="text-xs text-content-tertiary">{{ entry.label }}</span>
                        <button
                          @click="copyValue(entry.value)"
                          class="bg-transparent border-none text-content-tertiary cursor-pointer p-0.5 rounded hover:bg-overlay-subtle hover:text-content"
                          title="Copy to clipboard"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3">
                            <path d="M7 3.5A1.5 1.5 0 018.5 2h3.879a1.5 1.5 0 011.06.44l3.122 3.12A1.5 1.5 0 0117 6.622V12.5a1.5 1.5 0 01-1.5 1.5h-1v-3.379a3 3 0 00-.879-2.121L10.5 5.379A3 3 0 008.379 4.5H7v-1z" />
                            <path d="M4.5 6A1.5 1.5 0 003 7.5v9A1.5 1.5 0 004.5 18h7a1.5 1.5 0 001.5-1.5v-5.879a1.5 1.5 0 00-.44-1.06L9.44 6.439A1.5 1.5 0 008.378 6H4.5z" />
                          </svg>
                        </button>
                      </div>
                      <p class="m-0 whitespace-pre-wrap break-words text-content-secondary text-xs leading-relaxed select-text">{{ entry.value }}</p>
                    </div>

                    <KeyValueList v-if="(compactInputs?.length ?? 0) > 0" :rows="compactInputRows" />
                  </template>
                </div>

                <div
                  v-if="parsedError"
                  class="rounded-lg border border-red-500/30 bg-red-500/5"
                >
                  <div class="border-b border-red-500/20 px-4 py-3">
                    <div class="text-[13px] font-semibold text-red-400">{{ parsedError.title }}</div>
                    <p class="mt-1 whitespace-pre-wrap break-words text-[12px] leading-relaxed text-content-secondary">
                      {{ parsedError.message }}
                    </p>
                  </div>
                  <div class="px-4 py-3 flex flex-wrap items-center gap-2">
                    <button
                      v-if="canFixWithAgent"
                      type="button"
                      class="text-[12px] px-2.5 py-1 rounded-md bg-accent hover:bg-accent/90 text-white"
                      @click="$emit('fix-with-agent')"
                    >Ask the agent for help</button>
                    <button
                      v-if="canRerun"
                      type="button"
                      class="text-[12px] px-2.5 py-1 rounded bg-overlay-subtle border border-edge-subtle text-content-muted hover:text-content hover:bg-overlay-hover"
                      @click="$emit('rerun')"
                    >Retry</button>
                    <button
                      type="button"
                      class="text-[12px] px-2.5 py-1 rounded bg-overlay-subtle border border-edge-subtle text-content-muted hover:text-content hover:bg-overlay-hover"
                      @click="copyValue(parsedError.raw)"
                    >Copy error</button>
                  </div>
                </div>

                <div
                  v-if="devModeRef && errorDetails"
                  class="rounded-lg border border-amber-500/40 bg-overlay-light"
                >
                  <div class="flex items-center gap-2 border-b border-amber-500/30 px-4 py-2.5">
                    <span class="text-[10px] font-medium text-amber-600 dark:text-amber-400 bg-amber-500/15 px-1.5 py-0.5 rounded-sm">Dev</span>
                    <span class="text-[12px] text-content-muted">raw step error</span>
                  </div>
                  <div class="px-4 py-3">
                    <pre class="max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-overlay-subtle px-3 py-2 font-mono text-[11px] text-content-secondary custom-scrollbar select-text">{{ errorDetails }}</pre>
                  </div>
                </div>

                <div
                  v-if="devModeRef && rawJson"
                  class="rounded-lg border border-edge-subtle bg-base"
                >
                  <div class="flex items-center justify-between border-b border-edge-subtle px-4 py-3">
                    <button
                      type="button"
                      class="group flex flex-1 items-center gap-2 text-left text-[13px] font-semibold text-content"
                      :aria-expanded="rawJsonExpanded"
                      @click="rawJsonExpanded = !rawJsonExpanded"
                    >
                      <svg
                        class="h-3.5 w-3.5 text-content-tertiary transition-transform group-hover:text-content"
                        :class="rawJsonExpanded ? 'rotate-90' : ''"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke-width="2.25"
                        stroke="currentColor"
                      >
                        <path stroke-linecap="round" stroke-linejoin="round" d="m9 5 7 7-7 7" />
                      </svg>
                      <span>Raw JSON</span>
                    </button>
                    <button
                      v-if="rawJsonExpanded"
                      type="button"
                      @click.stop="copyValue(rawJson)"
                      class="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-medium text-content-tertiary transition-colors hover:bg-overlay-subtle hover:text-content"
                      title="Copy JSON"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3">
                        <path d="M7 3.5A1.5 1.5 0 018.5 2h3.879a1.5 1.5 0 011.06.44l3.122 3.12A1.5 1.5 0 0117 6.622V12.5a1.5 1.5 0 01-1.5 1.5h-1v-3.379a3 3 0 00-.879-2.121L10.5 5.379A3 3 0 008.379 4.5H7v-1z" />
                        <path d="M4.5 6A1.5 1.5 0 003 7.5v9A1.5 1.5 0 004.5 18h7a1.5 1.5 0 001.5-1.5v-5.879a1.5 1.5 0 00-.44-1.06L9.44 6.439A1.5 1.5 0 008.378 6H4.5z" />
                      </svg>
                      {{ rawJsonCopied ? 'Copied' : 'Copy' }}
                    </button>
                  </div>
                  <div v-if="rawJsonExpanded" class="px-4 py-3">
                    <pre class="max-h-72 overflow-auto whitespace-pre rounded-lg bg-overlay-subtle px-3 py-2 font-mono text-[11px] text-content-secondary custom-scrollbar select-text">{{ rawJson }}</pre>
                  </div>
                </div>

              </section>
            </div>
    </div>
  </Modal>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { devModeRef } from '../../appConfig'
import { copyToClipboard } from '../../utils/clipboard'
import { parseFlowError } from '../../utils/flowErrors'
import MediaImage from '../media/MediaImage.vue'
import KeyValueList, { type KeyValueRow } from '../ui/KeyValueList.vue'
import Modal from '../ui/Modal.vue'

export interface InputEntry {
  key: string
  label: string
  value: string
  fullWidth?: boolean
}

interface Props {
  show: boolean
  title?: string
  headerIconPath: string
  headerIconBgClass: string
  toolTitle?: string | null
  providerLabel?: string | null
  providerIsStimmaCloud?: boolean
  durationLabel?: string | null
  statusText?: string | null
  statusDotClass?: string | null
  statusTextClass?: string | null
  stepIndex?: number
  stepCount?: number
  canRerun?: boolean
  previewMediaIds?: number[]
  previewPlaceholder?: {
    title: string
    body?: string
    iconPath: string
    class: string
  } | null
  loadingInputs?: boolean
  prominentInputs?: InputEntry[]
  compactInputs?: InputEntry[]
  errorDetails?: string
  rawJson?: string | null
  canFixWithAgent?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  title: 'Generation details',
  stepIndex: 0,
  stepCount: 1,
  canRerun: false,
  loadingInputs: false,
  previewMediaIds: () => [],
  prominentInputs: () => [],
  compactInputs: () => [],
  previewPlaceholder: null,
  toolTitle: null,
  providerLabel: null,
  providerIsStimmaCloud: false,
  durationLabel: null,
  statusText: null,
  statusDotClass: null,
  statusTextClass: null,
  errorDetails: '',
  rawJson: null,
  canFixWithAgent: false,
})

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'prev-step'): void
  (e: 'next-step'): void
  (e: 'rerun'): void
  (e: 'fix-with-agent'): void
}>()

const defaultPlaceholderIconPath = 'M3.375 3.375h17.25v17.25H3.375V3.375Zm3.375 11.25 3-3 2.25 2.25 4.5-4.5 2.25 2.25'

const summaryRows = computed<KeyValueRow[]>(() => {
  const rows: KeyValueRow[] = [
    { label: 'Status', value: props.statusText || 'Unknown', mono: false, valueClass: props.statusTextClass || undefined },
  ]
  if (props.durationLabel) rows.push({ label: 'Generation time', value: props.durationLabel })
  rows.push({ label: 'Tool', value: props.toolTitle || 'Not recorded', mono: false })
  if (props.providerLabel) {
    rows.push({
      label: 'Provider',
      value: props.providerLabel,
      mono: false,
      valueClass: props.providerIsStimmaCloud ? 'stimma-cloud-text font-medium' : undefined,
    })
  }
  return rows
})

const compactInputRows = computed<KeyValueRow[]>(() => (props.compactInputs || []).map(entry => ({
  label: entry.label,
  value: entry.value,
  mono: !entry.fullWidth,
  truncate: false,
})))

const rawJsonCopied = ref(false)
const rawJsonExpanded = ref(false)
const parsedError = computed(() => parseFlowError(props.errorDetails))
let rawJsonCopiedTimer: ReturnType<typeof setTimeout> | null = null

watch(() => props.show, (visible) => {
  if (!visible) rawJsonExpanded.value = false
})

function handleKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !props.show) return
  event.preventDefault()
  event.stopPropagation()
  event.stopImmediatePropagation()
  emit('close')
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown, true)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown, true)
})

async function copyValue(value: string) {
  if (!value) return
  try {
    const ok = await copyToClipboard(value)
    if (ok && value === props.rawJson) {
      rawJsonCopied.value = true
      if (rawJsonCopiedTimer) clearTimeout(rawJsonCopiedTimer)
      rawJsonCopiedTimer = setTimeout(() => { rawJsonCopied.value = false }, 1500)
    }
  } catch {
    // Best effort.
  }
}
</script>
