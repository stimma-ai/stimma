<template>
  <!-- STP tool step: host the tool's WHOLE parameter schema inline -->
  <div v-if="step.kind === 'tool'">
    <div v-if="!stepTool && toolLoadFailed" class="text-xs text-amber-500 py-1">
      This tool is not available right now. Its saved settings are kept and will apply when it returns.
    </div>
    <div v-else-if="!stepTool" class="text-xs text-content-muted py-1">Loading tool schema…</div>
    <template v-else>
      <!-- Prompt (img2img refine steps care about it) — the full AIPromptEditor,
           including its inline sparkle chat (no page-level chat dock exists in
           the step config panel, so external-chat stays off). -->
      <div v-if="hasPrompt" class="px-1 py-2">
        <div class="text-sm font-medium text-content mb-2">Prompt</div>
        <AIPromptEditor
          :model-value="step.settings.prompt ?? ''"
          @update:model-value="updateSetting('prompt', $event)"
          :rows="4"
          :prompt-options="step.promptOptions ?? defaultPromptOptions"
          @update:prompt-options="emit('update:promptOptions', $event)"
          :placeholder="promptPlaceholder"
        />
      </div>
      <!-- Upscale resolution (x-control: upscale_resolution) — same dedicated
           picker the tool gets standalone; stores scale_factor OR resolution. -->
      <UpscaleResolutionPicker
        v-if="showUpscalePicker"
        class="my-2"
        :model-value="upscalePickerValue"
        @update:model-value="onUpscalePickerUpdate"
        :support-scale-factor="showUpscalePicker"
        :support-resolution="showUpscalePicker"
        compact
      />

      <!-- Aspect ratio / image size / megapixels (dedicated controls in
           ToolView; rendered as simple rows here) -->
      <div v-if="hasAspectRatio && aspectRatioChoices.length" class="flex items-center justify-between gap-4 px-1 py-2">
        <div class="text-sm font-medium text-content">Aspect Ratio</div>
        <div class="min-w-0 max-w-[55%] flex-shrink-0">
          <SettingsDropdown
            :model-value="String(step.settings.aspect_ratio ?? schemaDefault('aspect_ratio') ?? aspectRatioChoices[0])"
            @update:model-value="updateSetting('aspect_ratio', $event)"
            :options="aspectRatioChoices.map((v: string) => ({ value: v, label: v }))"
          />
        </div>
      </div>
      <div v-if="imageSizeChoices.length" class="flex items-center justify-between gap-4 px-1 py-2">
        <div class="text-sm font-medium text-content">Image Size</div>
        <div class="min-w-0 max-w-[55%] flex-shrink-0">
          <SettingsDropdown
            :model-value="String(step.settings.image_size ?? schemaDefault('image_size') ?? imageSizeChoices[0])"
            @update:model-value="updateSetting('image_size', $event)"
            :options="imageSizeChoices.map((v: string) => ({ value: v, label: v }))"
          />
        </div>
      </div>
      <div v-if="hasMegapixels" class="flex items-center justify-between gap-4 px-1 py-2">
        <div class="text-sm font-medium text-content">Megapixels</div>
        <div class="flex min-w-0 w-[55%] max-w-[360px] flex-shrink-0 items-center justify-end gap-2">
          <input v-no-autocorrect
            type="range"
            :value="step.settings.megapixels ?? schemaDefault('megapixels') ?? 1"
            @input="updateSetting('megapixels', Number(($event.target as HTMLInputElement).value))"
            :min="schemaProp('megapixels')?.minimum ?? 0.25"
            :max="schemaProp('megapixels')?.maximum ?? 4"
            :step="schemaProp('megapixels')?.['x-step'] ?? 0.25"
            class="min-w-24 flex-1 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full"
          />
          <span class="w-10 flex-shrink-0 text-sm text-content-tertiary text-right select-none">
            {{ step.settings.megapixels ?? schemaDefault('megapixels') ?? 1 }}
          </span>
        </div>
      </div>

      <!-- Duration / FPS (dedicated controls in ToolView; simple rows here).
           Unset values display videoParamDefaults — the same prefill ToolView
           applies — so the panel shows exactly what the step will run with. -->
      <div v-if="hasDuration" class="flex items-center justify-between gap-4 px-1 py-2">
        <div class="text-sm font-medium text-content">Duration</div>
        <div v-if="allowedDurations" class="min-w-0 max-w-[55%] flex-shrink-0">
          <SettingsDropdown
            :model-value="String(step.settings.duration ?? videoParamDefaults.duration)"
            @update:model-value="updateSetting('duration', Number($event))"
            :options="allowedDurations.map((d: number) => ({ value: String(d), label: `${d}s` }))"
          />
        </div>
        <div v-else class="flex min-w-0 w-[55%] max-w-[360px] flex-shrink-0 items-center justify-end gap-2">
          <input v-no-autocorrect
            type="range"
            :value="step.settings.duration ?? videoParamDefaults.duration"
            @input="updateSetting('duration', Number(($event.target as HTMLInputElement).value))"
            :min="durationConfig.min"
            :max="durationConfig.max"
            :step="durationConfig.step"
            class="min-w-24 flex-1 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full"
          />
          <span class="w-10 flex-shrink-0 text-sm text-content-tertiary text-right select-none">
            {{ Number(step.settings.duration ?? videoParamDefaults.duration).toFixed(1) }}s
          </span>
        </div>
      </div>
      <div v-if="hasFps" class="flex items-center justify-between gap-4 px-1 py-2">
        <div class="text-sm font-medium text-content">FPS</div>
        <div class="min-w-0 max-w-[55%] flex-shrink-0">
          <SettingsDropdown
            :model-value="String(step.settings.fps ?? videoParamDefaults.fps ?? fpsOptions[0])"
            @update:model-value="updateSetting('fps', Number($event))"
            :options="fpsOptions.map((fps: number) => ({ value: String(fps), label: `${fps} fps` }))"
          />
        </div>
      </div>

      <SchemaParamGroup
        :groups="groupedGenericParams"
        :values="step.settings"
        flat
        disable-collapse
        @update:param="updateSetting"
      />
      <div v-if="!groupedGenericParams.length && !hasPrompt && !showUpscalePicker && !hasAspectRatio && !hasMegapixels && !hasDuration && !hasFps" class="text-xs text-content-muted py-1">
        This tool has no tunable settings.
      </div>
    </template>
  </div>

  <!-- Built-in filter step: the small fixed control set from the shared defs -->
  <div v-else class="divide-y divide-white/[0.06]">
    <template v-for="param in filterParams" :key="param.name">
      <!-- Enum -->
      <div v-if="param.type === 'enum'" class="flex items-center justify-between gap-4 px-1 py-2">
        <div class="text-sm font-medium text-content">{{ param.label }}</div>
        <div class="min-w-0 max-w-[55%] flex-shrink-0">
          <SettingsDropdown
            :model-value="String(step.settings[param.name] ?? param.default)"
            @update:model-value="updateSetting(param.name, $event)"
            :options="param.options || []"
          />
        </div>
      </div>
      <!-- Number slider -->
      <div v-else class="flex items-center justify-between gap-4 px-1 py-2">
        <div class="text-sm font-medium text-content">{{ param.label }}</div>
        <div class="flex min-w-0 w-[55%] max-w-[360px] flex-shrink-0 items-center justify-end gap-2">
          <input v-no-autocorrect
            type="range"
            :value="step.settings[param.name] ?? param.default"
            @input="updateSetting(param.name, Number(($event.target as HTMLInputElement).value))"
            :min="param.min ?? 0"
            :max="param.max ?? 100"
            :step="param.step ?? 1"
            class="min-w-24 flex-1 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full"
          />
          <span class="w-10 flex-shrink-0 text-sm text-content-tertiary text-right select-none">
            {{ step.settings[param.name] ?? param.default }}
          </span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AIPromptEditor from '../AIPromptEditor.vue'
