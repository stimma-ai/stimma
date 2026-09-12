<script setup lang="ts">
/**
 * The phone editor's row: one line of cells that drills down in place
 * (DESIGN.md §3.6a). At the root it is the six families and Edits. Inside a
 * family the same row becomes ‹ and that family's pickable things — Retouch's
 * brushes, Generate's verbs, Adjust's groups, Crop's aspects and turns,
 * Paint's engines — so switching tools is one tap and never a navigation.
 * While a selection tool is armed the row is ‹ and the selection tools.
 *
 * The row only PICKS. Every control a pick reveals lives in the deck panel
 * above it.
 */
import { computed, nextTick, ref, watch } from 'vue'
import ToolIcon from './ToolIcon.vue'
import type { IconName } from '../ported/icons'
import { familyById, PAINT_ENGINES, SELECT_TOOLS, TOOL_FAMILIES } from '../stack/toolFamilies'
import type { FamilyId, SelectToolId } from '../stack/toolFamilies'
import { CREATIVE_LEVEL_EDITS, CROP_ASPECTS, PHOTOGRAPHIC_LEVEL_EDITS } from '../stack/adjustSections'
import { sanitizeSvg } from '../../utils/sanitizeHtml'

const props = defineProps<{
  family: FamilyId | null
  sub: string | null
  /** The sub-bar's state object: aspect, engine, flips, selection presence. */
  state: Record<string, any>
  /** An armed selection tool replaces the family's row with the selection tools. */
  armed: SelectToolId | null
  /** Root row: how many steps the stack holds, as the Edits cell's badge. */
  count?: number
  /** Adjust: the section of the selected step, so its group reads as the open one. */
  activeLevel?: string | null
  /** Adjust: the Looks strip is what the panel shows. */
  looks?: boolean
  /** Adjust: the Autos are what the panel shows. */
  auto?: boolean
}>()
const emit = defineEmits<{
  family: [FamilyId]
  edits: []
  back: []
  sub: [string]
  set: [Record<string, any>]
  arm: [SelectToolId]
}>()

interface Cell {
  id: string
  label: string
  icon?: IconName
  svg?: string
  aspect?: number | null
  active: boolean
  /** Selection cells light up in the selection color, not the accent. */
  selection?: boolean
  /** A dot: this group has a step with values. */
  modified?: boolean
  badge?: number
  pick: () => void
}
type Item = Cell | 'sep'

const PHONE_ORDER: FamilyId[] = ['crop', 'retouch', 'generate', 'levels', 'annotate', 'paint']
const SHORT: Record<string, string> = { remove: 'Remove', cutout: 'Cut out', repaint: 'Repaint', expand: 'Expand' }
const STACK_ICON = sanitizeSvg(
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 3 3 8l9 5 9-5-9-5z"/><path d="M3 13l9 5 9-5"/><path d="M3 17.5 12 22l9-4.5"/>
  </svg>`
)
const familySvg = Object.fromEntries(TOOL_FAMILIES.map(f => [f.id, sanitizeSvg(
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${f.icon}</svg>`
)]))

const level = computed<'root' | 'family' | 'selection'>(() => props.armed ? 'selection' : props.family ? 'family' : 'root')

const items = computed<Item[]>(() => {
  if (props.armed) {
    const cells = SELECT_TOOLS.map<Cell>(tool => ({
      id: tool.id, label: tool.label.replace(' gradient', ''), icon: tool.icon,
      active: props.armed === tool.id, selection: true, pick: () => emit('arm', tool.id),
    }))
    return [...cells.slice(0, 4), 'sep', ...cells.slice(4, 7), 'sep', ...cells.slice(7)]
  }
  const family = props.family
  if (!family) {
    return [
      ...PHONE_ORDER.map<Cell>(id => ({ id, label: familyById(id).label, svg: familySvg[id], active: false, pick: () => emit('family', id) })),
      'sep',
      { id: 'edits', label: 'Edits', svg: STACK_ICON, active: false, badge: props.count, pick: () => emit('edits') },
    ]
  }
  const spec = familyById(family)
  if (family === 'crop') {
    return [
      ...CROP_ASPECTS.map<Cell>(preset => ({ id: preset.id, label: preset.label, aspect: preset.ratio, active: props.state.cropAspect === preset.id, pick: () => emit('set', { cropAspect: preset.id }) })),
      'sep',
      { id: 'turn', label: 'Rotate', icon: 'rotateCcw', active: false, pick: () => emit('set', { rotateQuarter: true }) },
      { id: 'flipX', label: 'Flip H', icon: 'flipHorizontal', active: !!props.state.flipX, pick: () => emit('set', { flipX: !props.state.flipX }) },
      { id: 'flipY', label: 'Flip V', icon: 'flipVertical', active: !!props.state.flipY, pick: () => emit('set', { flipY: !props.state.flipY }) },
    ]
  }
  if (family === 'paint') {
    return [
      ...PAINT_ENGINES.map<Cell>(engine => ({ id: engine.id, label: engine.label, icon: engine.icon, active: props.state.engineId === engine.id, pick: () => emit('set', { engineId: engine.id }) })),
      'sep',
      { id: 'newLayer', label: 'New layer', icon: 'copy', active: false, pick: () => emit('set', { newLayer: true }) },
    ]
  }
  if (family === 'levels') {
    const group = (edit: { id: string; label: string; icon: IconName }): Cell => ({
      id: edit.id, label: edit.id === 'point' ? 'Point' : edit.label, icon: edit.icon,
      active: !props.looks && !props.auto && props.activeLevel === edit.id,
      modified: props.state.modifiedSections?.includes(edit.id) ?? false,
      pick: () => emit('sub', edit.id),
    })
    return [
      { id: 'auto', label: 'Auto', icon: 'histogram', active: !!props.auto, pick: () => emit('sub', 'auto') },
      ...PHOTOGRAPHIC_LEVEL_EDITS.map(group),
      'sep',
      ...CREATIVE_LEVEL_EDITS.map(group),
      'sep',
      { id: 'looks', label: 'Looks', icon: 'image', active: !!props.looks, modified: (props.state.appliedLookIds?.length ?? 0) > 0, pick: () => emit('sub', 'looks') },
    ]
  }
  const shapeSelected = family === 'annotate' && !!props.state.selectedShapeId
  const cells = spec.subTools.map<Cell>(tool => ({
    id: tool.id, label: SHORT[tool.id] ?? tool.label, icon: tool.icon,
    active: !shapeSelected && props.sub === tool.id, pick: () => emit('sub', tool.id),
  }))
  if (family === 'retouch') return [...cells.slice(0, 3), 'sep', ...cells.slice(3)]
  if (family === 'annotate') return [...cells.slice(0, 5), 'sep', ...cells.slice(5)]
  return cells
})

