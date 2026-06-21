<template>
  <GenerationDetailsModal
    :show="show"
    :header-icon-path="headerIconPath"
    :header-icon-bg-class="headerIconBgClass"
    :tool-title="toolTitle"
    :provider-label="providerLabel"
    :provider-is-stimma-cloud="isStimmaCloud"
    :duration-label="durationLabel"
    :status-text="statusText"
    :status-dot-class="statusDotClass"
    :status-text-class="statusTextClass"
    :preview-media-ids="previewMediaIds"
    :preview-placeholder="previewPlaceholder"
    :prominent-inputs="prominentInputs"
    :compact-inputs="compactInputs"
    :error-details="errorDetails"
    :raw-json="rawJson"
    @close="$emit('close')"
  />
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useProvidersApi } from '../../composables/useProvidersApi'
import {
  DEFAULT_TASK_TYPE_GRADIENT_CLASS,
  DEFAULT_TASK_TYPE_ICON_PATH,
  getTaskTypeGradientClass,
  getTaskTypeIconPath,
} from '../../utils/taskTypeIcons'
import {
  buildStpCallPayload,
  stringifyStpPayload,
} from '../../utils/stpPayload'
import { STIMMA_CLOUD_PROVIDER_ID } from '../../utils/stimmaCloud'
import GenerationDetailsModal, { type InputEntry } from './GenerationDetailsModal.vue'

interface Job {
  id: number
  status: string
  model_name?: string
  tool_id?: string
  task_type?: string
  error?: string
  parameters?: string
  created_at?: string
  completed_at?: string
  result_media_id?: number | null
}

const props = defineProps<{
  show: boolean
  job: Job | null
}>()

defineEmits<{
  (e: 'close'): void
}>()

const { cachedTools, cachedProviders, fetchProvidersAndTools } = useProvidersApi()

watch(
  () => [props.show, props.job?.tool_id] as const,
  ([visible, toolId]) => {
    if (visible && toolId) fetchProvidersAndTools().catch(() => {})
  },
  { immediate: true },
)

const params = computed<Record<string, any> | null>(() => {
  if (!props.job?.parameters) return null
  try {
    return JSON.parse(props.job.parameters)
  } catch {
    return null
  }
})

const resolvedTool = computed(() => {
  const tid = props.job?.tool_id
  if (!tid) return null
  return cachedTools.value.find((t) => t.full_tool_id === tid) || null
})

const providerId = computed(() => {
  const tid = props.job?.tool_id
  if (!tid) return null
  return tid.split(':')[0] || null
})

const providerLabel = computed<string | null>(() => {
  if (resolvedTool.value?.provider_name) return resolvedTool.value.provider_name
  const pid = providerId.value
  if (!pid) return null
  return cachedProviders.value.find((p) => p.provider_id === pid)?.provider_name || pid
})

const isStimmaCloud = computed(() => providerId.value === STIMMA_CLOUD_PROVIDER_ID)

const toolTitle = computed<string | null>(() => {
  if (resolvedTool.value?.name) return resolvedTool.value.name
  if (props.job?.model_name) return props.job.model_name
  return null
})

const headerIconBgClass = computed(() => {
  const taskType = props.job?.task_type
  if (!taskType) return DEFAULT_TASK_TYPE_GRADIENT_CLASS
  return getTaskTypeGradientClass(taskType)
})

const headerIconPath = computed(() => {
  const taskType = props.job?.task_type
  if (!taskType) return DEFAULT_TASK_TYPE_ICON_PATH
  return getTaskTypeIconPath(taskType)
})

const statusText = computed(() => statusTextFor(props.job?.status))
const statusDotClass = computed(() => dotClassFor(props.job?.status))
const statusTextClass = computed(() => statusClassFor(props.job?.status))

const durationLabel = computed<string | null>(() => {
  const p = params.value
  if (p && typeof p.generation_time === 'number' && Number.isFinite(p.generation_time)) {
    return formatSeconds(p.generation_time)
  }
  const created = props.job?.created_at
  const completed = props.job?.completed_at
  if (created && completed) {
    const start = Date.parse(created)
    const end = Date.parse(completed)
    if (Number.isFinite(start) && Number.isFinite(end) && end >= start) {
      return formatMs(end - start)
    }
  }
  return null
})

const previewMediaIds = computed<number[]>(() => {
  const mid = props.job?.result_media_id
  return mid ? [mid] : []
})

const previewPlaceholder = computed(() => ({
  title: placeholderTitle(props.job?.status),
  body: placeholderBody(props.job?.status),
  iconPath: placeholderIconPath(props.job?.status),
  class: placeholderClass(props.job?.status),
}))

const PROMINENT_KEYS = new Set(['prompt', 'negative_prompt', 'system', 'instructions'])
const EXCLUDED_KEYS = new Set(['generation_time', 'selected_loras', 'loras'])
const LONG_VALUE_KEYS = new Set(['prompt', 'negative_prompt', 'system', 'instructions', 'checkpoint'])
const COMPACT_ORDER = ['width', 'height', 'seed', 'steps', 'cfg', 'guidance', 'sampler', 'scheduler', 'denoise', 'shift', 'checkpoint']

