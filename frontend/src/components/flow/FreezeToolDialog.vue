<template>
  <Teleport to="body">
    <Transition name="freeze-modal">
      <div
        v-if="show"
        class="fixed inset-0 z-modal flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
        @click.self="cancel"
        @keydown.esc="cancel"
      >
        <div class="bg-surface border border-edge rounded-lg shadow-2xl w-[480px] max-w-[92vw] max-h-[88vh] flex flex-col overflow-hidden">
          <!-- Header -->
          <div class="flex items-center gap-2 px-4 py-3 border-b border-edge-subtle">
            <span class="font-semibold text-sm text-content">{{ isEdit ? 'Edit custom tool' : 'Save as Custom Tool' }}</span>
            <div class="flex-1"></div>
            <button
              @click="cancel"
              class="w-7 h-7 flex items-center justify-center text-content-muted hover:text-content hover:bg-overlay-subtle rounded-md transition-colors flex-shrink-0"
              title="Close"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Body -->
          <div class="flex-1 overflow-y-auto px-4 py-4">
            <!-- Loading defaults -->
            <div v-if="loadingDefaults" class="py-10 text-center text-xs text-content-muted">
              Loading…
            </div>

            <template v-else>
              <!-- Source-flow link -->
              <div
                v-if="backingFlowId != null"
                class="flex items-center gap-2.5 bg-base border border-edge-subtle rounded-lg px-3 py-2.5 mb-3.5"
              >
                <BoltIcon class="w-5 h-5 text-blue-500 flex-shrink-0" />
                <div class="flex-1 min-w-0 text-sm font-semibold text-content truncate">{{ sourceFlowName }}</div>
                <!-- In create mode you came from the flow screen, so don't offer a
                     link straight back to it. -->
                <a
                  v-if="isEdit"
                  class="text-[11px] text-blue-400 hover:text-blue-300 flex-shrink-0"
                  href="#"
                  @click.prevent="openBackingFlow"
                >Open flow ↗</a>
              </div>

              <!-- Name -->
              <div class="mb-3.5">
                <label class="block text-[11px] text-content-secondary mb-1">Name</label>
                <input
                  ref="nameInputRef"
                  v-model="name"
                  type="text"
                  placeholder="Tool name"
                  class="w-full bg-base text-content text-[12.5px] border border-transparent rounded-md px-2.5 py-1.5 focus:outline-none focus:border-accent"
                />
              </div>

              <!-- Description -->
              <div class="mb-3.5">
                <label class="block text-[11px] text-content-secondary mb-1">Description</label>
                <input
                  v-model="description"
                  type="text"
                  placeholder="What does this tool do?"
                  class="w-full bg-base text-content text-[12.5px] border border-transparent rounded-md px-2.5 py-1.5 focus:outline-none focus:border-accent"
                />
              </div>

              <!-- Task type (validity anchored to the label) -->
              <div class="mb-3.5">
                <div class="flex items-center justify-between mb-1">
                  <label class="text-[11px] text-content-secondary">Task type</label>
                  <span v-if="validationError" class="flex items-center gap-1 text-[11px] text-red-400">
                    <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2.2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" /></svg>
                    Won't work
                  </span>
                  <span v-else class="flex items-center gap-1 text-[11px] text-green-400">
                    <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2.2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
                    Looks good
                  </span>
                </div>
                <select
                  v-model="taskType"
                  class="w-full bg-base text-content text-[12.5px] border border-transparent rounded-md px-2.5 py-1.5 focus:outline-none focus:border-accent"
                >
                  <option v-for="tt in availableTaskTypes" :key="tt" :value="tt">{{ formatTaskType(tt) }}</option>
                </select>
                <div v-if="validationError" class="text-[11px] text-red-400 mt-1.5">{{ validationError }}</div>
              </div>

              <!-- Resolve pauses (HITL) -->
              <template v-if="hitlNodes.length > 0">
                <label class="block text-[11px] text-content-secondary mb-1 mt-1">Resolve pauses</label>
                <div
                  v-for="node in hitlNodes"
                  :key="node.key"
                  class="flex items-center justify-between gap-2.5 bg-base border border-edge-subtle rounded-lg px-3 py-2 mb-1.5"
                >
                  <div class="min-w-0">
                    <div class="text-xs font-semibold text-content truncate">{{ node.label }}</div>
                    <div class="text-[10px] text-content-muted">{{ node.kindLabel }}</div>
                  </div>
                  <select
                    v-model="hitlPolicies[node.key]"
                    class="bg-surface-raised border border-transparent rounded-md text-content text-[11.5px] px-2 py-1 focus:outline-none focus:border-accent flex-shrink-0"
                  >
                    <option v-for="opt in node.options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                  </select>
                </div>
              </template>

              <!-- Output — which flow output this tool returns. Just a field, like
                   the others; no task-type jargon. -->
              <div
                v-for="out in requiredOutputs"
                :key="out"
                class="mb-3.5"
              >
                <label class="block text-[11px] text-content-secondary mb-1">{{ requiredOutputs.length > 1 ? outputLabel(out) : 'Output' }}</label>
                <select
                  v-model="outputMap[out]"
                  class="w-full bg-base text-content text-[12.5px] border border-transparent rounded-md px-2.5 py-1.5 focus:outline-none focus:border-accent"
                >
                  <option v-if="flowOutputNames.length === 0" :value="undefined" disabled>This flow has no outputs</option>
                  <option v-for="fo in flowOutputNames" :key="fo" :value="fo">{{ fo }}</option>
                </select>
              </div>
            </template>
          </div>

          <!-- Footer -->
          <div class="flex items-center gap-2 px-4 py-3 border-t border-edge-subtle bg-surface-raised">
            <button
              v-if="isEdit"
              @click="handleDelete"
              :disabled="saving || deleting"
              class="text-[11px] text-red-400 hover:text-red-300 mr-auto flex items-center gap-1.5 disabled:opacity-50"
            >
              <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
              </svg>
              {{ deleting ? 'Deleting…' : 'Delete tool' }}
            </button>
            <div v-else class="flex-1"></div>

            <button
              @click="cancel"
              class="text-[12px] text-content-secondary bg-surface-raised rounded-md px-3 py-1.5 hover:bg-overlay-subtle transition-colors"
            >Cancel</button>
            <button
              @click="handleSave"
              :disabled="!canSave || saving || deleting"
              class="text-[12px] text-white bg-accent hover:bg-accent/90 rounded-md px-3 py-1.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {{ saving ? 'Saving…' : (isEdit ? 'Save changes' : 'Save as Custom Tool') }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, reactive, watch, nextTick } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../apiConfig'
