<template>
  <!-- Hovering a slot in the text (desktop): how it stands, and three of the variants images
       could get now. -->
  <Teleport to="body">
    <div
      v-if="shown"
      class="fixed z-menu pointer-events-none w-[300px] max-w-[calc(100vw-16px)] px-3 py-2.5 bg-surface border border-edge-subtle rounded-lg shadow-lg"
      :style="style"
      data-slot-hover
    >
      <div class="flex items-center gap-1.5 text-[11px]">
        <span v-if="kind === 'keep'" class="w-3 h-[15px] rounded-[3px] ring-1 ring-selection/80 bg-selection/30 bg-cover bg-center" :style="thumbStyle" />
        <Spinner v-else-if="kind === 'writing'" size="sm" />
        <span :class="kind === 'varying' || kind === 'writing' ? 'text-content-muted' : 'text-selection'" data-hover-head>{{ head }}</span>
      </div>
      <ul v-if="samples.length" class="mt-1.5 space-y-1">
        <li v-for="t in samples" :key="t" class="flex gap-1.5 text-xs leading-snug text-content" data-hover-sample>
          <span class="shrink-0 mt-[6px] w-1 h-1 rounded-full bg-content-muted" />
          <span>{{ t }}</span>
        </li>
      </ul>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Spinner from '../ui/Spinner.vue'
import { useViewport } from '../../composables/useViewport'
import { lineText, shownVariants } from '../../utils/programChoices'
import type { PromptProgram } from '../../composables/usePromptProgram'

const props = defineProps<{ program: PromptProgram }>()
const { isCoarsePointer } = useViewport()

// It shows after a short rest on the slot; moving to another slot swaps it at once.
const at = ref<{ n: number; rect: DOMRect } | null>(null)
let timer: ReturnType<typeof setTimeout> | null = null
watch(() => props.program.hover.value, (h) => {
  if (timer) clearTimeout(timer)
  if (!h) { at.value = null; return }
  if (at.value) at.value = h
  else timer = setTimeout(() => { at.value = props.program.hover.value }, 350)
})

const slot = computed(() => (at.value ? props.program.slots.value.find(s => s.n === at.value!.n) || null : null))
const shown = computed(() => !!at.value && !props.program.openCard.value && !isCoarsePointer.value)
const st = computed(() => (slot.value ? props.program.states.value[slot.value.id] : null))
const kind = computed(() => (slot.value ? props.program.lookOfSlot(slot.value.id) : 'writing'))
const pool = computed(() => (slot.value ? props.program.poolOf(slot.value.id) : null))
const head = computed(() => {
  switch (kind.value) {
    case 'writing': return 'Writing variants'
    case 'varying': return `Varies · ${pool.value?.variants?.length ?? 0} variants`
    case 'keep': return 'Kept from an image'
    case 'pinned': return 'Pinned'
    case 'several': return lineText(st.value) || 'Chosen'
    case 'off': return 'Left out'
    case 'written': return 'As written'
    default: return ''
  }
})
/** A few of the variants images could get now, spread across what can be drawn. */
const samples = computed(() => {
  if (!slot.value || kind.value === 'writing' || kind.value === 'off' || kind.value === 'written') return []
  const from = st.value?.values?.length ? st.value.values : shownVariants(pool.value, st.value).map(v => v.text)
  const k = kind.value === 'pinned' || kind.value === 'keep' ? 1 : 3
  const step = Math.max(1, Math.floor(from.length / k))
  const out: string[] = []
  for (let i = 0; i < from.length && out.length < k; i += step) out.push(from[i])
  return out
})
const thumbStyle = computed(() => {
  const src = typeof st.value?.from === 'number' ? props.program.thumbOf(st.value.from) : null
  return src ? { backgroundImage: `url("${src.replace(/"/g, '%22')}")` } : {}
})
const style = computed(() => {
  const r = at.value!.rect
  const below = r.bottom + 8
  const top = below + 150 > window.innerHeight ? r.top - 8 - 150 : below
  return { left: `${Math.max(8, Math.min(window.innerWidth - 308, r.left))}px`, top: `${Math.round(top)}px` }
})
</script>
