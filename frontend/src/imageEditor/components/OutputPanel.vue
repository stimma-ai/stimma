<script setup lang="ts">
/**
 * The output stage, as a place rather than a row.
 *
 * It lives beside Edits instead of in it for two reasons. The Edits list is the
 * stack and nothing else — a pinned entry with different physics is the same
 * mistake the checkpoint band made, in miniature. And an upscaler is a TOOL: it
 * comes with a picker and however many parameters its schema declares, which a
 * 42px row can only ever misrepresent with invented buttons.
 *
 * Nothing here knows what an upscaler is called or what knobs it has. The
 * `upscale-image` task declares the interface — `x-control: upscale_resolution`
 * resolving to `scale_factor` or `resolution`, plus whatever else — and the
 * same `useToolSchemaFeatures` / `SchemaParamGroup` pair ToolView uses renders
 * it. Install a different upscaler and this panel changes with it.
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import ToolIcon from '../../components/tools/ToolIcon.vue'
import ToolProviderLabel from '../../components/tools/ToolProviderLabel.vue'
import { isStimmaCloudTool } from '../../utils/stimmaCloud'
import SchemaParamGroup from '../../components/generation/SchemaParamGroup.vue'
import OutputSizeControl from './OutputSizeControl.vue'
import ToolPicker from './ToolPicker.vue'
import { useToolSchemaFeatures } from '../../composables/useToolSchemaFeatures'
import { outputDimensions } from '../stack/outputStage'
import type { OutputStage } from '../stack/types'

const props = defineProps<{
  output: OutputStage
  /** The whole catalog; the panel filters it to what can upscale. */
  tools: any[]
  /** The composite's current size — what a save would start from. */
  inputWidth: number
  inputHeight: number
  pickerOpen: boolean
}>()

const emit = defineEmits<{
  update: [Partial<OutputStage>]
  setParams: [Record<string, any>]
  togglePicker: []
  closePicker: []
}>()

const upscalers = computed(() =>
  props.tools.filter(t => (t.task_types || []).includes('upscale-image'))
)

const tool = computed(() =>
  props.tools.find(t => t.full_tool_id === props.output.tool_id) ?? null
)

const isCloud = (t: any) => isStimmaCloudTool(t)

// The same schema-driven feature set ToolView and chain steps get, for
// whichever tool is selected. A tool ref is all it needs.
const {
  groupedGenericParams,
  showUpscalePicker,
  hasScaleFactor,
  hasUpscaleResolution,
  scaleFactorConstraints,
} = useToolSchemaFeatures({
  tool,
  availableLoras: computed(() => []),
})

/**
 * The three states, named for what they do rather than for how they are
 * implemented. "AI upscale" is the model; "Resize" is arithmetic — sharp, free,
 * instant, and not a lesser version of anything, which is why it is not called
 * plain or basic.
 */
const MODES = [
  { id: 'off', label: 'Off' },
  { id: 'ai', label: 'AI upscale' },
  { id: 'resize', label: 'Resize' },
] as const

const mode = computed<'off' | 'ai' | 'resize'>(() => {
  if (!props.output.enabled) return 'off'
  return props.output.method === 'resample' ? 'resize' : 'ai'
})

function setMode(id: 'off' | 'ai' | 'resize') {
  if (id === 'off') {
    // Method survives being switched off, so coming back lands where it was.
    emit('update', { enabled: false })
    return
  }
  emit('update', { enabled: true, method: id === 'ai' ? 'photo' : 'resample' })
}


/**
 * Where the tool menu goes.
 *
 * Anchored under the trigger and then pushed back inside the window: this panel
 * is the last thing before the right edge, so a 320px menu that started at the
 * trigger's left edge would hang off the screen. Fixed coordinates rather than
 * an absolute child, because the panel scrolls and a scroll container clips
 * anything that reaches past it.
 */
const MENU_WIDTH = 320
const VIEWPORT_MARGIN = 8

const triggerRef = ref<HTMLElement | null>(null)
const menuStyle = ref<Record<string, string>>({})

function placeMenu() {
  const trigger = triggerRef.value
  if (!trigger) return
  const rect = trigger.getBoundingClientRect()
  const width = Math.min(MENU_WIDTH, window.innerWidth - VIEWPORT_MARGIN * 2)
  const left = Math.max(
    VIEWPORT_MARGIN,
    Math.min(rect.left, window.innerWidth - width - VIEWPORT_MARGIN)
  )
  // Flip above the trigger when the list would not fit below it.
  const below = window.innerHeight - rect.bottom
  const style: Record<string, string> = { left: `${left}px` }
  if (below < 200 && rect.top > below) {
    style.bottom = `${window.innerHeight - rect.top + 4}px`
  } else {
    style.top = `${rect.bottom + 4}px`
  }
  menuStyle.value = style
}

watch(
  () => props.pickerOpen,
  open => {
    if (!open) {
      window.removeEventListener('resize', placeMenu)
      window.removeEventListener('scroll', placeMenu, true)
      return
    }
    void nextTick(placeMenu)
    window.addEventListener('resize', placeMenu)
    // Capture phase: the sidebar's own scroll container is what moves the
    // trigger, and its scroll does not bubble.
    window.addEventListener('scroll', placeMenu, true)
  }
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', placeMenu)
  window.removeEventListener('scroll', placeMenu, true)
})

const usesTool = computed(() => props.output.method === 'photo')