import { useToasts } from '../../composables/useToasts'
import { useProvidersApi } from '../../composables/useProvidersApi'
import { formatTaskTypeLabel } from '../../utils/taskTypeIcons'
import { BoltIcon } from '@heroicons/vue/24/solid'

interface HitlNodeInfo {
  key: string
  label: string
  kindLabel: string
  options: { value: string; label: string }[]
}

interface UserTool {
  id: number | string
  name: string
  description?: string | null
  flow_id?: number | null
  task_types?: string[]
  output_map?: Record<string, string>
  hitl_policies?: Record<string, any>
  parameter_schema?: Record<string, any>
}

const props = defineProps<{
  show: boolean
  // create mode
  flowId?: number | string | null
  flowName?: string | null
  flowOutputNames?: string[]
  // names of inputs the flow exposes (create mode) — used to validate that the
  // chosen task type's required inputs are actually present.
  availableInputNames?: string[]
  // raw flow equations (to derive HITL nodes); each item may carry
  // equation_key / equation_type / hitl_kind / hitl_count / display_name
  hitlEquations?: Array<Record<string, any>>
  // edit mode: pass an existing UserTool to prefill + switch to edit mode
  tool?: UserTool | null
}>()

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'saved', tool: any): void
  (e: 'deleted', id: number | string): void
  (e: 'open-flow', flowId: number | string): void
}>()

const { addToast } = useToasts()
const { clearCache } = useProvidersApi()

// Canonical task-type contracts come from the backend (tasks/schemas.py via
// GET /api/tools/task-types) — never hardcoded here. Maps task_type ->
// { required_input, optional_input, required_output }.
interface TaskContract {
  required_input: string[]
  optional_input: string[]
  required_output: string[]
}
const taskContracts = ref<Record<string, TaskContract>>({})

