<script setup lang="ts">
// The Assets browser's second row, under the unchanged FilterBar: how the
// results are laid out. Left: Group by (the Select trigger and its menu) and
// the group count. Right: thumbnail size and the ⋯ menu (expand or collapse
// every group). Filters and sort stay in the FilterBar row above.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { CheckIcon } from '@heroicons/vue/24/outline'
import Select from '../ui/Select.vue'
import OverflowButton from '../ui/OverflowButton.vue'
import Tooltip from '../ui/Tooltip.vue'
import TileSizeSlider from './TileSizeSlider.vue'
import { consumeEscape, isTopmostEscapeLayer } from '../../utils/escapeLayers'
import { GROUP_BY_OPTIONS, groupByTriggerLabel, type GroupBy } from '../../utils/browseGrouping'

const props = defineProps<{
  groupBy: GroupBy
  /** Groups on screen, or null while there are none to count. */
  groupCount: number | null
  /** Why grouping can't apply right now (similarity search, random order). */
  unavailableReason?: string | null
}>()
const tileMin = defineModel<number>('tileMin', { required: true })
const emit = defineEmits<{
  'update:groupBy': [GroupBy]
  'expand-all': []
  'collapse-all': []
}>()

const openMenu = ref<'group' | 'more' | null>(null)
const groupMenuRoot = ref<HTMLElement | null>(null)
const moreMenuRoot = ref<HTMLElement | null>(null)
const groupMenu = ref<HTMLElement | null>(null)
const moreMenu = ref<HTMLElement | null>(null)

const disabled = computed(() => !!props.unavailableReason)
const triggerLabel = computed(() => (disabled.value ? 'No grouping' : groupByTriggerLabel(props.groupBy)))
const grouped = computed(() => !disabled.value && props.groupBy !== 'none')
const countText = computed(() => {
  if (!grouped.value || props.groupCount == null) return ''
  return `${props.groupCount} ${props.groupCount === 1 ? 'group' : 'groups'}`
})

function toggle(menu: 'group' | 'more') {
  openMenu.value = openMenu.value === menu ? null : menu
}

function pickGroupBy(value: GroupBy) {
  openMenu.value = null
  if (value !== props.groupBy) emit('update:groupBy', value)
}

function act(action: 'expand-all' | 'collapse-all') {
  openMenu.value = null
  if (action === 'expand-all') emit('expand-all')
  else emit('collapse-all')
}

function onDocumentPointer(event: Event) {
  const target = event.target as Node | null
  if (!openMenu.value || !target) return
  if (groupMenuRoot.value?.contains(target) || moreMenuRoot.value?.contains(target)) return
  openMenu.value = null
}

function onDocumentKey(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !openMenu.value) return
  const layer = openMenu.value === 'group' ? groupMenu.value : moreMenu.value
  if (!isTopmostEscapeLayer(layer)) return
  consumeEscape(event)
  openMenu.value = null
}

onMounted(() => {
  document.addEventListener('mousedown', onDocumentPointer)
  document.addEventListener('keydown', onDocumentKey, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocumentPointer)
  document.removeEventListener('keydown', onDocumentKey, true)
})

const menuClass = 'absolute top-full z-menu mt-1 min-w-[190px] rounded-lg border border-edge-subtle bg-surface py-1 shadow-lg'
const rowClass = 'flex w-full items-center gap-2 px-3 py-1.5 text-left text-ctl text-content-secondary transition-colors duration-150 hover:bg-overlay-subtle hover:text-content focus-visible:outline-none focus-visible:bg-overlay-subtle'
</script>

<template>
  <div class="flex min-h-11 flex-none flex-wrap items-center gap-x-3 gap-y-1 border-b border-edge-subtle bg-base px-page py-1.5 compact:min-h-12 compact:py-0">
    <div ref="groupMenuRoot" class="relative -ml-3 flex items-center">
      <Tooltip v-if="disabled" :text="unavailableReason || ''">
        <Select :label="triggerLabel" disabled :aria-description="unavailableReason || undefined" />
      </Tooltip>
      <Select v-else :label="triggerLabel" :open="openMenu === 'group'" data-testid="browse-group-by" @click="toggle('group')" />
      <div v-if="openMenu === 'group'" ref="groupMenu" data-escape-layer role="listbox" aria-label="Group by" :class="[menuClass, 'left-0']">
        <button
          v-for="option in GROUP_BY_OPTIONS"
          :key="option.value"
          type="button"
          role="option"
          :aria-selected="option.value === groupBy"
          :class="rowClass"
          @click="pickGroupBy(option.value)"
        >
          <span class="flex w-icon-nav flex-none justify-center">
            <CheckIcon v-if="option.value === groupBy" class="h-icon-inline w-icon-inline text-accent-hi" aria-hidden="true" />
          </span>
          <span class="flex-1" :class="option.value === groupBy ? 'text-content' : ''">{{ option.label }}</span>
        </button>
      </div>
    </div>
    <span v-if="countText" class="font-mono text-xs tabular-nums text-content-tertiary">{{ countText }}</span>
    <span class="flex-1"></span>
    <TileSizeSlider v-model="tileMin" class="compact:hidden" />
    <div v-if="grouped" ref="moreMenuRoot" class="relative -mr-2 coarse:-mr-3">
      <OverflowButton size="lg" label="View options" :aria-expanded="openMenu === 'more'" @click="toggle('more')" />
      <div v-if="openMenu === 'more'" ref="moreMenu" data-escape-layer role="menu" :class="[menuClass, 'right-0']">
        <button type="button" role="menuitem" :class="rowClass" @click="act('expand-all')">Expand all groups</button>
        <button type="button" role="menuitem" :class="rowClass" @click="act('collapse-all')">Collapse all groups</button>
      </div>
    </div>
  </div>
</template>
