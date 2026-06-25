<template>
  <!-- Stimma Cloud ring treatment (only when ring=true). -->
  <div
    v-if="isRing"
    class="cloud-grad shrink-0"
    :class="[outerSizeClass, ringPadClass]"
  >
    <div
      class="w-full h-full flex items-center justify-center text-content-secondary bg-surface-raised"
      :class="[innerRadiusClass, padClass]"
    >
      <div class="tool-mark w-full h-full" v-html="glyphSvg" />
    </div>
  </div>

  <!-- Bare mark: just the resolved glyph, no tile/border, sized to fill and
       tinted with currentColor. For dense dropdown rows that previously showed
       a bare stroke glyph. -->
  <div
    v-else-if="bare"
    class="tool-mark w-full h-full"
    v-html="glyphSvg"
  />

  <!-- Neutral tile. Mark/glyph = model identity. Source is conveyed elsewhere
       (e.g. the card border) when the ring is suppressed. -->
  <div
    v-else
    class="shrink-0 flex items-center justify-center text-content-secondary bg-surface-raised border border-edge-subtle"
    :class="[outerSizeClass, padClass]"
  >
    <div class="tool-mark w-full h-full" v-html="glyphSvg" />
  </div>
</template>

<script setup lang="ts">
/**
 * ToolIcon — the one shared tool icon. Two orthogonal axes:
 *   - Mark (inner glyph) = model identity: a vendor brand mark resolved from
 *     `model_vendor`, falling back to a task-generic glyph when there is no
 *     known mark.
 *   - Tile (background) = source: a Stimma Cloud gradient hairline ring vs a
 *     neutral tile. The ring can be suppressed via `ring=false` when the
 *     surrounding surface already conveys "Stimma Cloud" (e.g. a card border),
 *     to avoid stacking two cloud rims.
 *
 * Treatment, sizes, and glyphs mirror plans/icon-branding/mocks/tool-icons.html.
 */
import { computed } from 'vue'
import { isStimmaCloudTool } from '../../utils/stimmaCloud'
import { getModelMarkSvg } from './modelMarks'
import { getTaskTypeIconSvg } from '../../utils/taskTypeIcons'
import { sanitizeSvg } from '../../utils/sanitizeHtml'

type ToolLike = {
  id?: string
  full_tool_id?: string
  provider_id?: string
  model_vendor?: string | null
  task_type?: string | null
  task_types?: string[] | null
}

const props = withDefaults(
  defineProps<{
    tool: ToolLike
    size?: 'xl' | 'lg' | 'md' | 'sm' | 'xs'
    /** Force Stimma Cloud detection regardless of provider_id. */
    forceCloud?: boolean
    /** Draw the Stimma Cloud gradient ring for cloud tools. Off → neutral tile. */
    ring?: boolean
    /** Render only the resolved mark/glyph (no tile, no border), filling the
     *  parent and tinted with currentColor. For dense dropdown rows. */
    bare?: boolean
  }>(),
  { size: 'lg', forceCloud: false, ring: true, bare: false }
)

const isCloud = computed(() => props.forceCloud || isStimmaCloudTool(props.tool))
const isRing = computed(() => isCloud.value && props.ring)

// Primary task type, used only when no vendor mark resolves.
const primaryTaskType = computed(() => {
  const t = props.tool
  if (t.task_type) return t.task_type
  if (t.task_types && t.task_types.length) return t.task_types[0]
  return ''
})

// Mark = identity. Vendor mark first; task-generic glyph as the fallback floor.
const glyphSvg = computed(() => {
  const markSvg = getModelMarkSvg(props.tool.model_vendor)
  if (markSvg) return sanitizeSvg(markSvg)

  const inner = getTaskTypeIconSvg(primaryTaskType.value)
  const wrapped =
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" ` +
    `stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
  return sanitizeSvg(wrapped)
})

const outerSizeClass = computed(() => {
  switch (props.size) {
    case 'xs':
      return 'w-[26px] h-[26px] rounded-lg'
    case 'sm':
      return 'w-9 h-9 rounded-[10px]'
    case 'md':
      return 'w-8 h-8 rounded-lg'
    case 'xl':
      return 'w-16 h-16 rounded-2xl'
    case 'lg':
    default:
      return 'w-12 h-12 rounded-xl'
  }
})

const padClass = computed(() => {
  switch (props.size) {
    case 'xs':
      return 'p-1.5'
    case 'sm':
      return 'p-2'
    case 'md':
      return 'p-2'
    case 'xl':
      return 'p-3'
    case 'lg':
    default:
      return 'p-2.5'
  }
})

// Inner radius for the ring treatment (outer radius minus the 1.5px hairline).
const innerRadiusClass = computed(() => {
  switch (props.size) {
    case 'xs':
      return 'rounded-[6px]'
    case 'sm':
      return 'rounded-[8px]'
    case 'md':
      return 'rounded-[6px]'
    case 'xl':
      return 'rounded-[14px]'
    case 'lg':
    default:
      return 'rounded-[10px]'
  }
})

const ringPadClass = 'p-[1.5px]'
</script>

<style scoped>
/* Stimma Cloud gradient. Matches --stimma-cloud-* in style.css and the mock's
   .cloud-grad. */
.cloud-grad {
  background-image: linear-gradient(135deg, #0d9488 0%, #06b6d4 50%, #6366f1 100%);
}

/* Tint embedded marks to currentColor so multi-color brand SVGs render mono. */
.tool-mark :deep(svg) {
  width: 100%;
  height: 100%;
  display: block;
}
.tool-mark :deep(svg path),
.tool-mark :deep(svg stop),
.tool-mark :deep(svg [fill]:not([fill='none'])) {
  fill: currentColor;
}
</style>
