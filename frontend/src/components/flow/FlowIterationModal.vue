<template>
  <GenerationDetailsModal
    :show="!!iteration"
    :header-icon-path="headerIconPath"
    :header-icon-bg-class="headerIconBgClass"
    :tool-title="toolTitle"
    :provider-label="providerLabel"
    :provider-is-stimma-cloud="isStimmaCloud"
    :duration-label="durationLabel"
    :status-text="statusText"
    :status-dot-class="statusDotClass"
    :status-text-class="statusTextClass"
    :step-index="selectedStepIndex"
    :step-count="stepCount"
    :can-rerun="!!invalidateTargetKey"
    :preview-placeholder="previewPlaceholder"
    :loading-inputs="loadingTrace"
    :prominent-inputs="prominentInputEntries"
    :compact-inputs="compactInputEntries"
    :error-details="errorDetails"
    :raw-json="rawJson"
    :can-fix-with-agent="canFixWithAgent"
    @close="$emit('close')"
    @prev-step="goToStep(selectedStepIndex - 1)"
    @next-step="goToStep(selectedStepIndex + 1)"
    @rerun="invalidate"
    @fix-with-agent="onFixWithAgent"
  >
    <template #preview>
      <div class="overflow-hidden rounded-xl border border-edge-subtle bg-overlay-subtle/40">
        <div
          v-if="previewMediaIds.length"
          class="grid gap-2 p-3"
          :class="previewMediaIds.length === 1 ? 'grid-cols-1' : 'grid-cols-2'"
        >
          <div
            v-for="mid in previewMediaIds"
            :key="mid"
            class="overflow-hidden rounded-lg border border-edge-subtle bg-overlay-subtle"
          >
            <FlowMediaTile
              :media-id="mid"
              :media-ids="previewMediaIds"
              :index="previewMediaIds.indexOf(mid)"
              :thumbnail="true"
              :thumbnail-size="512"
              :contain="true"
              container-class="aspect-square w-full bg-overlay-subtle"
            />
          </div>
        </div>
        <div
          v-else
          class="flex aspect-square items-center justify-center px-6 text-center"
          :class="previewPlaceholder.class"
        >
          <div>
            <div class="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-black/5">
              <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" :d="previewPlaceholder.iconPath" />
              </svg>
            </div>
            <div class="text-[13px] font-medium">{{ previewPlaceholder.title }}</div>
            <div v-if="previewPlaceholder.body" class="mt-1 text-[12px] text-content-muted">
              {{ previewPlaceholder.body }}
            </div>
          </div>
        </div>
      </div>
    </template>
  </GenerationDetailsModal>
</template>

<script setup lang="ts">
import axios from 'axios'
import { computed, ref, watch } from 'vue'
import { getApiBase } from '../../apiConfig'
import type { GroupedIteration } from '../../composables/useFlowGrouping'
import type { FlowEquation } from '../../composables/useFlowsApi'
import { useProvidersApi } from '../../composables/useProvidersApi'
import {
  DEFAULT_TASK_TYPE_GRADIENT_CLASS,
  DEFAULT_TASK_TYPE_ICON_PATH,
  getTaskTypeGradientClass,
  getTaskTypeIconPath,
} from '../../utils/taskTypeIcons'
import { buildStpCallPayload, stringifyStpPayload } from '../../utils/stpPayload'
import { errorSummary } from '../../utils/flowErrors'
import { shouldShowEquationDuration } from '../../utils/equationDuration'
import { STIMMA_CLOUD_PROVIDER_ID } from '../../utils/stimmaCloud'
import GenerationDetailsModal, { type InputEntry } from '../generation/GenerationDetailsModal.vue'
import FlowMediaTile from './FlowMediaTile.vue'

interface Props {
  iteration: GroupedIteration | null
  flowId: number | string | null
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'invalidate-equation', key: string): void
  (e: 'fix-step-with-agent', equation: FlowEquation): void
}>()