async function loadTaskTypes() {
  if (Object.keys(taskContracts.value).length) return
  try {
    const resp = await axios.get(`${getApiBase()}/tools/task-types`)
    const map: Record<string, TaskContract> = {}
    for (const t of resp.data || []) {
      map[t.task_type] = {
        required_input: t.required_input || [],
        optional_input: t.optional_input || [],
        required_output: t.required_output || [],
      }
    }
    taskContracts.value = map
  } catch (e) {
    // Leave empty; the dropdown shows only the current value until it loads.
  }
}

// Human phrasing for input names we might report as missing.
const INPUT_LABELS: Record<string, string> = {
  prompt: 'a text prompt',
  input_images: 'an image input',
  input_videos: 'a video input',
  mask: 'a mask',
}
function humanizeInput(name: string): string {
  return INPUT_LABELS[name] || `“${name}”`
}

const availableTaskTypes = computed(() => {
  const keys = Object.keys(taskContracts.value)
  // Always render the currently-selected value, even before the list loads.
  if (taskType.value && !keys.includes(taskType.value)) return [taskType.value, ...keys]
  return keys
})

// ----- Local form state -----
const name = ref('')
const description = ref('')
const taskType = ref<string>('image-to-image')
const outputMap = reactive<Record<string, string>>({})
const hitlPolicies = reactive<Record<string, string>>({})

const loadingDefaults = ref(false)
const saving = ref(false)
const deleting = ref(false)
const serverValidationError = ref<string | null>(null)

const nameInputRef = ref<HTMLInputElement | null>(null)

const isEdit = computed(() => !!props.tool)
const backingFlowId = computed<number | string | null>(() =>
  isEdit.value ? (props.tool?.flow_id ?? null) : (props.flowId ?? null),
)
// Human name of the source flow (never a raw id). Callers pass flow-name in both
// modes; fall back to "Untitled flow" when the flow exists but is unnamed.
const sourceFlowName = computed(() => {
  const n = (props.flowName || '').trim()
  if (n) return n
  return backingFlowId.value != null ? 'Untitled flow' : '—'
})
const flowOutputNames = computed(() => props.flowOutputNames || [])

const requiredOutputs = computed(
  () => taskContracts.value[taskType.value]?.required_output || ['assets'],
)

// Human label for an STP output key (don't leak internal contract names).
function outputLabel(key: string): string {
  if (key === 'assets') return 'Result'
  if (key === 'detections') return 'Detections'
  return key.charAt(0).toUpperCase() + key.slice(1)
}

// Derive HITL nodes from raw flow equations. Best-effort: if equations aren't
// provided cleanly, this is simply empty and the section is omitted.
const hitlNodes = computed<HitlNodeInfo[]>(() => {
  const eqs = props.hitlEquations || []
  const out: HitlNodeInfo[] = []
  for (const eq of eqs) {
    const type = eq.equation_type
    const kind = eq.hitl_kind
    if (type !== 'hitl' && !kind) continue
    const count = eq.hitl_count ?? eq.slot_count ?? null
    const label = eq.display_name || eq.description || eq.equation_key || 'Pause'
    let kindLabel = kind || 'pause'
    let options: { value: string; label: string }[]
    if (kind === 'approve') {
      kindLabel = 'approve'
      options = [{ value: 'accept_first', label: 'Accept first' }]
    } else if (kind === 'select') {
      kindLabel = count != null ? `select · 1 of ${count}` : 'select'
      options = [
        { value: 'first', label: 'First' },
        { value: 'random', label: 'Random' },
      ]
    } else {
      options = [{ value: 'accept_first', label: 'Accept first' }]
    }
    out.push({ key: eq.equation_key, label, kindLabel, options })
  }
  return out
})

// Create mode: the flow's exposed inputs, fetched from /freeze-defaults so the
// dialog is self-sufficient (doesn't depend on the parent passing a prop).
// null = not yet known → input check is skipped (no false positives).
const fetchedInputs = ref<string[] | null>(null)

// Inputs the flow exposes — from the tool's parameter_schema (edit) or the
// flow's declared inputs (create). Empty/unknown → input check is skipped.
const exposedInputs = computed<string[]>(() => {
  if (isEdit.value) {
    const props_ = props.tool?.parameter_schema?.properties
    return props_ && typeof props_ === 'object' ? Object.keys(props_) : []
  }
  if (fetchedInputs.value != null) return fetchedInputs.value
  return props.availableInputNames || []
})
const inputsKnown = computed(
  () =>
    isEdit.value ||
    fetchedInputs.value != null ||
    props.availableInputNames != null,
)

