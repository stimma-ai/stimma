<template>
  <!-- STP tool step: host the tool's WHOLE parameter schema inline -->
  <div v-if="step.kind === 'tool'">
    <div v-if="!stepTool && toolLoadFailed" class="text-xs text-amber-500 py-1">
      This tool is not available right now. Its saved settings are kept and will apply when it returns.
    </div>
    <div v-else-if="!stepTool" class="text-xs text-content-muted py-1">Loading tool schema…</div>
    <template v-else>
      <!-- Prompt (img2img refine steps care about it) -->
      <div v-if="hasPrompt" class="px-1 py-2">
        <div class="text-sm font-medium text-content mb-2">Prompt</div>
        <textarea v-no-autocorrect
          :value="step.settings.prompt ?? ''"
          @input="updateSetting('prompt', ($event.target as HTMLTextAreaElement).value)"
          rows="2"
          :placeholder="promptPlaceholder"
          class="w-full px-2 py-1.5 bg-base border border-edge rounded text-content text-sm resize-y focus:outline-none focus:border-blue-500 font-sans"
        ></textarea>
      </div>
      <SchemaParamGroup
        :groups="groupedGenericParams"
        :values="step.settings"
        @update:param="updateSetting"
      />
      <div v-if="!groupedGenericParams.length && !hasPrompt" class="text-xs text-content-muted py-1">
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
import SchemaParamGroup from '../SchemaParamGroup.vue'
import SettingsDropdown from '../../ui/SettingsDropdown.vue'
import { useToolSchemaFeatures } from '../../../composables/useToolSchemaFeatures'
import { useProvidersApi, type ProviderTool } from '../../../composables/useProvidersApi'
import { getChainFilterDef } from '@stimma/image-editor'
import type { ChainStep } from '../../../utils/postProcessingChain'

const props = defineProps<{
  step: ChainStep
}>()

const emit = defineEmits<{
  (e: 'update:settings', settings: Record<string, any>): void
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
// get that tool's grouped params (the same renderer ToolView itself uses).
const { groupedGenericParams, hasPrompt, promptPlaceholder } = useToolSchemaFeatures({
  tool: stepTool,
  availableLoras: computed(() => []),
})

// --- Filter steps -----------------------------------------------------------

const filterParams = computed(() => {
  if (props.step.kind !== 'filter') return []
  return getChainFilterDef(props.step.filter_id || '')?.params ?? []
})
</script>