function aspectRect(ratio: number | null) {
  const r = ratio === null ? null : ratio === -1 ? 3 / 2 : ratio
  if (r === null) return null
  const w = r >= 1 ? 18 : 18 * r
  const h = r >= 1 ? 18 / r : 18
  return { x: 12 - w / 2, y: 12 - h / 2, width: w, height: h }
}

const rootEl = ref<HTMLElement | null>(null)
const activeId = computed(() => (items.value.find(item => item !== 'sep' && item.active) as Cell | undefined)?.id ?? null)
watch([activeId, () => props.family, () => props.armed], () => {
  void nextTick(() => {
    const row = rootEl.value
    if (!row) return
    const el = row.querySelector<HTMLElement>('[aria-pressed="true"]')
    if (!el) { row.scrollTo({ left: 0 }); return }
    const cell = el.getBoundingClientRect()
    const r = row.getBoundingClientRect()
    if (cell.left < r.left + 8 || cell.right > r.right - 8) {
      row.scrollTo({ left: el.offsetLeft - (r.width - cell.width) / 2, behavior: 'smooth' })
    }
  })
}, { immediate: true })
</script>

<template>
  <div
    ref="rootEl"
    class="editor-tool-strip flex items-stretch gap-0.5 h-[60px] overflow-x-auto pt-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    :class="level === 'root' ? 'px-1 justify-between' : 'px-1.5'"
    role="toolbar"
    :aria-label="level === 'root' ? 'Editor families' : level === 'selection' ? 'Selection tools' : 'Tools'"
    :data-level="level"
  >
    <!-- The way up: always the same cell in the same place, one level at a
         time. A selection level is a level too, so it leaves the same way. -->
    <button
      v-if="level !== 'root'"
      type="button"
      class="flex-none min-w-11 min-h-[56px] flex items-center justify-center border-none bg-transparent border-r border-edge-strong pr-2 mr-1"
      :class="level === 'selection' ? 'text-selection' : 'text-content-secondary'"
      aria-label="Back"
      @click="emit('back')"
    >
      <ToolIcon name="chevronLeft" :size="24" />
    </button>

    <template v-for="(item, index) in items" :key="item === 'sep' ? `sep-${index}` : item.id">
      <span v-if="item === 'sep'" class="w-px shrink-0 my-3.5 mx-1 bg-edge-strong" aria-hidden="true" />
      <button
        v-else
        type="button"
        class="relative min-h-[56px] px-1 rounded-md flex flex-col items-center justify-center gap-1
               text-[10.5px] font-medium leading-none whitespace-nowrap border-none bg-transparent transition-colors
               focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
        :class="[
          level === 'root' ? 'flex-1 min-w-0' : 'flex-none min-w-[58px]',
          item.active ? (item.selection ? 'text-selection' : 'text-accent-hi') : 'text-content-secondary',
          item.id === 'edits' && 'text-selection',
        ]"
        :aria-label="item.label"
        :aria-pressed="item.active"
        :data-strip-cell="item.id"
        @click="item.pick()"
      >
        <span v-if="item.svg" class="w-[22px] h-[22px] shrink-0" v-html="item.svg" />
        <svg v-else-if="item.aspect !== undefined && aspectRect(item.aspect)" viewBox="0 0 24 24" class="w-[22px] h-[22px]" fill="none" stroke="currentColor" stroke-width="1.5">
          <rect v-bind="aspectRect(item.aspect)!" rx="1.5" :stroke-dasharray="item.aspect === -1 ? '3 2' : undefined" />
        </svg>
        <ToolIcon v-else :name="item.icon ?? 'crop'" :size="22" />
        {{ item.label }}
        <span v-if="item.modified && !item.active" class="absolute top-1.5 right-2 w-1.5 h-1.5 rounded-full bg-accent" aria-hidden="true" />
        <span
          v-if="item.badge"
          class="absolute top-0.5 left-[calc(50%+5px)] min-w-[15px] h-[15px] px-1 rounded-full bg-selection text-base text-[9.5px] font-mono font-semibold flex items-center justify-center"
          aria-hidden="true"
        >{{ item.badge }}</span>
      </button>
    </template>
  </div>
</template>