const trace = ref<any | null>(null)
const loadingTrace = ref(false)
const selectedStepIndex = ref(0)

const { cachedTools, cachedProviders, fetchProvidersAndTools } = useProvidersApi()

const stepCount = computed(() => props.iteration?.equations.length || 0)

const focalEquation = computed<FlowEquation | null>(() => {
  const equations = props.iteration?.equations || []
  return equations[selectedStepIndex.value] || null
})

const invalidateTargetKey = computed<string | null>(() => {
  const primaryKey = props.iteration?.primary?.equation_key
  if (primaryKey) return primaryKey
  return props.iteration?.wrapperKey || null
})

const previewMediaIds = computed<number[]>(() => {
  const focalMedia = focalEquation.value?.result_media_ids || []
  if (focalMedia.length) return focalMedia.slice(0, 4)
  const primaryMedia = props.iteration?.primary?.result_media_ids || []
  return primaryMedia.slice(0, 4)
})

const resolvedTool = computed(() => {
  const tid = focalEquation.value?.tool_id
  if (!tid) return null
  return cachedTools.value.find((t) => t.full_tool_id === tid) || null
})

const providerId = computed(() => {
  const tid = focalEquation.value?.tool_id
  if (!tid) return null
  return tid.split(':')[0] || null
})

const providerLabel = computed(() => {
  if (resolvedTool.value?.provider_name) return resolvedTool.value.provider_name
  const pid = providerId.value
  if (!pid) return null
  return cachedProviders.value.find((p) => p.provider_id === pid)?.provider_name || pid
})

const isStimmaCloud = computed(() => providerId.value === STIMMA_CLOUD_PROVIDER_ID)

const toolTitle = computed(() => {
  const eq = focalEquation.value
  if (!eq) return ''
  if (resolvedTool.value?.name) return resolvedTool.value.name
  if (eq.display_name) return eq.display_name
  if (eq.equation_type === 'llm_call') return 'LLM'
  if (eq.equation_type === 'code') return 'Code'
  if (eq.tool_id) {
    const parts = eq.tool_id.split(':').filter(Boolean)
    if (parts.length >= 2) {
      return parts[1].split('-').map((w) => w ? w[0].toUpperCase() + w.slice(1) : w).join(' ')
    }
  }
  return 'Generation'
})

const headerIconBgClass = computed(() => {
  const eq = focalEquation.value
  if (!eq) return DEFAULT_TASK_TYPE_GRADIENT_CLASS
  if (eq.equation_type === 'tool_call') return getTaskTypeGradientClass(eq.task_type || '')
  if (eq.equation_type === 'llm_call') return 'bg-gradient-to-br from-blue-500/80 to-blue-700/80'
  if (eq.equation_type === 'code') return 'bg-gradient-to-br from-emerald-500/80 to-emerald-700/80'
  return DEFAULT_TASK_TYPE_GRADIENT_CLASS
})

const headerIconPath = computed(() => {
  const eq = focalEquation.value
  if (!eq) return DEFAULT_TASK_TYPE_ICON_PATH
  if (eq.equation_type === 'tool_call') return getTaskTypeIconPath(eq.task_type || '')
  if (eq.equation_type === 'llm_call') return 'M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z'
  if (eq.equation_type === 'code') return 'M17.25 6.75L22.5 12l-5.25 5.25M6.75 17.25L1.5 12l5.25-5.25M14.25 3.75L9.75 20.25'
  return DEFAULT_TASK_TYPE_ICON_PATH
})

const statusText = computed(() => statusTextFor(focalEquation.value?.status))
const statusDotClass = computed(() => dotClassFor(focalEquation.value?.status))
const statusTextClass = computed(() => statusClassFor(focalEquation.value?.status))

const durationLabel = computed(() => formatDuration(focalEquation.value))

