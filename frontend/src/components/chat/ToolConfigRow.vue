<template>
  <div
    class="group px-3 py-2 hover:bg-overlay-faint transition-colors"
    :class="showBorder ? 'border-b border-edge' : ''"
  >
    <!-- Main row: tool info + controls -->
    <div class="flex items-center gap-2">
      <!-- Tool info (takes up available space) -->
      <div class="flex-1 min-w-0">
        <div class="text-[13px] text-content leading-snug truncate">{{ tool.name }}</div>
        <div
          class="text-[11px] leading-tight truncate mt-0.5"
          :class="isStimmaCloud ? 'stimma-cloud-text' : 'text-content-muted'"
        >
          {{ tool.provider_name }}
        </div>
      </div>

      <!-- Controls (fixed width) -->
      <div class="flex items-center gap-1 flex-shrink-0">
        <!-- State toggle -->
        <div class="flex items-center gap-0.5 bg-overlay-subtle rounded-md p-0.5">
          <button
            @click="setState('denied')"
            :class="[
              'h-6 px-2 flex items-center justify-center rounded transition-colors text-[11px] font-medium',
              currentState === 'denied'
                ? 'bg-red-500/15 text-red-500'
                : 'text-content-muted hover:text-content-tertiary hover:bg-overlay-subtle'
            ]"
            title="Deny tool"
          >
            Deny
          </button>
          <button
            v-if="showNeutral"
            @click="setState('neutral')"
            :class="[
              'h-6 px-2 flex items-center justify-center rounded transition-colors text-[11px] font-medium',
              currentState === 'neutral'
                ? 'bg-zinc-500/20 text-content-secondary'
                : 'text-content-muted hover:text-content-tertiary hover:bg-overlay-subtle'
            ]"
            title="Ask first (neutral)"
          >
            Ask
          </button>
          <button
            @click="setState('allowed')"
            :class="[
              'h-6 px-2 flex items-center justify-center rounded transition-colors text-[11px] font-medium',
              currentState === 'allowed'
                ? 'bg-green-500/15 text-green-500'
                : 'text-content-muted hover:text-content-tertiary hover:bg-overlay-subtle'
            ]"
            title="Allow tool"
          >
            Allow
          </button>
        </div>

        <!-- Remove button -->
        <button
          @click="$emit('remove')"
          class="w-6 h-6 flex items-center justify-center rounded text-content-muted hover:text-red-500 hover:bg-red-500/10 transition-colors opacity-0 group-hover:opacity-100"
          title="Remove from list"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ProviderTool } from '../../composables/useProvidersApi'
import type { ToolConfig } from '../../composables/useAgentPresetsApi'
import { isStimmaCloudTool } from '../../utils/stimmaCloud'

type ToolState = 'neutral' | 'allowed' | 'denied'

const props = withDefaults(defineProps<{
  tool: ProviderTool
  config: ToolConfig | null
  showNeutral?: boolean
  showBorder?: boolean
}>(), {
  showNeutral: true,
  showBorder: false,
})

const emit = defineEmits<{
  (e: 'update:config', config: ToolConfig): void
  (e: 'remove'): void
}>()

// Computed
const isStimmaCloud = computed(() => {
  return isStimmaCloudTool(props.tool)
})

const currentState = computed((): ToolState => {
  const toolId = props.tool.full_tool_id
  if (props.config?.denied_tools?.includes(toolId)) return 'denied'
  if (props.config?.allowed_tools?.includes(toolId)) return 'allowed'
  return 'neutral'
})

function getUpdatedConfig(): ToolConfig {
  const toolId = props.tool.full_tool_id
  const allowed = [...(props.config?.allowed_tools || [])]
  const denied = [...(props.config?.denied_tools || [])]

  return {
    allowed_tools: allowed.filter(id => id !== toolId),
    denied_tools: denied.filter(id => id !== toolId),
  }
}

function setState(state: ToolState) {
  const toolId = props.tool.full_tool_id
  const config = getUpdatedConfig()

  if (state === 'allowed') {
    config.allowed_tools.push(toolId)
  } else if (state === 'denied') {
    config.denied_tools.push(toolId)
  }
  // neutral: remove from both lists (already done in getUpdatedConfig)

  emit('update:config', config)
}
</script>
