<script setup lang="ts">
/**
 * The phone editor's sub-tool strip, pinned to the foot of the drawer.
 *
 * The desktop sub-bar puts a family's pickable things — Retouch's brushes,
 * Generate's verbs, Adjust's groups, Crop's aspects, Paint's engines — in a
 * chip row above its controls. On a phone those chips become this strip:
 * one horizontally scrolling row of labelled cells that stays visible at
 * every drawer height, so switching Heal to Clone is one tap and never a
 * navigation. Arming a selection tool swaps the row for the selection tools
 * (selection is workspace state, and its tools need the same reach).
 *
 * The strip only PICKS. Every control a pick reveals lives in the drawer
 * body above, rendered by the same sub-bar and inspectors as the desktop.
 */
import { computed, nextTick, ref, watch } from 'vue'
import Sheet from '../../components/ui/Sheet.vue'
import ToolIcon from './ToolIcon.vue'
import type { IconName } from '../ported/icons'
import { familyById, PAINT_ENGINES, SELECT_TOOLS } from '../stack/toolFamilies'
import type { FamilyId, SelectToolId } from '../stack/toolFamilies'
import {
  AUTO_EDITS, CREATIVE_LEVEL_EDITS, CROP_ASPECTS, PHOTOGRAPHIC_LEVEL_EDITS,
} from '../stack/adjustSections'

const props = defineProps<{
  family: FamilyId | null
  sub: string | null
  /** The sub-bar's state object: aspect, engine, looks, selection presence. */
  state: Record<string, any>
  /** An armed selection tool replaces the family's row with the selection tools. */
  armed: SelectToolId | null
}>()
const emit = defineEmits<{
  sub: [string]
  set: [Record<string, any>]
  arm: [SelectToolId]
}>()

interface Cell {
  id: string
  label: string
  icon?: IconName
  /** Crop aspects draw their own proportion instead of a named glyph. */
  aspect?: number | null
  active: boolean
  /** Selection cells light up in the selection color, not the accent. */
  selection?: boolean
  pick: () => void
}
type Item = Cell | 'sep'

const autoOpen = ref(false)

/** Generate's chip labels are sentences on desktop; the cells want one word. */
const SHORT: Record<string, string> = { remove: 'Remove', cutout: 'Cut out', repaint: 'Repaint', expand: 'Expand' }

const items = computed<Item[]>(() => {
  if (props.armed) {
    const cells = SELECT_TOOLS.map<Cell>(tool => ({
      id: tool.id,
      label: tool.label.replace(' gradient', ''),
      icon: tool.icon,
      active: props.armed === tool.id,
      selection: true,
      pick: () => emit('arm', tool.id),
    }))
    return [...cells.slice(0, 4), 'sep', ...cells.slice(4, 7), 'sep', ...cells.slice(7)]
  }
  const family = props.family
  if (!family) return []
  const spec = familyById(family)
  if (family === 'crop') {
    return CROP_ASPECTS.map<Cell>(preset => ({
      id: preset.id,
      label: preset.label,
      aspect: preset.ratio,
      active: props.state.cropAspect === preset.id,
      pick: () => emit('set', { cropAspect: preset.id }),
    }))
  }
  if (family === 'paint') {
    const engines = PAINT_ENGINES.map<Cell>(engine => ({
      id: engine.id,
      label: engine.label,
      icon: engine.icon,
      active: props.state.engineId === engine.id,
      pick: () => emit('set', { engineId: engine.id }),
    }))
    return [...engines, 'sep', {
      id: 'newLayer', label: 'New layer', icon: 'copy', active: false,
      pick: () => emit('set', { newLayer: true }),
    }]
  }
  if (family === 'levels') {
    const group = (edit: { id: string; label: string; icon: IconName }): Cell => ({
      id: edit.id,
      label: edit.id === 'point' ? 'Point' : edit.label,
      icon: edit.icon,
      active: false,
      pick: () => emit('set', { addLevel: edit.id }),
    })
    return [
      { id: 'auto', label: 'Auto', icon: 'histogram', active: autoOpen.value, pick: () => { autoOpen.value = true } },
      ...PHOTOGRAPHIC_LEVEL_EDITS.map(group),
      'sep',
      ...CREATIVE_LEVEL_EDITS.map(group),
      'sep',
      {
        id: 'looks', label: 'Looks', icon: 'image', active: !!props.state.looksOpen,
        pick: () => emit('set', { looksOpen: !props.state.looksOpen }),
      },
    ]
  }
  // Retouch, Generate, Annotate: the family's own sub-tools. With an
  // annotation selected the strip shows no armed tool: the body is that
  // shape's remote, and the next tap on the strip arms a tool again.
  const shapeSelected = family === 'annotate' && !!props.state.selectedShapeId
  const cells = spec.subTools.map<Cell>(tool => ({
    id: tool.id,
    label: SHORT[tool.id] ?? tool.label,
    icon: tool.icon,
    active: !shapeSelected && props.sub === tool.id,
    pick: () => emit('sub', tool.id),
  }))
  if (family === 'retouch') return [...cells.slice(0, 3), 'sep', ...cells.slice(3)]
  if (family === 'annotate') return [...cells.slice(0, 5), 'sep', ...cells.slice(5)]
  return cells
})