const previewPlaceholder = computed(() => ({
  title: placeholderTitle(focalEquation.value?.status),
  body: placeholderBody(focalEquation.value?.status),
  iconPath: placeholderIconPath(focalEquation.value?.status),
  class: placeholderClass(focalEquation.value?.status),
}))

function placeholderTitle(status?: string | null): string {
  switch (status) {
    case 'failed': return 'No image was produced'
    case 'computing': return 'Generation is running'
    case 'awaiting_input': return 'Waiting for input'
    default: return 'No preview available'
  }
}

function placeholderBody(status?: string | null): string {
  if (status === 'failed') return errorSummary(errorDetails.value) || 'Open the error details below to see what went wrong.'
  return ''
}

function placeholderClass(status?: string | null): string {
  switch (status) {
    case 'failed': return 'bg-red-500/5 text-red-400'
    case 'computing': return 'bg-blue-500/5 text-blue-400'
    default: return 'bg-overlay-subtle/30 text-content-muted'
  }
}

function placeholderIconPath(status?: string | null): string {
  if (status === 'failed') return 'M12 9v3.75m0 3.75h.007v.008H12v-.008ZM10.34 3.94 1.82 18a1.875 1.875 0 0 0 1.603 2.813h17.154A1.875 1.875 0 0 0 22.18 18L13.66 3.94a1.875 1.875 0 0 0-3.32 0Z'
  if (status === 'computing') return 'M16.5 6.75V3.75m0 0h-3m3 0-3 3m-3 10.5v3m0 0h3m-3 0 3-3m-7.5-6h-3m0 0v-3m0 3 3-3m15 3h-3m0 0v3m0-3-3 3'
  return 'M3.375 3.375h17.25v17.25H3.375V3.375Zm3.375 11.25 3-3 2.25 2.25 4.5-4.5 2.25 2.25'
}

const inputEntries = computed<InputEntry[]>(() => {
  const eq = focalEquation.value
  const t = trace.value
  if (!eq) return []

  const longFields = new Set(['prompt', 'negative_prompt', 'system', 'instructions', 'source', 'static_content'])
  const entries: InputEntry[] = []

  const addObjectEntries = (obj: Record<string, any> | null | undefined) => {
    if (!obj || typeof obj !== 'object') return
    for (const [key, raw] of Object.entries(obj)) {
      if (raw === null || raw === undefined || raw === '') continue
      if (Array.isArray(raw) && raw.length === 0) continue
      if (
        typeof raw === 'object' &&
        !Array.isArray(raw) &&
        Object.keys(raw).length === 0
      ) continue
      const formatted = formatValue(raw)
      entries.push({
        key,
        label: formatLabel(key),
        value: formatted,
        fullWidth: longFields.has(key) || formatted.length > 60 || formatted.includes('\n'),
      })
    }
  }

  if (t?.equation_type === 'tool_call') {
    addObjectEntries(toolInputsFromTraceOrMedia.value)
  } else if (
    t?.equation_type === 'code'
    || t?.equation_type === 'create_image'
    || t?.equation_type === 'create_layout'
    || t?.equation_type === 'rasterize_layout'
  ) {
    addObjectEntries(t.inputs || null)
  } else if (t?.equation_type === 'llm_call') {
    if (t.prompt) {
      entries.push({ key: 'prompt', label: 'Prompt', value: formatValue(t.prompt), fullWidth: true })
    }
    if (t.system) {
      entries.push({ key: 'system', label: 'System', value: formatValue(t.system), fullWidth: true })
    }
  } else if (t?.definition && typeof t.definition === 'object') {
    addObjectEntries(t.definition.params || t.definition.inputs || t.definition)
  }

  const deduped = new Map<string, InputEntry>()
  for (const entry of entries) {
    if (!deduped.has(entry.key)) deduped.set(entry.key, entry)
  }
  return Array.from(deduped.values())
})

const PROMINENT_KEYS = new Set(['prompt', 'negative_prompt', 'system', 'instructions', 'source', 'static_content'])

