<template>
  <div class="mb-6">
    <!-- Panel header -->
    <div class="flex items-center justify-between mb-3">
      <span class="flex items-center gap-1.5 text-xs font-medium text-content-muted uppercase tracking-wide">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 text-purple-400">
          <path d="M9.638 1.093a.75.75 0 01.724 0l8.5 4.75a.75.75 0 010 1.314l-8.5 4.75a.75.75 0 01-.724 0l-8.5-4.75a.75.75 0 010-1.314l8.5-4.75z" />
          <path d="M3.265 10.602l5.649 3.156a2.25 2.25 0 002.172 0l5.649-3.156 1.127.63a.75.75 0 010 1.31l-8.5 4.75a.75.75 0 01-.724 0l-8.5-4.75a.75.75 0 010-1.31l1.127-.63z" />
        </svg>
        Post-processing
        <span v-if="chain.steps.length" class="px-1.5 py-px rounded-full bg-white/[0.06] text-[10px] text-content-tertiary normal-case tracking-normal">
          {{ chain.steps.length }} step{{ chain.steps.length === 1 ? '' : 's' }}
        </span>
      </span>
      <label class="inline-flex items-center gap-2 cursor-pointer">
        <span class="text-xs text-content-tertiary">{{ chain.enabled ? 'On' : 'Off' }}</span>
        <input
          type="checkbox"
          :checked="chain.enabled"
          @change="setChainEnabled(($event.target as HTMLInputElement).checked)"
          class="sr-only peer"
        >
        <div class="relative w-9 h-5 bg-surface-hover peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-green-600"></div>
      </label>
    </div>

    <!-- Step stack -->
    <div :class="chain.enabled ? '' : 'opacity-60'">
      <template v-for="(step, index) in chain.steps" :key="step.id">
        <!-- Insertion indicator (drag reorder) -->
        <div v-if="drag.active && drag.overIndex === index" class="h-0.5 bg-blue-500 rounded my-1"></div>
        <div
          @dragover.prevent="onDragOver($event, index)"
          @drop.prevent="onDrop(index)"
        >
          <ChainStepCard
            :step="step"
            :title="stepTitle(step)"
            :summary="stepSummary(step)"
            :expanded="expandedIds.has(step.id)"
            :incompatible="mediaFlow.incompatibleStepIds.has(step.id)"
            :needed-input="stepNeededInput(step)"
            :unavailable="step.kind === 'tool' && toolsLoaded && !toolById(step.tool_id)"
            :dragging="drag.active && drag.fromIndex === index"
            :thumb-media-id="stepThumbs?.[step.id] ?? null"
            @toggle-expanded="toggleExpanded(step.id)"
            @set-enabled="setStepEnabled(step.id, $event)"
            @remove="removeStep(step.id)"
            @grip-dragstart="onGripDragStart($event, index)"
            @grip-dragend="onGripDragEnd"
          >
            <template #settings>
              <ChainStepSettings
                :step="step"
                @update:settings="updateStepSettings(step.id, $event)"
              />
            </template>
          </ChainStepCard>
        </div>
        <!-- Connector -->
        <div v-if="index < chain.steps.length - 1" class="flex justify-center py-0.5 text-content-muted/40">
          <svg width="11" height="7" viewBox="0 0 11 7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M2 1.5l3.5 3.5L9 1.5" /></svg>
        </div>
      </template>
      <div v-if="drag.active && drag.overIndex === chain.steps.length" class="h-0.5 bg-blue-500 rounded my-1"></div>

      <!-- Add step (dashed row) -->
      <div class="relative" :class="chain.steps.length ? 'mt-2' : ''" @dragover.prevent="onDragOver($event, chain.steps.length)" @drop.prevent="onDrop(chain.steps.length)">
        <button
          type="button"
          class="w-full flex items-center justify-center gap-1.5 rounded-lg border border-dashed border-edge-subtle px-3 py-2 text-xs text-content-muted hover:text-content-secondary hover:border-edge transition-colors"
          @click="toggleAddMenu"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
            <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
          </svg>
          Add step
        </button>
        <AddStepMenu
          v-if="addMenuOpen"
          :tools="candidateTools"
          :filters="candidateFilters"
          @add-tool="addToolStep"
          @add-filter="addFilterStep"
          @close="addMenuOpen = false"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import ChainStepCard from './ChainStepCard.vue'
