<template>
  <div class="mb-6">
    <!-- Panel header -->
    <div class="flex items-center justify-between mb-3">
      <span class="text-xs font-medium text-content-muted uppercase tracking-wide">Post-processing</span>
      <label v-if="chain.steps.length" class="inline-flex items-center gap-2 cursor-pointer">
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
          :class="index > 0 ? 'mt-1.5' : ''"
          @dragover.prevent="onDragOver($event, index)"
          @drop.prevent="onDrop(index)"
        >
          <ChainStepCard
            :step="step"
            :title="stepTitle(step)"
            :summary="stepSummary(step)"
            :provider="stepProvider(step)"
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
                @update:prompt-options="updateStepPromptOptions(step.id, $event)"
              />
            </template>
          </ChainStepCard>
        </div>
      </template>
      <div v-if="drag.active && drag.overIndex === chain.steps.length" class="h-0.5 bg-blue-500 rounded my-1"></div>
    </div>

    <!-- Add step (dashed row) — outside the disabled-dim wrapper: adding a step
         auto-enables the chain, and an opacity ancestor would composite the
         dropdown translucently over the controls behind it. -->
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
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import ChainStepCard from './ChainStepCard.vue'
import ChainStepSettings from './ChainStepSettings.vue'
import AddStepMenu from './AddStepMenu.vue'
import { useProvidersApi, type ProviderTool } from '../../../composables/useProvidersApi'
import { isStimmaCloudTool } from '../../../utils/stimmaCloud'
import {
  CHAIN_TOOL_TASK_TYPES,
  chainMediaFlow,
  defaultChainStepPromptOptions,
  defaultInsertIndex,
  newStepId,
  stepInputMedia,
  stepAcceptedMedia,
  type ChainStep,
  type ChainStepPromptOptions,
  type PostProcessingChain,
} from '../../../utils/postProcessingChain'
import { videoParamDefaultsForTool } from '../../../composables/useToolSchemaFeatures'
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
  /** The base generation's output type (a video tool's chain starts from video). */
  baseMediaType?: 'image' | 'video'
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

const baseType = computed<'image' | 'video'>(() => props.baseMediaType || 'image')

const mediaFlow = computed(() => chainMediaFlow(props.chain, baseType.value))

// Media types present at ANY insertion position. A step is offered if some
// stage of the chain accepts it — picking one inserts it at the latest stage
// that does (so image steps stay addable after a video transition).
const stageTypes = computed(() => new Set(mediaFlow.value.positionTypes))

const candidateTools = computed(() => {
  const chainTypes = new Set<string>(CHAIN_TOOL_TASK_TYPES)
  return allTools.value.filter(t => {
    if (t.full_tool_id === props.currentToolId) return false
    if (t.availability === 'unconfigured') return false
    // Built-in filters are catalog tools too, but the menu presents them in
    // its dedicated Filters group — don't list them twice.
    if (t.provider_id === 'builtin' && t.task_type === 'filter') return false
    const tts = (t.task_types?.length ? t.task_types : [t.task_type]).filter(tt => chainTypes.has(tt))
    if (!tts.length) return false
    return tts.some(tt => stageTypes.value.has(stepInputMedia(tt, 'tool')))
  })
})

// Offer a filter when some chain stage carries a media type it accepts (today's
// filters accept both, so they're offered whenever the chain has any stage).
const candidateFilters = computed<ChainFilterDef[]>(() =>
  CHAIN_FILTER_DEFS.filter(f =>
    [...stageTypes.value].some(t => stepAcceptedMedia({ kind: 'filter', filter_id: f.id }).includes(t))
  )
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
    steps: c.steps.map(s => {
      if (s.id !== id) return s
      // undefined in the patch means "remove this setting" (e.g. switching
      // the upscale picker between scale_factor and resolution)
      const merged = { ...s.settings }
      for (const [k, v] of Object.entries(settings)) {
        if (v === undefined) delete merged[k]
        else merged[k] = v
      }
      return { ...s, settings: merged }
    }),
  }))
}

