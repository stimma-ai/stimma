<template>
  <!-- Use from an image: what one image drew, a line per part, hung from the image. Using a
       line adds what it drew to that part's picks (a person's age, gender and descent can each
       be used on their own); the part's row flashes and a toast offers Undo. The image keeps
       no state. A part the prompt no longer has reads quietly as not in it now. -->
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-menu" @click="emit('close')">
      <div
        ref="menuRef"
        role="menu"
        aria-label="Use in your prompt"
        data-use-list
        data-escape-layer
        tabindex="-1"
        class="fixed z-menu outline-none w-[300px] max-w-[calc(100vw-16px)] max-h-[min(28rem,calc(100dvh-16px))] bg-surface border border-edge-subtle rounded-lg shadow-lg p-1 flex flex-col gap-px overflow-y-auto overscroll-contain"
        :style="menuStyle"
        @click.stop
      >
        <div class="shrink-0 px-2 pt-1 pb-1 text-[11px] text-content-tertiary">Use in your prompt</div>
        <template v-for="p in parts" :key="p.key">
          <div v-if="!p.here" class="flex items-baseline gap-2 px-2 py-1.5 text-xs coarse:text-[13px] text-content-muted" :data-use-gone="p.key">
            <span class="w-16 shrink-0 truncate">{{ p.label }}</span>
            <span class="flex-1 min-w-0">Not in your prompt now</span>
          </div>
          <template v-else>
            <button
              type="button"
              role="menuitem"
              class="group/use w-full flex items-start gap-2 px-2 py-1.5 coarse:py-2.5 rounded-md text-left text-xs coarse:text-[13px] hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60"
              :data-use-part="p.key"
              @click="use(p)"
            >
              <span class="w-16 shrink-0 truncate text-content-tertiary">{{ p.label }}</span>
              <span class="flex-1 min-w-0 leading-snug break-words text-content"><span v-for="(x, k) in pieces(p)" :key="k" :class="x.kept ? 'text-content-muted' : ''">{{ x.t }}</span></span>
              <span class="shrink-0 text-[11px] text-selection opacity-0 group-hover/use:opacity-100 group-focus-visible/use:opacity-100 coarse:opacity-100">Use</span>
            </button>
            <!-- A person's broad strokes, each its own use. -->
            <div v-if="p.person" class="flex flex-wrap items-baseline gap-x-1 pl-[5rem] pr-2 pb-1.5 text-[11px] coarse:text-xs" :data-use-facets="p.key">
              <span class="text-content-muted">or use {{ p.person.pronoun }}:</span>
              <template v-for="(f, i) in p.person.facets" :key="f.id">
                <span v-if="i" class="text-content-muted" aria-hidden="true">·</span>
                <button
                  type="button"
                  role="menuitem"
                  class="px-0.5 coarse:py-1.5 rounded text-content-secondary hover:text-selection outline-none focus-visible:ring-1 focus-visible:ring-selection/60"
                  :data-use-facet="f.id"
                  @click="use(p, f)"
                >{{ f.says }}</button>
              </template>
            </div>
          </template>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useAnchoredMenuPosition } from '../../composables/useContextMenuPosition'
import { addToast } from '../../composables/useToasts'
import { flashSlot } from '../../composables/slotFlash'
import { cap, keptPieces } from '../../utils/programChoices'
import { imageParts, usedState, type Facet, type ImagePart } from '../../utils/fromImage'
import type { PromptProgram } from '../../composables/usePromptProgram'

/** `open`: one image's run record and where the list hangs from. */
const props = defineProps<{ open: { run: any; anchor: DOMRect } | null; program: PromptProgram }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const menuRef = ref<HTMLElement | null>(null)
const anchorRect = computed(() => props.open?.anchor ?? null)
const visible = computed(() => !!props.open)
const { menuStyle } = useAnchoredMenuPosition(menuRef, anchorRect, visible, { gap: 6 })

const parts = computed(() => props.open ? imageParts(props.open.run, {
  slots: props.program.slots.value,
  choices: props.program.choices.value,
  states: props.program.states.value,
  pools: props.program.pools.value,
}) : [])

// The words the draw kept from the part, quieter (display only).
function pieces(p: ImagePart) {
  return p.words ? keptPieces(p.text, p.words, props.program.poolOf(p.key)?.keep) : [{ t: p.text }]
}

function use(p: ImagePart, facet?: Facet) {
  const program = props.program
  const before = program.states.value[p.key] ?? null
  const next = usedState(p, program.states.value, program.poolOf(p.key), facet)
  if (next === undefined) return
  program.setState(p.key, next)
  flashSlot(p.key)
  const name = cap(program.slotById.value[p.key]?.words || p.label)
  addToast(`${name}: added ${facet ? facet.says : p.text}`, 'success', 6000, {
    label: 'Undo',
    onClick: () => { program.setState(p.key, before); flashSlot(p.key) },
  })
}

// Teleported to the end of the page: focus moves in when it opens, and Escape closes it
// before anything under it (the Generation details dialog).
let returnTo: HTMLElement | null = null
function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  e.preventDefault()
  e.stopPropagation()
  emit('close')
}
watch(visible, (v) => {
  if (v) {
    returnTo = document.activeElement instanceof HTMLElement ? document.activeElement : null
    window.addEventListener('keydown', onKey, true)
    void nextTick(() => menuRef.value?.focus({ preventScroll: true }))
  } else {
    window.removeEventListener('keydown', onKey, true)
    const to = returnTo
    returnTo = null
    if (to?.isConnected) to.focus()
  }
})
onUnmounted(() => window.removeEventListener('keydown', onKey, true))
</script>