// The chosen task type's required inputs must be exposed by the flow. The
// contract comes from the backend; if it hasn't loaded for this type yet we
// can't judge, so we stay quiet rather than claim either state.
const inputValidationError = computed(() => {
  const contract = taskContracts.value[taskType.value]
  if (!contract || !inputsKnown.value) return null
  const missing = contract.required_input.filter((r) => !exposedInputs.value.includes(r))
  if (missing.length === 0) return null
  const what = missing.map(humanizeInput).join(' and ')
  return `${formatTaskType(taskType.value)} needs ${what}, which this flow doesn’t expose`
})

const validationError = computed(() => {
  // Server 400 takes precedence — it's authoritative.
  if (serverValidationError.value) return serverValidationError.value
  // Task-type contract: required inputs must be exposed by the flow.
  if (inputValidationError.value) return inputValidationError.value
  // Local guard: every required output must be mapped to a flow output.
  for (const out of requiredOutputs.value) {
    if (!outputMap[out]) {
      return requiredOutputs.value.length > 1
        ? `Choose which flow output becomes ${outputLabel(out)}`
        : 'Choose which output this tool returns'
    }
  }
  return null
})

const canSave = computed(() => {
  if (loadingDefaults.value) return false
  if (!name.value.trim()) return false
  if (!isEdit.value && backingFlowId.value == null) return false
  if (inputValidationError.value) return false
  for (const out of requiredOutputs.value) {
    if (!outputMap[out]) return false
  }
  return true
})

function formatTaskType(tt: string): string {
  return formatTaskTypeLabel(tt)
}

// Reset output map keys when the task type's required outputs change, keeping a
// sensible default binding ("assets" → first flow output) when possible.
watch(requiredOutputs, (outs) => {
  for (const key of Object.keys(outputMap)) {
    if (!outs.includes(key)) delete outputMap[key]
  }
  for (const out of outs) {
    if (!outputMap[out] && flowOutputNames.value.length > 0) {
      outputMap[out] = flowOutputNames.value[0]
    }
  }
})

// Clear a stale server validation error once the user changes the task type.
watch(taskType, () => {
  serverValidationError.value = null
})

function resetForm() {
  serverValidationError.value = null
  fetchedInputs.value = null
  for (const k of Object.keys(outputMap)) delete outputMap[k]
  for (const k of Object.keys(hitlPolicies)) delete hitlPolicies[k]
}

async function initCreate() {
  resetForm()
  name.value = props.flowName ? `${props.flowName}` : 'Untitled tool'
  description.value = ''
  taskType.value = 'image-to-image'
  // Seed HITL policy defaults from derived nodes.
  for (const node of hitlNodes.value) {
    hitlPolicies[node.key] = node.options[0]?.value || 'first'
  }
  // Pull inferred defaults from the backend.
  if (backingFlowId.value == null) return
  loadingDefaults.value = true
  try {
    // Ensure the task-type contracts are loaded before inferring a default
    // (the includes() check below depends on them).
    await loadTaskTypes()
    const base = getApiBase()
    const resp = await axios.get(`${base}/flows/${backingFlowId.value}/freeze-defaults`)
    const data = resp.data || {}
    // Exposed inputs drive task-type validation (self-sufficient; no prop needed).
    if (Array.isArray(data.exposed_inputs)) {
      fetchedInputs.value = data.exposed_inputs
    } else if (props.availableInputNames != null) {
      fetchedInputs.value = props.availableInputNames
    }
    const tts: string[] = data.task_types || []
    if (tts.length > 0 && availableTaskTypes.value.includes(tts[0])) {
      taskType.value = tts[0]
    }
    const map: Record<string, string> = data.output_map || {}
    for (const [k, v] of Object.entries(map)) {
      if (v != null) outputMap[k] = v as string
    }
  } catch (err) {
    // Non-fatal: fall back to local defaults.
    console.warn('[FreezeToolDialog] freeze-defaults failed', err)
  } finally {
    loadingDefaults.value = false
  }
  // Fill any still-unbound required outputs with the first flow output.
  for (const out of requiredOutputs.value) {
    if (!outputMap[out] && flowOutputNames.value.length > 0) {
      outputMap[out] = flowOutputNames.value[0]
    }
  }
}