function updateStepPromptOptions(id: string, promptOptions: ChainStepPromptOptions) {
  updateChain(c => ({
    ...c,
    steps: c.steps.map(s => (s.id === id ? { ...s, promptOptions } : s)),
  }))
}

const addMenuOpen = ref(false)
function toggleAddMenu() {
  addMenuOpen.value = !addMenuOpen.value
}

// Resolve the chain task type a tool step should run as — prefer one whose
// input type has a stage in the chain.
function chainTaskTypeFor(tool: ProviderTool): string {
  const tts = (tool.task_types?.length ? tool.task_types : [tool.task_type])
    .filter(tt => (CHAIN_TOOL_TASK_TYPES as readonly string[]).includes(tt))
  return tts.find(tt => stageTypes.value.has(stepInputMedia(tt, 'tool'))) || tts[0]
}

// Insert a new step at the latest stage that accepts its input type (an image
// step lands just before the chain's video transition, not at the end).
function insertStep(step: ChainStep) {
  const at = defaultInsertIndex(props.chain, stepAcceptedMedia(step), baseType.value)
  updateChain(c => {
    const steps = [...c.steps]
    steps.splice(at < 0 ? steps.length : at, 0, step)
    // Adding a step turns the chain on — going from empty to a working
    // pipeline shouldn't cost the user an extra click on the global switch.
    return { ...c, enabled: true, steps }
  })
  expandStep(step.id)
}

function addToolStep(tool: ProviderTool) {
  addMenuOpen.value = false
  insertStep({
    id: newStepId(),
    kind: 'tool',
    enabled: true,
    tool_id: tool.full_tool_id,
    task_type: chainTaskTypeFor(tool),
    tool_name: tool.name,
    // Unset settings fall back to the tool's schema defaults at execution;
    // duration/fps are seeded eagerly because ToolView prefills them too
    // (videoParamDefaultsForTool is the shared source of truth) — the panel
    // must show exactly what the step will run with.
    settings: { ...videoParamDefaultsForTool(tool) },
    // Same new-state prompt defaults as ToolView (Enhance ON).
    promptOptions: defaultChainStepPromptOptions(),
  })
}

function addFilterStep(filter: ChainFilterDef) {
  addMenuOpen.value = false
  insertStep({
    id: newStepId(),
    kind: 'filter',
    enabled: true,
    filter_id: filter.id,
    settings: getChainFilterDefaults(filter.id),
  })
}

// --- Expand / collapse -------------------------------------------------------

const expandedIds = ref(new Set<string>())
function toggleExpanded(id: string) {
  const next = new Set(expandedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedIds.value = next
}

// A freshly added step opens expanded — tuning its settings is the very next
// thing the user does.
function expandStep(id: string) {
  const next = new Set(expandedIds.value)
  next.add(id)
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
  if (step.kind === 'tool') return ''
  const def = getChainFilterDef(step.filter_id || '')
  if (!def) return 'Built-in filter'
  const parts = def.params
    .filter(p => step.settings[p.name] !== undefined && step.settings[p.name] !== p.default)
    .slice(0, 3)
    .map(p => `${p.label.toLowerCase()} ${step.settings[p.name]}`)
  return parts.length ? parts.join(' · ') : def.description
}

// Standard provider treatment for tool-step sub rows (Stimma Cloud gradient
// badge or provider-name pill — same as AllToolsView).
function stepProvider(step: ChainStep): { name: string; isStimmaCloud: boolean } | null {
  if (step.kind !== 'tool' || !step.tool_id) return null
  const tool = toolById(step.tool_id)
  const providerId = tool?.provider_id || step.tool_id.split(':')[0]
  return {
    name: tool?.provider_name || providerId,
    isStimmaCloud: isStimmaCloudTool(tool || { provider_id: providerId }),
  }
}

function stepNeededInput(step: ChainStep): string {
  return stepAcceptedMedia(step).join('/')
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