const prominentInputEntries = computed(() =>
  inputEntries.value.filter((entry) => PROMINENT_KEYS.has(entry.key)),
)

const compactInputEntries = computed(() =>
  inputEntries.value.filter((entry) => !PROMINENT_KEYS.has(entry.key)),
)

const toolInputsFromMedia = ref<Record<string, any> | null>(null)

const toolInputsFromTraceOrMedia = computed<Record<string, any> | null>(() => {
  if (toolInputsFromMedia.value && Object.keys(toolInputsFromMedia.value).length) return toolInputsFromMedia.value
  const def = trace.value?.definition
  if (!def || typeof def !== 'object') return null
  if (def.params && typeof def.params === 'object') {
    const params = { ...def.params }
    if (def.n !== undefined && def.n !== 1) params.n = def.n
    return params
  }
  return def
})

const rawJson = computed<string | null>(() => {
  const eq = focalEquation.value
  const t = trace.value
  if (!eq || !t) return null
  if (t.equation_type === 'tool_call') {
    const def = t.definition || {}
    const toolId = def.tool_id || def.tool || eq.tool_id || null
    const merged = toolInputsFromTraceOrMedia.value || def.params || {}
    const n = typeof def.n === 'number' ? def.n : undefined
    return stringifyStpPayload(buildStpCallPayload(toolId, merged, { n }))
  }
  // Non-tool-call equations don't talk to an STP tool — fall back to the
  // trace object so developers can still inspect what the runtime returned.
  try {
    return JSON.stringify(t, null, 2)
  } catch {
    return null
  }
})

const errorDetails = computed(() => {
  const raw = trace.value?.error || focalEquation.value?.error || props.iteration?.wrapper?.error || null
  if (!raw) return ''
  return String(raw).trim()
})

const canFixWithAgent = computed(() => !!errorDetails.value && !!focalEquation.value)

function onFixWithAgent() {
  const eq = focalEquation.value
  if (eq) emit('fix-step-with-agent', eq)
}

watch(
  () => props.iteration?.wrapperKey,
  (wrapperKey) => {
    const equations = props.iteration?.equations || []
    if (!wrapperKey || equations.length === 0) {
      selectedStepIndex.value = 0
      return
    }
    const failedIndex = equations.findIndex((eq) => eq.status === 'failed')
    if (failedIndex >= 0) {
      selectedStepIndex.value = failedIndex
      return
    }
    const primaryKey = props.iteration?.primary?.equation_key
    const primaryIndex = primaryKey ? equations.findIndex((eq) => eq.equation_key === primaryKey) : -1
    selectedStepIndex.value = primaryIndex >= 0 ? primaryIndex : Math.max(0, equations.length - 1)
  },
  { immediate: true },
)

watch(
  () => [props.iteration?.wrapperKey, focalEquation.value?.equation_key] as const,
  async ([wrapperKey]) => {
    trace.value = null
    toolInputsFromMedia.value = null
    if (!wrapperKey) return
    const eq = focalEquation.value
    if (!eq || props.flowId == null) return

    if (eq.equation_type === 'tool_call' && eq.tool_id) {
      fetchProvidersAndTools().catch(() => {})
    }

    loadingTrace.value = true
    try {
      const url = `${getApiBase()}/flows/${props.flowId}/equations/${encodeURIComponent(eq.equation_key)}/trace`
      const res = await axios.get(url)
      trace.value = res.data
      if (eq.equation_type === 'tool_call') {
        await hydrateToolInputsFromResultMedia(eq.result_media_ids || [])
      }
    } catch {
      trace.value = null
    } finally {
      loadingTrace.value = false
    }
  },
  { immediate: true },
)

async function hydrateToolInputsFromResultMedia(mediaIds: number[]) {
  toolInputsFromMedia.value = null
  for (const mediaId of mediaIds || []) {
    try {
      const res = await axios.get(`${getApiBase()}/media/${mediaId}`)
      const extracted = extractToolInputsFromMediaItem(res.data)
      if (extracted && Object.keys(extracted).length > 0) {
        toolInputsFromMedia.value = extracted
        return
      }
    } catch {
      // Best effort only.
    }
  }
}