function initEdit() {
  resetForm()
  const t = props.tool!
  name.value = t.name || ''
  description.value = t.description || ''
  const tts = t.task_types || []
  taskType.value = tts.length > 0 ? tts[0] : 'image-to-image'
  for (const [k, v] of Object.entries(t.output_map || {})) {
    if (v != null) outputMap[k] = v as string
  }
  for (const [k, v] of Object.entries(t.hitl_policies || {})) {
    hitlPolicies[k] = typeof v === 'string' ? v : ((v as any)?.policy || 'first')
  }
  // Default-bind any required output the saved map didn't cover.
  for (const out of requiredOutputs.value) {
    if (!outputMap[out] && flowOutputNames.value.length > 0) {
      outputMap[out] = flowOutputNames.value[0]
    }
  }
}

watch(
  () => props.show,
  (open) => {
    if (!open) return
    loadTaskTypes()  // canonical task-type contracts (cached after first load)
    if (isEdit.value) initEdit()
    else initCreate()
    nextTick(() => nameInputRef.value?.focus())
  },
  { immediate: true },
)

function cancel() {
  emit('cancel')
}

function openBackingFlow() {
  if (backingFlowId.value != null) emit('open-flow', backingFlowId.value)
}

function buildPayload() {
  const cleanOutputMap: Record<string, string> = {}
  for (const out of requiredOutputs.value) {
    if (outputMap[out]) cleanOutputMap[out] = outputMap[out]
  }
  // Backend resolver (providers/user_tools.py::_make_hitl_resolver) reads
  // {equation_key: {"policy": "<first|random|accept_first>"}}.
  const cleanHitl: Record<string, any> = {}
  for (const node of hitlNodes.value) {
    const p = hitlPolicies[node.key]
    if (p) cleanHitl[node.key] = { policy: p }
  }
  return {
    name: name.value.trim(),
    description: description.value.trim() || null,
    task_types: [taskType.value],
    output_map: cleanOutputMap,
    hitl_policies: cleanHitl,
  }
}

async function handleSave() {
  if (!canSave.value || saving.value) return
  serverValidationError.value = null
  saving.value = true
  const base = getApiBase()
  try {
    if (isEdit.value) {
      // In-place update — stable tool id (PATCH /api/user-tools/{id}).
      const resp = await axios.patch(`${base}/user-tools/${props.tool!.id}`, buildPayload())
      clearCache()
      addToast(`Tool "${resp.data?.name || name.value}" updated`, 'success', 4000)
      emit('saved', resp.data)
    } else {
      const resp = await axios.post(`${base}/flows/${backingFlowId.value}/freeze`, buildPayload())
      clearCache()
      addToast(`Tool "${resp.data?.name || name.value}" created`, 'success', 4000)
      emit('saved', resp.data)
    }
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    if (err?.response?.status === 400 && detail) {
      serverValidationError.value = typeof detail === 'string' ? detail : JSON.stringify(detail)
    } else {
      const msg = detail || err?.message || 'Failed to save tool'
      addToast(typeof msg === 'string' ? msg : 'Failed to save tool', 'error', 6000)
    }
  } finally {
    saving.value = false
  }
}

async function handleDelete() {
  if (!isEdit.value || deleting.value) return
  deleting.value = true
  try {
    const base = getApiBase()
    const id = props.tool!.id
    await axios.delete(`${base}/user-tools/${id}`)
    clearCache()
    addToast(`Tool "${props.tool!.name}" deleted`, 'success', 4000)
    emit('deleted', id)
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.message || 'Failed to delete tool'
    addToast(typeof msg === 'string' ? msg : 'Failed to delete tool', 'error', 6000)
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.freeze-modal-enter-active,
.freeze-modal-leave-active {
  transition: opacity 0.15s ease;
}
.freeze-modal-enter-from,
.freeze-modal-leave-to {
  opacity: 0;
}
.freeze-modal-enter-active > div,
.freeze-modal-leave-active > div {
  transition: transform 0.15s ease;
}
.freeze-modal-enter-from > div,
.freeze-modal-leave-to > div {
  transform: scale(0.96);
}
</style>
