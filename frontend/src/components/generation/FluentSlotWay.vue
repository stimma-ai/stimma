<template>
  <!-- A slot's way, in its open row right after its words: a small icon (Add Detail or Add
       Variety) and ▾, opening a two-item menu with a check on the current one. -->
  <button
    ref="btn"
    type="button"
    class="inline-flex items-center align-top gap-0.5 ml-1 pl-1 pr-0.5 -my-0.5 py-0.5 coarse:-my-2 coarse:py-2 rounded text-content-secondary hover:text-content hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60"
    aria-haspopup="menu"
    :aria-expanded="open"
    :aria-label="WAY_NAMES[ways.way]"
    :title="WAY_NAMES[ways.way]"
    data-slot-way
    :data-way="ways.way"
    @click.stop="toggle"
    @keydown.stop
  >
    <ArrowsPointingOutIcon v-if="ways.way === 'any'" class="w-3.5 h-3.5 text-selection" />
    <ArrowsPointingInIcon v-else class="w-3.5 h-3.5 text-selection" />
    <ChevronDownIcon :class="['w-2.5 h-2.5 text-content-muted transition-transform duration-150', open ? 'rotate-180' : '']" stroke-width="2.5" />
  </button>
  <Teleport to="body">
    <div
      v-if="open"
      ref="menu"
      role="menu"
      class="fixed z-menu py-1 min-w-40 bg-surface border border-edge-subtle rounded-lg shadow-lg"
      :style="style"
      data-slot-way-menu
    >
      <button
        v-for="w in (['detail', 'any'] as const)"
        :key="w"
        type="button"
        role="menuitemradio"
        :aria-checked="ways.way === w"
        :disabled="w === 'any' && !varietyReady"
        :title="w === 'any' && kind.state === 'none' ? 'Couldn’t tell what these words are a kind of' : undefined"
        class="w-full flex items-center gap-2 px-3 py-1.5 coarse:py-2.5 text-left text-xs coarse:text-[13px] text-content hover:bg-overlay-subtle disabled:opacity-50 disabled:pointer-events-none outline-none focus-visible:bg-overlay-subtle"
        :data-way-item="w"
        :data-kind-state="w === 'any' && ways.variety === 'rewrite' ? kind.state : undefined"
        @click="choose(w)"
      >
        <ArrowsPointingOutIcon v-if="w === 'any'" class="w-3.5 h-3.5 shrink-0 text-selection" />
        <ArrowsPointingInIcon v-else class="w-3.5 h-3.5 shrink-0 text-selection" />
        <span class="flex-1 whitespace-nowrap">{{ WAY_NAMES[w] }}</span>
        <span v-if="w === 'any' && kind.state === 'finding'" class="w-3.5 h-3.5 shrink-0 flex items-center justify-center"><span class="w-2 h-2 rounded-full border border-content-muted/25 border-t-content-muted/70 animate-spin" /></span>
        <CheckIcon v-else :class="['w-3.5 h-3.5 shrink-0 text-selection', ways.way === w ? '' : 'invisible']" stroke-width="2.5" />
      </button>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowsPointingInIcon, ArrowsPointingOutIcon, CheckIcon, ChevronDownIcon } from '@heroicons/vue/24/outline'
import { slotWays } from '../../utils/programChoices'
import type { PromptProgram } from '../../composables/usePromptProgram'
import { WAY_NAMES } from '../../utils/promptSuggestions'

const props = defineProps<{
  program: PromptProgram; id: string
  /** The kind of a slot's words ("hairstyle" for `<short bob>`); "" when it can't be said. */
  slotKind?: (slot: { n: number; words: string }) => Promise<string>
}>()
const emit = defineEmits<{
  /** Add Variety on a slot whose words read as a kind: write `kind` in their place. */
  (e: 'vary-slot', slot: { n: number; words: string; kind: string }): void
}>()