const allInputEntries = computed<InputEntry[]>(() => {
  const p = params.value
  if (!p) return []
  const entries: InputEntry[] = []
  for (const [key, raw] of Object.entries(p)) {
    if (EXCLUDED_KEYS.has(key)) continue
    if (raw === null || raw === undefined || raw === '') continue
    if (Array.isArray(raw) && raw.length === 0) continue
    if (typeof raw === 'object' && !Array.isArray(raw) && Object.keys(raw).length === 0) continue
    const value = formatValue(raw)
    entries.push({
      key,
      label: formatLabel(key),
      value,
      fullWidth: LONG_VALUE_KEYS.has(key) || value.length > 60 || value.includes('\n'),
    })
  }
  // Flatten LoRAs into their own readable field if present
  const loras = (p.loras || p.selected_loras) as any[] | undefined
  if (Array.isArray(loras) && loras.length) {
    const formatted = loras
      .map((lora) => {
        const name = getLoraDisplayName(lora)
        const weight = lora?.weight
        return weight !== undefined && weight !== null ? `${name} (${weight})` : name
      })
      .join('\n')
    entries.push({
      key: 'loras',
      label: 'LoRAs',
      value: formatted,
      fullWidth: true,
    })
  }
  return entries
})

const prominentInputs = computed(() =>
  allInputEntries.value.filter((entry) => PROMINENT_KEYS.has(entry.key)),
)

const compactInputs = computed(() => {
  const rest = allInputEntries.value.filter((entry) => !PROMINENT_KEYS.has(entry.key))
  return rest.slice().sort((a, b) => {
    const aIdx = COMPACT_ORDER.indexOf(a.key)
    const bIdx = COMPACT_ORDER.indexOf(b.key)
    if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx
    if (aIdx !== -1) return -1
    if (bIdx !== -1) return 1
    return a.label.localeCompare(b.label)
  })
})

const errorDetails = computed(() => {
  const raw = props.job?.error
  if (!raw) return ''
  return String(raw).trim()
})

const rawJson = computed<string | null>(() => {
  if (!props.job) return null
  const toolId = props.job.tool_id ?? null
  const payload = buildStpCallPayload(toolId, params.value)
  return stringifyStpPayload(payload)
})

function formatSeconds(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  return secs ? `${mins}m ${secs}s` : `${mins}m`
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms} ms`
  return formatSeconds(ms / 1000)
}

function formatLabel(key: string): string {
  const overrides: Record<string, string> = {
    cfg: 'CFG',
    fps: 'FPS',
    negative_prompt: 'Negative prompt',
    n: 'Count',
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

function getLoraDisplayName(lora: Record<string, any>): string {
  const raw = (lora?.lora || lora?.path || lora?.name || '') as string
  const filename = String(raw).split('/').pop() || raw
  return String(filename).replace(/\.safetensors$/i, '') || 'Unknown LoRA'
}

function statusTextFor(status?: string | null): string {
  switch (status) {
    case 'completed': return 'Done'
    case 'failed': return 'Failed'
    case 'processing': return 'Running'
    case 'assigned': return 'Assigned'
    case 'queued': return 'Queued'
    case 'enhancing': return 'Enhancing'
    default: return 'Pending'
  }
}

function statusClassFor(status?: string | null): string {
  switch (status) {
    case 'completed': return 'text-green-500'
    case 'failed': return 'text-red-400'
    case 'processing': return 'text-blue-400'
    case 'queued':
    case 'assigned':
    case 'enhancing': return 'text-yellow-400'
    default: return 'text-content-muted'
  }
}

function dotClassFor(status?: string | null): string {
  switch (status) {
    case 'completed': return 'bg-green-500'
    case 'failed': return 'bg-red-400'
    case 'processing': return 'bg-blue-400'
    case 'queued':
    case 'assigned':
    case 'enhancing': return 'bg-yellow-400'
    default: return 'bg-content-muted'
  }
}

function placeholderTitle(status?: string | null): string {
  switch (status) {
    case 'failed': return 'No image was produced'
    case 'processing': return 'Generation is running'
    case 'queued':
    case 'assigned': return 'Waiting to start'
    case 'enhancing': return 'Enhancing prompt'
    default: return 'No preview available'
  }
}

function placeholderBody(status?: string | null): string {
  if (status === 'failed') return 'See the error details below.'
  return ''
}

function placeholderClass(status?: string | null): string {
  switch (status) {
    case 'failed': return 'bg-red-500/5 text-red-400'
    case 'processing': return 'bg-blue-500/5 text-blue-400'
    default: return 'bg-overlay-faint text-content-muted'
  }
}

function placeholderIconPath(status?: string | null): string {
  if (status === 'failed') return 'M12 9v3.75m0 3.75h.007v.008H12v-.008ZM10.34 3.94 1.82 18a1.875 1.875 0 0 0 1.603 2.813h17.154A1.875 1.875 0 0 0 22.18 18L13.66 3.94a1.875 1.875 0 0 0-3.32 0Z'
  if (status === 'processing') return 'M16.5 6.75V3.75m0 0h-3m3 0-3 3m-3 10.5v3m0 0h3m-3 0 3-3m-7.5-6h-3m0 0v-3m0 3 3-3m15 3h-3m0 0v3m0-3-3 3'
  return 'M3.375 3.375h17.25v17.25H3.375V3.375Zm3.375 11.25 3-3 2.25 2.25 4.5-4.5 2.25 2.25'
}
</script>