import ChainStepSettings from './ChainStepSettings.vue'
import AddStepMenu from './AddStepMenu.vue'
import { useProvidersApi, type ProviderTool } from '../../../composables/useProvidersApi'
import {
  CHAIN_TOOL_TASK_TYPES,
  chainMediaFlow,
  newStepId,
  stepInputMedia,
  type ChainStep,
  type PostProcessingChain,
} from '../../../utils/postProcessingChain'
import {
  CHAIN_FILTER_DEFS,
  getChainFilterDef,
  getChainFilterDefaults,
  type ChainFilterDef,
} from '@stimma/image-editor'

const props = defineProps<{
  chain: PostProcessingChain
  /** The ToolView's own tool — excluded from the Add menu's offerings. */
  currentToolId?: string
  /** Optional per-step output thumbnails (step id → media id) from the last run. */
  stepThumbs?: Record<string, number>
}>()

const emit = defineEmits<{
  (e: 'update:chain', chain: PostProcessingChain): void
}>()

// --- Candidate steps for the Add menu --------------------------------------

const { fetchProvidersAndTools } = useProvidersApi()
const allTools = ref<ProviderTool[]>([])
const toolsLoaded = ref(false)

onMounted(async () => {
  try {
    const { tools } = await fetchProvidersAndTools()
    allTools.value = tools
  } catch (err) {
    console.error('Failed to load tools for post-processing menu:', err)
  } finally {
    toolsLoaded.value = true
  }
})

function toolById(fullToolId?: string): ProviderTool | undefined {
  if (!fullToolId) return undefined
  return allTools.value.find(t => t.full_tool_id === fullToolId)
}

const mediaFlow = computed(() => chainMediaFlow(props.chain))

// Tools offered in the Add menu: chain-compatible task types whose input
// matches the chain's current output media type (a video step flips the
// running type to video — only video-accepting steps may follow).
const candidateTools = computed(() => {
  const running = mediaFlow.value.finalType
  const chainTypes = new Set<string>(CHAIN_TOOL_TASK_TYPES)
  return allTools.value.filter(t => {
    if (t.full_tool_id === props.currentToolId) return false
    if (t.availability === 'unconfigured') return false
    const tts = (t.task_types?.length ? t.task_types : [t.task_type]).filter(tt => chainTypes.has(tt))
    if (!tts.length) return false
    return tts.some(tt => stepInputMedia(tt, 'tool') === running)
  })
})

// In-app filters are image-only; hide them once the chain outputs video.
const candidateFilters = computed<ChainFilterDef[]>(() =>
  mediaFlow.value.finalType === 'image' ? CHAIN_FILTER_DEFS : []
)

// --- Chain mutations --------------------------------------------------------

function updateChain(updater: (chain: PostProcessingChain) => PostProcessingChain) {
  emit('update:chain', updater({ enabled: props.chain.enabled, steps: [...props.chain.steps] }))
}

function setChainEnabled(enabled: boolean) {
  updateChain(c => ({ ...c, enabled }))
}

function setStepEnabled(id: string, enabled: boolean) {
  updateChain(c => ({
    ...c,
    steps: c.steps.map(s => (s.id === id ? { ...s, enabled } : s)),
  }))
}

function removeStep(id: string) {
  expandedIds.value.delete(id)
  updateChain(c => ({ ...c, steps: c.steps.filter(s => s.id !== id) }))
}

function updateStepSettings(id: string, settings: Record<string, any>) {
  updateChain(c => ({
    ...c,
    steps: c.steps.map(s => (s.id === id ? { ...s, settings: { ...s.settings, ...settings } } : s)),
  }))
}

