<script setup lang="ts">
// A multi-select filter trigger for the All tools header: the kit Select, and
// the options it opens. Wide: an inline dropdown under the trigger. Compact or
// coarse pointer: the kit Sheet (an inline dropdown converted to a sheet would
// sit inside the app column's stacking context, under the shared sheet
// backdrop, and no tap would ever reach it). Rows toggle and the menu stays
// open; groups are separated by a hairline and may carry a sentence-case label.
import { onBeforeUnmount, onMounted, ref, type Component } from 'vue'
import { CheckIcon } from '@heroicons/vue/24/outline'
import Select from '../ui/Select.vue'
import Sheet from '../ui/Sheet.vue'
import { useViewport } from '../../composables/useViewport'

export interface FilterOption {
  id: string
  label: string
  /** Draw the label in the Stimma Cloud gradient (the provider's own name). */
  cloud?: boolean
}
export interface FilterGroup {
  label?: string
  options: FilterOption[]
}

defineProps<{
  label: string
  /** Narrowing the list: the trigger takes the accent tint. */
  active: boolean
  /** Sheet title on compact. */
  title: string
  groups: FilterGroup[]
  selected: ReadonlySet<string>
  /** Glyph shown before the label on compact only. */
  icon?: Component
}>()

const emit = defineEmits<{ toggle: [id: string] }>()

const { isCompact, isCoarsePointer } = useViewport()
const asSheet = () => isCompact.value || isCoarsePointer.value

const open = ref(false)
const root = ref<HTMLElement | null>(null)

// The Sheet teleports to body (outside `root`) and dismisses itself; treating
// its taps as outside clicks would close it on every pick.
function onDocumentClick(event: MouseEvent) {
  if (!asSheet() && root.value && !root.value.contains(event.target as Node)) open.value = false
}
onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))
</script>

<template>
  <div ref="root" class="relative min-w-0">
    <Select :label="label" :open="open" :active="active" :caret="!isCompact" class="max-w-full" @click="open = !open">
      <template v-if="icon" #icon><component :is="icon" class="hidden h-icon-nav w-icon-nav flex-shrink-0 compact:block" /></template>
    </Select>

    <!-- Dropdown (wide) -->
    <div
      v-if="open && !asSheet()"
      class="absolute right-0 top-full z-menu mt-1 min-w-[190px] rounded-lg border border-edge-subtle bg-surface py-1 shadow-xl"
    >
      <template v-for="(group, index) in groups" :key="index">
        <div v-if="index > 0" class="my-1 border-t border-edge-subtle"></div>
        <div v-if="group.label" class="px-3 pb-1 pt-2 text-xs text-content-tertiary">{{ group.label }}</div>
        <button
          v-for="option in group.options"
          :key="option.id"
          type="button"
          class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-overlay-subtle"
          :class="selected.has(option.id) ? 'text-accent-hi' : 'text-content-secondary'"
          :aria-pressed="selected.has(option.id)"
          @click="emit('toggle', option.id)"
        >
          <CheckIcon v-if="selected.has(option.id)" class="h-icon-nav w-icon-nav flex-shrink-0" />
          <span v-else class="w-icon-nav flex-shrink-0"></span>
          <span :class="option.cloud ? 'stimma-cloud-text font-medium' : ''">{{ option.label }}</span>
        </button>
      </template>
    </div>

    <!-- Sheet (compact / coarse) -->
    <Sheet :show="open && asSheet()" :title="title" @close="open = false">
      <div class="pb-2">
        <template v-for="(group, index) in groups" :key="index">
          <div v-if="index > 0" class="mx-4 my-1 border-t border-edge-subtle"></div>
          <div v-if="group.label" class="px-4 pb-1 pt-3 text-xs text-content-tertiary">{{ group.label }}</div>
          <button
            v-for="option in group.options"
            :key="option.id"
            type="button"
            class="sheet-row"
            :class="selected.has(option.id) ? '!text-accent-hi' : ''"
            :aria-pressed="selected.has(option.id)"
            @click="emit('toggle', option.id)"
          >
            <CheckIcon v-if="selected.has(option.id)" class="sheet-row-icon" />
            <span v-else class="sheet-row-icon"></span>
            <span class="truncate" :class="option.cloud ? 'stimma-cloud-text font-medium' : ''">{{ option.label }}</span>
          </button>
        </template>
      </div>
    </Sheet>
  </div>
</template>