import SchemaParamGroup from '../SchemaParamGroup.vue'
import SettingsDropdown from '../../ui/SettingsDropdown.vue'
import UpscaleResolutionPicker from '../UpscaleResolutionPicker.vue'
import { useToolSchemaFeatures } from '../../../composables/useToolSchemaFeatures'
import { useProvidersApi, type ProviderTool } from '../../../composables/useProvidersApi'
import { getChainFilterDef } from '@stimma/image-editor'
import { defaultChainStepPromptOptions, type ChainStep, type ChainStepPromptOptions } from '../../../utils/postProcessingChain'

// Fallback for steps saved before promptOptions existed — the same ToolView
// new-state defaults normalizeChain fills in (Enhance ON).
const defaultPromptOptions = defaultChainStepPromptOptions()

const props = defineProps<{
  step: ChainStep
}>()

const emit = defineEmits<{
  (e: 'update:settings', settings: Record<string, any>): void
  (e: 'update:promptOptions', value: ChainStepPromptOptions): void
}>()

function updateSetting(name: string, value: any) {
  emit('update:settings', { [name]: value })
}

// --- Tool steps: per-step schema features off the step's own tool ----------

const { getTool } = useProvidersApi()
const stepTool = ref<ProviderTool | null>(null)
const toolLoadFailed = ref(false)

