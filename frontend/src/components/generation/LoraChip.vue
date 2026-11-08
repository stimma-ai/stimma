<template>
  <div
    :class="[
      'group flex items-start gap-1.5 py-1.5 border-b border-edge-subtle last:border-b-0 text-sm text-content select-none cursor-pointer transition-colors',
      'coarse:items-center coarse:min-h-11 coarse:py-0',
      unavailable ? 'opacity-60' : (item.enabled || owned) ? '' : 'opacity-50'
    ]"
    @pointerdown="onPointerDown"
    @click.stop="onClick"
    @contextmenu.stop.prevent="$emit('contextmenu', $event)"
  >
    <!-- Enable dot -->
    <div class="shrink-0 w-3 flex items-center justify-center mt-[5px] coarse:mt-0">
      <!-- The prompt owns this one: it's on when the prompt picks it, whatever its switch says -->
      <LockClosedIcon v-if="owned" class="w-3 h-3 text-selection" data-program-lock />
      <div v-else-if="item.enabled && !unavailable" class="w-2.5 h-2.5 rounded-full bg-accent-hi" />
      <div v-else class="w-2.5 h-2.5 rounded-full border border-content-muted" />
    </div>

    <!-- Name + secondary chips. On compact the chips wrap under the name
         rather than pushing it (and the weight) past the edge. -->
    <div class="flex-1 min-w-0" :title="unavailable ? item.lora + ' — not available for this tool' : item.lora">
      <div class="flex items-center gap-1 compact:flex-wrap compact:gap-y-0.5">
        <span :class="['truncate text-[13px] compact:max-w-full', unavailable ? 'line-through' : (item.enabled ? 'font-medium' : '')]">{{ displayName.primary }}</span>
        <span
          v-for="chip in secondaryChips"
          :key="chip"
          class="shrink-0 text-[9px] leading-none px-1 py-0.5 rounded bg-overlay-subtle text-content-tertiary font-mono"
        >{{ chip }}</span>
        <span
          v-if="owned"
          class="shrink-0 text-[9px] leading-none px-1 py-0.5 rounded bg-selection/15 text-selection font-mono uppercase"
          data-program-mark
          :title="`Your prompt decides when this is on (${programLabel})`"
        >set by prompt</span>
      </div>
      <div v-if="showRaw" class="font-mono text-[10px] text-content-muted truncate mt-0.5">
        {{ item.lora }}
      </div>
      <!-- Only rows that are on: the words this LoRA needs, or what's missing
           when the prompt goes out verbatim. -->
      <template v-if="(item.enabled || owned) && !unavailable && triggerWords.length">
        <div
          v-if="missingTrigger && !owned"
          class="mt-0.5 text-[11px] leading-snug text-amber-600 dark:text-amber-400"
          data-lora-trigger-warning
        >
          <span class="font-mono">{{ missingTrigger }}</span> isn't in your prompt ·
          <button
            type="button"
            class="font-semibold text-accent-hi coarse:min-h-11"
            @click.stop="$emit('insert-trigger', missingTrigger)"
            @pointerdown.stop
          >Insert</button>
        </div>
        <div v-else class="mt-0.5 truncate font-mono text-[11px] leading-snug text-content-tertiary" data-lora-trigger-line>
          {{ triggerWords.join(', ') }}
        </div>
      </template>
    </div>

    <!-- Notes: only for a row with a fingerprint. Stays visible once written. -->
    <button
      v-if="canHaveNote"
      @click.stop="$emit('toggle-note')"
      @pointerdown.stop
      type="button"
      :class="[
        'shrink-0 w-[18px] h-4 mt-[2px] flex items-center justify-center transition-opacity hover:text-content coarse:opacity-100 coarse:w-11 coarse:h-11 coarse:mt-0',
        noteOpen ? 'opacity-100 text-accent-hi' : hasNote ? 'opacity-100 text-content-secondary' : 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100 text-content-tertiary',
      ]"
      :title="hasNote ? 'Edit notes' : 'Add notes'"
      :aria-label="hasNote ? 'Edit notes' : 'Add notes'"
      :aria-expanded="noteOpen"
      data-lora-note-button
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" class="w-[13px] h-[13px]">
        <path d="M5 2.8h7l3.5 3.5v10.9H5z" />
        <path d="M12 2.8v3.5h3.5M7.8 10.2h4.8M7.8 13.3h4.8" />
      </svg>
    </button>

    <!-- Weight cluster: − value + (hover reveals the steppers), ✕ far right.
         The whole row drags (root pointerdown, mouse only); no grab handle
         needed. On coarse pointers there is no hover: the steppers go (the
         value opens its slider sheet on tap) and ✕ is always visible at
         touch size. -->
    <button
      @click.stop="decrementWeight"
      @pointerdown.stop
      type="button"
      class="shrink-0 w-4 h-4 mt-[2px] flex items-center justify-center text-[11px] text-content-tertiary hover:text-content opacity-0 group-hover:opacity-100 transition-opacity coarse:hidden"
    >−</button>
    <span @pointerdown.stop @click.stop class="shrink-0 mt-[2px] coarse:mt-0 coarse:min-h-11 coarse:px-1 coarse:flex coarse:items-center">
      <ScrubValue
        label="LoRA strength"
        :default-value="1"
        :model-value="item.weight"
        @update:model-value="emitWeight"
        :min="-10" :max="10" :step="0.05"
        :disabled="unavailable"
        :non-default="Math.abs(item.weight - 1) > 0.001"
        :format="(v: number) => v.toFixed(2)"
      />
    </span>
    <button
      @click.stop="incrementWeight"
      @pointerdown.stop
      type="button"
      class="shrink-0 w-4 h-4 mt-[2px] flex items-center justify-center text-[11px] text-content-tertiary hover:text-content opacity-0 group-hover:opacity-100 transition-opacity coarse:hidden"
    >+</button>
    <button
      @click.stop="$emit('remove')"
      @pointerdown.stop
      type="button"
      class="shrink-0 w-4 h-4 mt-[2px] flex items-center justify-center text-content-muted hover:!text-red-500 opacity-0 group-hover:opacity-100 transition-opacity [[data-pointer=coarse]_&]:opacity-100 coarse:w-11 coarse:h-11 coarse:mt-0 coarse:-mr-2"
      title="Remove"
      aria-label="Remove"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3">
        <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { LockClosedIcon } from '@heroicons/vue/24/outline'