const pickerValue = computed(() => ({
  resolutionMode: (props.output.params.resolutionMode ?? 'relative') as 'relative' | 'pixels',
  scaleFactor: props.output.params.scaleFactor ?? 2,
  targetResolution: props.output.params.targetResolution ?? 1080,
}))

function onPickerUpdate(value: {
  resolutionMode: 'relative' | 'pixels'
  scaleFactor: number
  targetResolution: number
}) {
  emit('setParams', value)
}

const target = computed(() =>
  outputDimensions(props.output, props.inputWidth, props.inputHeight)
)

const unchanged = computed(() =>
  target.value.width === props.inputWidth && target.value.height === props.inputHeight
)
</script>

<template>
  <div class="flex-1 overflow-y-auto custom-scrollbar px-3 py-3 space-y-3">
    <!-- Off is one of the choices, not a checkbox in front of them. Three
         states, one control. -->
    <div class="space-y-1.5">
      <p class="text-xs font-medium text-content-tertiary">Upscale on save</p>
      <div class="flex items-center rounded-md bg-overlay-light p-0.5 text-xs">
        <button
          v-for="choice in MODES"
          :key="choice.id"
          type="button"
          class="flex-1 px-2 py-1 rounded transition-colors
                 focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
          :class="mode === choice.id
            ? 'bg-selection/15 text-content'
            : 'text-content-tertiary hover:text-content-secondary'"
          @click="setMode(choice.id)"
        >
          {{ choice.label }}
        </button>
      </div>
    </div>

    <template v-if="output.enabled">
      <!-- The tool picker is its own label: a "Tool" heading over a row that
           already shows a tool name and its provider says nothing twice. -->
      <div v-if="usesTool" class="relative">
        <p v-if="!upscalers.length" class="text-xs text-amber-400/90">
          No installed tool can upscale. Resize still works.
        </p>

        <template v-else>
          <button
            type="button"
            class="w-full px-2.5 py-2 rounded-md bg-surface-raised text-left text-[13px]
                   flex items-center gap-2.5 hover:bg-overlay-light transition-colors
                   focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
            ref="triggerRef"
            @click="emit('togglePicker')"
          >
            <template v-if="tool">
              <div class="w-3.5 h-3.5 shrink-0" :class="isCloud(tool) ? '' : 'text-content-tertiary'">
                <ToolIcon :tool="tool" size="xs" :bare="true" :ring="false" />
              </div>
              <span class="flex-1 min-w-0 truncate text-content">{{ tool.name }}</span>
              <ToolProviderLabel :cloud="isCloud(tool)" :provider-name="tool.provider_name" />
            </template>
            <span v-else class="flex-1 text-content-tertiary">Choose a tool</span>
          </button>

          <!-- Teleported and fixed, not absolute: the menu keeps the width its
               content needs and SHIFTS to fit the window. Constraining it to
               the column instead truncated tool names, and positioning it
               inside the panel put it in a scroll container that clips
               anything reaching past the sidebar's left edge. -->
          <Teleport to="body">
            <div v-if="pickerOpen" class="fixed z-menu" :style="menuStyle">
              <ToolPicker
                :tools="tools"
                task-type="upscale-image"
                :selected-id="output.tool_id"
                width-class="w-[320px] max-w-[calc(100vw-1rem)]"
                @select="emit('update', { tool_id: $event.full_tool_id }); emit('closePicker')"
                @close="emit('closePicker')"
              />
            </div>
          </Teleport>
        </template>
      </div>

      <!-- Size ------------------------------------------------------------ -->
      <!-- The tool's own control when it declares one; a plain factor when
           there is no tool to declare anything. -->
      <OutputSizeControl
        v-if="!usesTool || showUpscalePicker"
        :model-value="pickerValue"
        @update:model-value="onPickerUpdate"
        :support-scale-factor="usesTool ? hasScaleFactor : true"
        :support-resolution="usesTool ? hasUpscaleResolution : false"
        :scale-min="usesTool ? scaleFactorConstraints.min : 1"
        :scale-max="usesTool ? scaleFactorConstraints.max : 8"
        :scale-step="usesTool ? scaleFactorConstraints.step : 0.5"
        :scale-allowed-values="usesTool ? scaleFactorConstraints.allowedValues : null"
        :input-width="inputWidth"
        :input-height="inputHeight"
      />

      <!-- Everything else the tool declares ------------------------------- -->
      <div v-if="usesTool && tool" class="space-y-1.5">
        <SchemaParamGroup
          v-if="groupedGenericParams.length"
          :full-tool-id="tool.full_tool_id"
          :groups="groupedGenericParams"
          :values="output.params"
          flat
          @update:param="(name: string, value: any) => emit('setParams', { [name]: value })"
        />
        <p v-else-if="!showUpscalePicker" class="text-xs text-content-muted">
          This tool has no tunable settings.
        </p>
      </div>

      <!-- The picker already draws the before → after line, so this is only
           for a tool that declares no size control of its own. -->
      <template v-if="usesTool && !showUpscalePicker">
        <p class="text-xs font-mono text-content-tertiary tabular-nums">
          <template v-if="unchanged">Saves at {{ inputWidth }} × {{ inputHeight }}</template>
          <template v-else>
            {{ inputWidth }} × {{ inputHeight }} → {{ target.width }} × {{ target.height }}
          </template>
        </p>
      </template>
    </template>
  </div>
</template>