watch(
  () => props.step.tool_id,
  async (toolId) => {
    stepTool.value = null
    toolLoadFailed.value = false
    if (props.step.kind !== 'tool' || !toolId) return
    try {
      stepTool.value = await getTool(toolId)
      if (!stepTool.value) toolLoadFailed.value = true
    } catch {
      toolLoadFailed.value = true
    }
  },
  { immediate: true },
)

// useToolSchemaFeatures accepts any tool ref — instantiate it per step tool to
// get that tool's grouped params and dedicated-control flags (the same
// schema-driven features ToolView itself uses).
const {
  groupedGenericParams,
  hasPrompt,
  promptPlaceholder,
  showUpscalePicker,
  hasAspectRatio,
  aspectRatioChoices,
  imageSizeChoices,
  hasMegapixels,
  hasDuration,
  durationConfig,
  allowedDurations,
  hasFps,
  fpsOptions,
  videoParamDefaults,
} = useToolSchemaFeatures({
  tool: stepTool,
  availableLoras: computed(() => []),
})

function schemaProp(name: string): any {
  return stepTool.value?.parameter_schema?.properties?.[name]
}

function schemaDefault(name: string): any {
  return schemaProp(name)?.default
}

// The upscale picker is a dedicated multi-mode control. In a chain step the
// input image isn't known at config time, so the step stores either
// scale_factor (relative — the executor resolves it against the actual input
// at run time) or resolution (short-edge px).
const upscalePickerValue = computed(() => ({
  resolutionMode: (props.step.settings.resolution != null ? 'pixels' : 'relative') as 'relative' | 'pixels',
  scaleFactor: props.step.settings.scale_factor ?? 2,
  targetResolution: props.step.settings.resolution ?? 1080,
}))

function onUpscalePickerUpdate(v: { resolutionMode: 'relative' | 'pixels'; scaleFactor: number; targetResolution: number }) {
  if (v.resolutionMode === 'relative') {
    emit('update:settings', { scale_factor: v.scaleFactor, resolution: undefined })
  } else {
    emit('update:settings', { resolution: v.targetResolution, scale_factor: undefined })
  }
}

// --- Filter steps -----------------------------------------------------------

const filterParams = computed(() => {
  if (props.step.kind !== 'filter') return []
  return getChainFilterDef(props.step.filter_id || '')?.params ?? []
})
</script>
