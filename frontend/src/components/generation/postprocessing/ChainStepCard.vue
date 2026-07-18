<template>
  <!-- Atelier: a chain step is a hairline row, not a card. The 3px rail
       carries type identity; incompatible turns it amber (was a border). -->
  <div
    :class="[
      'relative border-b border-edge-subtle last:border-b-0 transition-colors',
      dragging ? 'opacity-30' : '',
    ]"
  >
    <div
      :class="[
        'absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r',
        incompatible ? 'bg-amber-500/70' : step.kind === 'tool' ? 'bg-purple-500/70' : 'bg-overlay-strong',
        step.enabled ? '' : 'opacity-40',
      ]"
    ></div>

    <div :class="['flex items-center gap-2.5 pl-3 pr-2.5 py-2', step.enabled ? '' : 'opacity-50']">
      <!-- Drag grip -->
      <span
        class="cursor-grab text-content-muted/40 hover:text-content-muted touch-none"
        draggable="true"
        @dragstart="$emit('grip-dragstart', $event)"
        @dragend="$emit('grip-dragend')"
        title="Drag to reorder"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
          <path d="M7 4a1 1 0 110-2 1 1 0 010 2zm6 0a1 1 0 110-2 1 1 0 010 2zM7 11a1 1 0 110-2 1 1 0 010 2zm6 0a1 1 0 110-2 1 1 0 010 2zM7 18a1 1 0 110-2 1 1 0 010 2zm6 0a1 1 0 110-2 1 1 0 010 2z" />
        </svg>
      </span>

      <!-- Type icon: standard task-type treatment for tools, neutral for filters -->
      <ToolIcon
        v-if="step.kind === 'tool'"
        :tool="{ id: step.tool_id, full_tool_id: step.tool_id, task_type: step.task_type }"
        size="md"
        :ring="false"
      />
      <div
        v-else
        class="w-[30px] h-[30px] rounded-md flex items-center justify-center flex-shrink-0 bg-overlay-light text-content-tertiary"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
          <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 1 1-3 0m3 0a1.5 1.5 0 1 0-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-9.75 0h9.75" />
        </svg>
      </div>

      <!-- Name + sub row (provider badge for tools, settings summary for filters) -->
      <button
        type="button"
        class="flex-1 min-w-0 text-left"
        @click="$emit('toggle-expanded')"
      >
        <div class="text-[13px] font-medium text-content truncate flex items-center gap-1.5">
          {{ title }}
          <span v-if="unavailable" class="text-[10px] font-medium text-amber-500">unavailable</span>
        </div>
        <div class="text-[11px] text-content-muted truncate mt-0.5 flex items-center gap-1.5">
          <template v-if="incompatible">
            <span class="text-amber-500">Needs {{ neededInput }} input — will be skipped</span>
          </template>
          <template v-else-if="step.kind === 'tool' && provider">
            <!-- Standard provider treatment (same as the sidebar): plain text,
                 gradient-colored for Stimma Cloud -->
            <span
              class="truncate text-[11px]"
              :class="provider.isStimmaCloud ? 'stimma-cloud-text font-medium' : 'text-content-muted'"
            >{{ provider.name }}</span>
          </template>
          <template v-else-if="step.kind === 'filter'">{{ summary }}</template>
        </div>
      </button>

      <!-- Output thumbnail (when the step has run) -->
      <MediaImage
        v-if="thumbMediaId"
        :media-id="thumbMediaId"
        :thumbnail="true"
        :size="128"
        class="w-[34px] h-[34px] rounded-media object-cover flex-shrink-0"
      />

      <!-- Expand chevron -->
      <button
        type="button"
        class="w-6 h-6 flex items-center justify-center rounded text-content-muted/60 hover:text-content-secondary transition-colors"
        @click="$emit('toggle-expanded')"
        :title="expanded ? 'Collapse' : 'Expand'"
      >
        <span :class="['transition-transform text-[10px]', expanded ? 'rotate-90' : '']">&#9654;</span>
      </button>

      <!-- Per-step enable toggle -->
      <label class="inline-flex items-center cursor-pointer flex-shrink-0" @click.stop>
        <input
          type="checkbox"
          :checked="step.enabled"
          @change="$emit('set-enabled', ($event.target as HTMLInputElement).checked)"
          class="sr-only peer"
        >
        <div class="relative w-7 h-4 bg-surface-hover peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-3 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-accent"></div>
      </label>

      <!-- Kebab → Remove -->
      <div class="relative flex-shrink-0">
        <button
          type="button"
          class="w-6 h-6 flex items-center justify-center rounded text-content-muted/50 hover:text-content-secondary transition-colors"
          @click.stop="onKebabClick"
          title="More options"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
            <path d="M10 3a1.5 1.5 0 110 3 1.5 1.5 0 010-3zM10 8.5a1.5 1.5 0 110 3 1.5 1.5 0 010-3zM11.5 15.5a1.5 1.5 0 10-3 0 1.5 1.5 0 003 0z" />
          </svg>
        </button>
        <ActionMenu
          v-if="menu.visible"
          :x="menu.x"
          :y="menu.y"
          :actions="menuActions"
          @close="menu.visible = false"
        />
      </div>
    </div>

    <!-- Expanded settings: the wash-inset disclosure (deepest containment) -->
    <div v-if="expanded" class="bg-overlay-faint rounded-md mx-1 mb-2 px-3 py-2">
      <slot name="settings"></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive } from 'vue'
import ActionMenu from '../../ActionMenu.vue'
import MediaImage from '../../media/MediaImage.vue'
import ToolIcon from '../../tools/ToolIcon.vue'
import type { ChainStep } from '../../../utils/postProcessingChain'

const props = defineProps<{
  step: ChainStep
  title: string
  summary: string
  expanded: boolean
  /** Standard provider treatment for the sub row (tool steps). */
  provider?: { name: string; isStimmaCloud: boolean } | null
  incompatible?: boolean
  neededInput?: string
  unavailable?: boolean
  dragging?: boolean
  thumbMediaId?: number | null
}>()

const emit = defineEmits<{
  (e: 'toggle-expanded'): void
  (e: 'set-enabled', enabled: boolean): void
  (e: 'remove'): void
  (e: 'grip-dragstart', ev: DragEvent): void
  (e: 'grip-dragend'): void
}>()

const menu = reactive({ visible: false, x: 0, y: 0 })

function onKebabClick(ev: MouseEvent) {
  menu.x = ev.clientX
  menu.y = ev.clientY
  menu.visible = true
}

const menuActions = computed(() => [
  {
    id: 'remove',
    label: 'Remove',
    danger: true,
    action: () => {
      menu.visible = false
      emit('remove')
    },
  },
])
</script>