/** A crop aspect as the rectangle it makes; Free is the crop glyph, Original dashed. */
function aspectRect(ratio: number | null) {
  const r = ratio === null ? null : ratio === -1 ? 3 / 2 : ratio
  if (r === null) return null
  const w = r >= 1 ? 18 : 18 * r
  const h = r >= 1 ? 18 / r : 18
  return { x: 12 - w / 2, y: 12 - h / 2, width: w, height: h }
}

// The active cell stays in view when it changes under the user (a shape
// selection, a family entry that restores its last tool).
const rootEl = ref<HTMLElement | null>(null)
const activeId = computed(() => (items.value.find(item => item !== 'sep' && item.active) as Cell | undefined)?.id ?? null)
watch([activeId, () => props.family, () => props.armed], () => {
  void nextTick(() => {
    const el = rootEl.value?.querySelector<HTMLElement>('[aria-pressed="true"]')
    if (!el || !rootEl.value) return
    const cell = el.getBoundingClientRect()
    const row = rootEl.value.getBoundingClientRect()
    if (cell.left < row.left + 8 || cell.right > row.right - 8) {
      rootEl.value.scrollTo({ left: el.offsetLeft - (row.width - cell.width) / 2, behavior: 'smooth' })
    }
  })
}, { immediate: true })
</script>

<template>
  <div
    ref="rootEl"
    class="editor-tool-strip flex items-stretch gap-0.5 overflow-x-auto px-2 pt-1 pb-1.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    role="toolbar"
    :aria-label="armed ? 'Selection tools' : 'Tools'"
  >
    <template v-for="(item, index) in items" :key="item === 'sep' ? `sep-${index}` : item.id">
      <span v-if="item === 'sep'" class="w-px shrink-0 my-3 mx-1.5 bg-edge-strong" aria-hidden="true" />
      <button
        v-else
        type="button"
        class="flex-none min-w-[64px] h-[58px] px-1.5 rounded-lg flex flex-col items-center justify-center gap-1.5
               text-[11px] font-medium leading-none whitespace-nowrap border-none transition-colors
               focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
        :class="item.active
          ? (item.selection ? 'bg-selection/15 text-selection' : 'bg-accent/15 text-accent-hi')
          : 'bg-transparent text-content-secondary'"
        :aria-label="item.label"
        :aria-pressed="item.active"
        :data-strip-cell="item.id"
        @click="item.pick()"
      >
        <svg v-if="item.aspect !== undefined && aspectRect(item.aspect)" viewBox="0 0 24 24" class="w-[22px] h-[22px]" fill="none" stroke="currentColor" stroke-width="1.5">
          <rect v-bind="aspectRect(item.aspect)!" rx="1.5" :stroke-dasharray="item.aspect === -1 ? '3 2' : undefined" />
        </svg>
        <ToolIcon v-else :name="item.icon ?? 'crop'" :size="22" />
        {{ item.label }}
      </button>
    </template>

    <!-- The Autos: three variants of one act, behind one cell. -->
    <Sheet :show="autoOpen" title="Automatic" @close="autoOpen = false">
      <button
        v-for="auto in AUTO_EDITS"
        :key="auto.id"
        type="button"
        class="sheet-row w-full text-left"
        @click="autoOpen = false; emit('set', { auto: auto.id })"
      >
        <ToolIcon :name="auto.icon" class="sheet-row-icon" :size="20" />
        <span class="flex-1">{{ auto.label }}</span>
      </button>
      <p v-if="state.hasSelection" class="px-4 pb-2 text-[12px] text-content-tertiary">
        Autos read the whole frame, so they apply to the whole image.
      </p>
    </Sheet>
  </div>
</template>