import type { LoraPoolItem } from '../../composables/useLoraPool'
import { getDirectoryPath } from '../../composables/useLoraDisplayNames'
import ScrubValue from '../ui/ScrubValue.vue'
import type { LoraDisplayName } from '../../composables/useLoraDisplayNames'

interface Props {
  item: LoraPoolItem
  displayName: LoraDisplayName
  showRaw?: boolean
  groupId?: string | null
  unavailable?: boolean
  canHaveNote?: boolean
  hasNote?: boolean
  noteOpen?: boolean
  triggerWords?: string[]
  /** A trigger word the verbatim prompt doesn't contain, when Enhance is off. */
  missingTrigger?: string | null
  /** The prompt-program choice that picks this LoRA, when the prompt controls it. */
  programLabel?: string | null
}

const props = withDefaults(defineProps<Props>(), {
  showRaw: false,
  groupId: null,
  unavailable: false,
  canHaveNote: false,
  hasNote: false,
  noteOpen: false,
  triggerWords: () => [],
  missingTrigger: null,
  programLabel: null,
})

const emit = defineEmits<{
  (e: 'toggle', event: MouseEvent): void
  (e: 'update-weight', weight: number): void
  (e: 'remove'): void
  (e: 'contextmenu', event: MouseEvent): void
  (e: 'drag-intent', event: PointerEvent, loraPath: string, groupId: string | null): void
  (e: 'toggle-note'): void
  (e: 'insert-trigger', word: string): void
  (e: 'program', event: MouseEvent): void
}>()

/** The prompt chooses among this LoRA, so the prompt, not its switch, decides when it runs. */
const owned = computed(() => !!props.programLabel && !props.unavailable)

const directoryPath = computed(() => getDirectoryPath(props.item.lora))

const secondaryChips = computed(() => {
  if (props.unavailable) return [] // keep unavailable chips quiet — drop the V9/STEP pills
  if (!props.displayName.secondary) return []
  return props.displayName.secondary.split(' ').filter(Boolean)
})

const formattedWeight = computed(() => {
  return props.item.weight.toFixed(2)
})

function emitWeight(v: number) {
  emit('update-weight', Math.round(v * 100) / 100)
}

function incrementWeight() {
  const newWeight = Math.min(10, props.item.weight + 0.05)
  emit('update-weight', Math.round(newWeight * 100) / 100)
}

function decrementWeight() {
  const newWeight = Math.max(-10, props.item.weight - 0.05)
  emit('update-weight', Math.round(newWeight * 100) / 100)
}


// Drag: emit intent on pointerdown, parent decides when to start drag
const suppressClick = ref(false)

function onPointerDown(event: PointerEvent) {
  if (event.button !== 0) return // Left click only
  // Touch drag is not attempted (DESIGN.md §1.11): a finger on the row must
  // scroll the drawer, and a pointerdown we preventDefault'd would fight it.
  if (event.pointerType === 'touch') return
  event.preventDefault() // Prevent text selection during drag
  suppressClick.value = false
  emit('drag-intent', event, props.item.lora, props.groupId)
}

function onClick(event: MouseEvent) {
  if (suppressClick.value) {
    suppressClick.value = false
    return
  }
  // A LoRA the prompt owns opens the choice that picks it (pin it there): its own
  // switch doesn't apply while the prompt chooses among it.
  if (owned.value) {
    emit('program', event)
    return
  }
  emit('toggle', event)
}

// Called by parent to suppress the click after a drag
function markDragged() {
  suppressClick.value = true
}

defineExpose({ markDragged })
</script>