// Add Detail keeps the words and makes each picture a specific one of them; Add Variety lets
// others of their kind in. Only this menu stores a mode (slotWays): Add Variety on a slot read
// as one thing sets 'kind', and Add Detail clears it again. Words that read as a kind already
// (<short bob>, <woman>) take Add Variety by having their kind written in their place
// (<hairstyle>, <person>), and the new slot opens.
const slot = computed(() => props.program.slotById.value[props.id] || null)
const ways = computed(() => slotWays(slot.value, props.program.states.value[props.id]))
const open = ref(false)
const btn = ref<HTMLElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const style = ref<Record<string, string>>({})

// The words' kind, for a rewrite: looked up when the menu opens (never shown). 'none' when it
// failed or came back empty; opening the menu again asks again.
const kind = ref<{ key: string; state: 'idle' | 'finding' | 'found' | 'none'; text: string }>({ key: '', state: 'idle', text: '' })
const varietyReady = computed(() => ways.value.variety === 'kind' || (ways.value.variety === 'rewrite' && kind.value.state === 'found'))
function findKind() {
  const s = slot.value
  if (!open.value || ways.value.variety !== 'rewrite' || !s) return
  const key = `${s.n}:${s.words}`
  if (kind.value.key === key && (kind.value.state === 'found' || kind.value.state === 'finding')) return
  if (!props.slotKind) { kind.value = { key, state: 'none', text: '' }; return }
  kind.value = { key, state: 'finding', text: '' }
  props.slotKind({ n: s.n, words: s.words }).then(
    (k) => { if (kind.value.key === key) kind.value = { key, state: k.trim() ? 'found' : 'none', text: k.trim() } },
    () => { if (kind.value.key === key) kind.value = { key, state: 'none', text: '' } },
  )
}
// The slot read again (or its words changed) while the menu is open: ask for what it needs now.
watch([() => ways.value.variety, () => slot.value?.words], findKind)

function toggle() {
  if (open.value) { open.value = false; return }
  const r = btn.value?.getBoundingClientRect()
  if (!r) return
  const top = r.bottom + 4 + 80 > window.innerHeight ? r.top - 4 - 80 : r.bottom + 4
  style.value = { left: `${Math.round(Math.max(8, Math.min(window.innerWidth - 168, r.left)))}px`, top: `${Math.round(top)}px` }
  open.value = true
  if (kind.value.state === 'none') kind.value = { ...kind.value, state: 'idle' }
  findKind()
}
function choose(w: 'detail' | 'any') {
  open.value = false
  const s = slot.value
  const to = w === 'detail' ? ways.value.detail : ways.value.variety
  if (!s || !to) return
  if (to === 'clear') props.program.clearMode(props.id)
  else if (to === 'kind') props.program.setMode(props.id, 'kind')
  else if (kind.value.state === 'found') emit('vary-slot', { n: s.n, words: s.words, kind: kind.value.text })
}

// A press anywhere but the menu or its button closes it; so does scrolling it out from under,
// and Escape (which then goes no further: the row stays open).
function onOutside(e: Event) {
  const t = e.target as Node | null
  if (!open.value || (t && (menu.value?.contains(t) || btn.value?.contains(t)))) return
  open.value = false
}
function close() { open.value = false }
function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape' || !open.value) return
  e.preventDefault()
  e.stopImmediatePropagation()
  open.value = false
  btn.value?.focus()
}
watch(() => props.id, () => { open.value = false })
// The picker's own Escape (step back, close the row) leaves an Escape alone while this menu is
// open, whichever of the two listeners runs first.
onMounted(() => {
  window.addEventListener('keydown', onKey, true)
  document.addEventListener('pointerdown', onOutside, true)
  window.addEventListener('scroll', close, true)
  window.addEventListener('resize', close)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey, true)
  document.removeEventListener('pointerdown', onOutside, true)
  window.removeEventListener('scroll', close, true)
  window.removeEventListener('resize', close)
})
</script>