function extractToolInputsFromMediaItem(mediaItem: any): Record<string, any> | null {
  if (!mediaItem?.generation_metadata) return null
  try {
    const raw = mediaItem.generation_metadata
    const meta = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (!meta || typeof meta !== 'object') return null
    const params = { ...((meta && meta.parameters) || {}) }
    if (params.seed === undefined && meta.seed !== undefined && meta.seed !== null) params.seed = meta.seed
    if (params.prompt === undefined && meta.prompt) params.prompt = meta.prompt
    if (params.negative_prompt === undefined && meta.negative_prompt) params.negative_prompt = meta.negative_prompt
    if ((params.loras === undefined && params.selected_loras === undefined) && Array.isArray(meta.loras) && meta.loras.length > 0) {
      params.loras = meta.loras.map((lora: any) => ({
        lora: lora?.name ?? lora?.lora ?? null,
        weight: lora?.weight ?? null,
      }))
    }
    return Object.keys(params).length ? params : null
  } catch {
    return null
  }
}

function invalidate() {
  if (!invalidateTargetKey.value) return
  emit('invalidate-equation', invalidateTargetKey.value)
  emit('close')
}

function goToStep(index: number) {
  const total = stepCount.value
  if (total <= 0) return
  selectedStepIndex.value = Math.max(0, Math.min(index, total - 1))
}

function formatDuration(eq: FlowEquation | null): string | null {
  if (!eq) return null
  if (!shouldShowEquationDuration(eq.equation_type)) return null
  const ms = eq.execution_duration_ms
  if (typeof ms === 'number' && Number.isFinite(ms) && ms >= 0) {
    if (ms < 1000) return `${ms} ms`
    if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`
    const mins = Math.floor(ms / 60_000)
    const secs = Math.round((ms % 60_000) / 1000)
    return secs ? `${mins}m ${secs}s` : `${mins}m`
  }
  if (eq.created_at && eq.completed_at) {
    const start = Date.parse(eq.created_at)
    const end = Date.parse(eq.completed_at)
    if (Number.isFinite(start) && Number.isFinite(end) && end >= start) {
      return formatDuration({ ...eq, execution_duration_ms: end - start })
    }
  }
  return null
}

function formatLabel(key: string): string {
  const overrides: Record<string, string> = {
    cfg: 'CFG',
    n: 'Count',
    negative_prompt: 'Negative prompt',
  }
  if (overrides[key]) return overrides[key]
  return key
    .split('_')
    .map((part) => part ? part[0].toUpperCase() + part.slice(1) : part)
    .join(' ')
}

function formatValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function statusTextFor(status?: string | null): string {
  switch (status) {
    case 'completed': return 'Done'
    case 'failed': return 'Failed'
    case 'computing': return 'Running'
    case 'awaiting_input': return 'Awaiting input'
    case 'skipped': return 'Skipped'
    case 'invalidated': return 'Stale'
    default: return 'Pending'
  }
}

function statusClassFor(status?: string | null): string {
  switch (status) {
    case 'completed': return 'text-green-500'
    case 'failed': return 'text-red-400'
    case 'computing': return 'text-blue-400'
    case 'awaiting_input': return 'text-purple-400'
    case 'skipped': return 'text-content-muted'
    case 'invalidated': return 'text-yellow-400'
    default: return 'text-content-muted'
  }
}

function dotClassFor(status?: string | null): string {
  switch (status) {
    case 'completed': return 'bg-green-500'
    case 'failed': return 'bg-red-400'
    case 'computing': return 'bg-blue-400'
    case 'awaiting_input': return 'bg-purple-400'
    case 'invalidated': return 'bg-yellow-400'
    default: return 'bg-content-muted'
  }
}
</script>