const addMenuOpen = ref(false)
function toggleAddMenu() {
  addMenuOpen.value = !addMenuOpen.value
}

// Resolve the chain task type a tool step should run as.
function chainTaskTypeFor(tool: ProviderTool): string {
  const running = mediaFlow.value.finalType
  const tts = (tool.task_types?.length ? tool.task_types : [tool.task_type])
    .filter(tt => (CHAIN_TOOL_TASK_TYPES as readonly string[]).includes(tt))
  return tts.find(tt => stepInputMedia(tt, 'tool') === running) || tts[0]
}

function addToolStep(tool: ProviderTool) {
  addMenuOpen.value = false
  const step: ChainStep = {
    id: newStepId(),
    kind: 'tool',
    enabled: true,
    tool_id: tool.full_tool_id,
    task_type: chainTaskTypeFor(tool),
    tool_name: tool.name,
    settings: {}, // empty = the tool's schema defaults (overlaid at execution)
  }
  updateChain(c => ({ ...c, steps: [...c.steps, step] }))
}

function addFilterStep(filter: ChainFilterDef) {
  addMenuOpen.value = false
  const step: ChainStep = {
    id: newStepId(),
    kind: 'filter',
    enabled: true,
    filter_id: filter.id,
    settings: getChainFilterDefaults(filter.id),
  }
  updateChain(c => ({ ...c, steps: [...c.steps, step] }))
}

// --- Expand / collapse -------------------------------------------------------

const expandedIds = ref(new Set<string>())
function toggleExpanded(id: string) {
  const next = new Set(expandedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedIds.value = next
}

// --- Display helpers ---------------------------------------------------------

function stepTitle(step: ChainStep): string {
  if (step.kind === 'tool') {
    return step.tool_name || toolById(step.tool_id)?.name || step.tool_id || 'Tool'
  }
  return getChainFilterDef(step.filter_id || '')?.label || step.filter_id || 'Filter'
}

function stepSummary(step: ChainStep): string {
  if (step.kind === 'tool') {
    const overrides = Object.keys(step.settings).length
    const base = `STP tool · ${step.task_type || 'image → image'}`
    return overrides ? `${base} · ${overrides} setting${overrides === 1 ? '' : 's'}` : base
  }
  const def = getChainFilterDef(step.filter_id || '')
  if (!def) return 'Built-in filter'
  const parts = def.params
    .filter(p => step.settings[p.name] !== undefined && step.settings[p.name] !== p.default)
    .slice(0, 3)
    .map(p => `${p.label.toLowerCase()} ${step.settings[p.name]}`)
  return parts.length ? parts.join(' · ') : def.description
}

function stepNeededInput(step: ChainStep): string {
  return stepInputMedia(step.task_type, step.kind)
}

// --- Drag reorder ------------------------------------------------------------

const drag = reactive({ active: false, fromIndex: -1, overIndex: -1 })

function onGripDragStart(ev: DragEvent, index: number) {
  drag.active = true
  drag.fromIndex = index
  drag.overIndex = -1
  if (ev.dataTransfer) {
    ev.dataTransfer.effectAllowed = 'move'
    ev.dataTransfer.setData('text/plain', String(index))
  }
}

function onGripDragEnd() {
  drag.active = false
  drag.fromIndex = -1
  drag.overIndex = -1
}

function onDragOver(ev: DragEvent, index: number) {
  if (!drag.active) return
  const el = ev.currentTarget as HTMLElement
  const rect = el.getBoundingClientRect()
  const before = ev.clientY < rect.top + rect.height / 2
  drag.overIndex = before ? index : Math.min(index + 1, props.chain.steps.length)
}

function onDrop(_index: number) {
  if (!drag.active || drag.overIndex < 0) return
  const from = drag.fromIndex
  let to = drag.overIndex
  onGripDragEnd()
  if (to > from) to -= 1
  if (to === from) return
  updateChain(c => {
    const steps = [...c.steps]
    const [moved] = steps.splice(from, 1)
    steps.splice(to, 0, moved)
    return { ...c, steps }
  })
}
</script>
