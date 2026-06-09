<template>
  <div
    :class="[
      'relative rounded-lg border bg-overlay-faint transition-colors',
      incompatible ? 'border-amber-500/50' : 'border-edge-subtle',
      dragging ? 'opacity-30' : '',
    ]"
  >
    <!-- Accent rail (3px inset) echoing the step type color -->
    <div
      :class="[
        'absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r',
        step.kind === 'tool' ? 'bg-purple-500/70' : 'bg-white/20',
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

      <!-- Type icon: purple square = STP tool, neutral = built-in filter -->
      <div
        :class="[
          'w-[30px] h-[30px] rounded-md flex items-center justify-center flex-shrink-0',
          step.kind === 'tool' ? 'bg-purple-500/15 text-purple-400' : 'bg-white/[0.06] text-content-tertiary',
        ]"
      >
        <svg v-if="step.kind === 'tool'" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
          <path fill-rule="evenodd" d="M14.5 10a4.5 4.5 0 004.284-5.882c-.105-.324-.51-.391-.752-.15L15.34 6.66a.454.454 0 01-.493.11 3.01 3.01 0 01-1.618-1.616.455.455 0 01.11-.494l2.694-2.692c.24-.241.174-.647-.15-.752a4.5 4.5 0 00-5.873 4.575c.055.873-.128 1.808-.8 2.368l-7.23 6.024a2.724 2.724 0 103.837 3.837l6.024-7.23c.56-.672 1.495-.855 2.368-.8.096.007.193.01.291.01zM5 16a1 1 0 11-2 0 1 1 0 012 0z" clip-rule="evenodd" />
        </svg>
        <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
          <path d="M10 3.75a2 2 0 10-4 0 2 2 0 004 0zM17.25 4.5a.75.75 0 000-1.5h-5.5a.75.75 0 000 1.5h5.5zM5 3.75a.75.75 0 01-.75.75h-1.5a.75.75 0 010-1.5h1.5a.75.75 0 01.75.75zM4.25 17a.75.75 0 000-1.5h-1.5a.75.75 0 000 1.5h1.5zM17.25 17a.75.75 0 000-1.5h-5.5a.75.75 0 000 1.5h5.5zM9 10a.75.75 0 01-.75.75h-5.5a.75.75 0 010-1.5h5.5A.75.75 0 019 10zM17.25 10.75a.75.75 0 000-1.5h-1.5a.75.75 0 000 1.5h1.5zM14 16.25a2 2 0 10-4 0 2 2 0 004 0zM10 8a2 2 0 114 0 2 2 0 01-4 0z" />
        </svg>
      </div>

      <!-- Name + one-line summary -->
      <button
        type="button"
        class="flex-1 min-w-0 text-left"
        @click="$emit('toggle-expanded')"
      >
        <div class="text-sm font-medium text-content truncate flex items-center gap-1.5">
          {{ title }}
          <span v-if="unavailable" class="text-[10px] font-medium text-amber-500 uppercase tracking-wide">unavailable</span>
        </div>
        <div class="text-xs text-content-muted truncate mt-0.5">
          <template v-if="incompatible">
            <span class="text-amber-500">Needs {{ neededInput }} input — will be skipped</span>
          </template>
          <template v-else>{{ summary }}</template>
        </div>
      </button>

      <!-- Output thumbnail (when the step has run) -->
      <MediaImage
        v-if="thumbMediaId"
        :media-id="thumbMediaId"
        :thumbnail="true"
        :size="128"
        class="w-[34px] h-[34px] rounded-md object-cover flex-shrink-0"
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
        <div class="relative w-7 h-4 bg-surface-hover peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-3 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-blue-600"></div>
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

    <!-- Expanded settings (in place) -->
    <div v-if="expanded" class="border-t border-edge-subtle px-3 py-2">
      <slot name="settings"></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive } from 'vue'
import ActionMenu from '../../ActionMenu.vue'
import MediaImage from '../../media/MediaImage.vue'
import type { ChainStep } from '../../../utils/postProcessingChain'

const props = defineProps<{
  step: ChainStep
  title: string
  summary: string
  expanded: boolean
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
