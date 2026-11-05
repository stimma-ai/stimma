<script setup lang="ts">
// The one collapsed-row grammar of a tool's form sections (reference images,
// LoRAs, post-processing, advanced settings; DESIGN.md §3.3): label at the left,
// a quiet mono state at the right edge, then either a labelled "Add" (the row
// adds something) or the one caret (the row discloses). One row height (32px,
// 44px on touch) and one state alignment. Sections sit `mb-3` apart
// (`coarse:mb-2`).
import { ref } from 'vue'
import { PlusIcon } from '@heroicons/vue/24/outline'
import Caret from '../ui/Caret.vue'

defineProps<{
  label: string
  /** Quiet mono state: `None`, `2 on`, `3 steps`, `4 settings`, `0/10`. */
  state?: string
  /** Shows the labelled Add action. */
  addable?: boolean
  addTitle?: string
  /** Makes the whole row a disclosure button with the one caret. */
  disclosure?: boolean
  open?: boolean
}>()
const emit = defineEmits<{ add: [event: MouseEvent]; toggle: [] }>()

const addEl = ref<HTMLElement | null>(null)
defineExpose({ addEl })
</script>

<template>
  <component
    :is="disclosure ? 'button' : 'div'"
    :type="disclosure ? 'button' : undefined"
    :aria-expanded="disclosure ? open : undefined"
    class="flex min-h-8 w-full items-center gap-2 text-left coarse:min-h-11"
    :class="disclosure ? 'rounded-md transition-colors duration-150 hover:text-content focus-visible:outline-none focus-visible:ring-2 ring-accent/60' : ''"
    @click="disclosure && emit('toggle')"
  >
    <span class="text-ctl font-semibold text-content-secondary">{{ label }}</span>
    <slot name="label-extra" />
    <div class="ml-auto flex items-center gap-1.5" :class="disclosure ? '' : '-mr-2'">
      <span v-if="state" class="font-mono text-xs font-normal tabular-nums text-content-tertiary">{{ state }}</span>
      <button
        v-if="addable"
        ref="addEl"
        type="button"
        class="inline-flex h-6 items-center gap-1 rounded-md px-2 text-xs text-content-secondary transition-colors duration-150 hover:bg-overlay-subtle hover:text-content focus-visible:outline-none focus-visible:ring-2 ring-accent/60 coarse:min-h-11"
        :title="addTitle"
        :aria-label="addTitle"
        @click.stop="emit('add', $event)"
      >
        <PlusIcon class="h-icon-inline w-icon-inline" aria-hidden="true" />
        Add
      </button>
      <Caret v-if="disclosure" :open="open" class="text-content-muted" />
      <slot name="trailing" />
    </div>
  </component>
</template>
