<template>
  <!-- Keep from this: what one image drew, a line per slot. A tick pins that slot to this
       image's variant, as if chosen in its picker, and the same line shows under the prompt
       (with the image's thumbnail on the slot); unticking puts it back. -->
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-menu" @click="emit('close')">
      <div
        ref="menuRef"
        role="dialog"
        aria-label="Keep from this"
        data-keep-card
        data-escape-layer
        tabindex="-1"
        class="fixed z-menu outline-none w-[340px] max-w-[calc(100vw-16px)] bg-surface border border-edge-subtle rounded-lg shadow-lg flex flex-col"
        :style="menuStyle"
        @click.stop
      >
        <div class="shrink-0 px-3 pt-2.5 pb-1.5 text-[13px] font-semibold text-content">Keep from this</div>
        <div class="px-1.5 pb-1.5 flex flex-col gap-px overflow-y-auto overscroll-contain">
          <div v-if="!rows.length" class="px-2 pb-1.5 text-xs text-content-muted" data-keep-none>Nothing from this image is in your prompt now.</div>
          <div
            v-for="r in rows"
            :key="r.key"
            role="checkbox"
            :aria-checked="r.on"
            tabindex="0"
            :data-keep="r.key"
            class="flex items-start gap-2.5 px-2 py-1.5 coarse:py-2.5 rounded-md cursor-pointer hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60"
            @click="flip(r)"
            @keydown.space.prevent="flip(r)"
            @keydown.enter.prevent="flip(r)"
          >
            <span :class="['shrink-0 mt-[2px] w-3.5 h-3.5 rounded-[4px] flex items-center justify-center border', r.on ? 'bg-selection border-selection text-white' : 'border-edge-strong']">
              <CheckIcon v-if="r.on" class="w-2.5 h-2.5" stroke-width="3" />
            </span>
            <span class="w-20 shrink-0 truncate text-xs coarse:text-[13px] text-content">{{ r.label }}</span>
            <span class="flex-1 min-w-0 text-xs coarse:text-[13px] leading-snug text-content-secondary line-clamp-2">{{ r.text }}</span>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { CheckIcon } from '@heroicons/vue/24/outline'
import { useAnchoredMenuPosition } from '../../composables/useContextMenuPosition'
import { flipRow, keepRows, type KeepRow } from '../../utils/keepFromThis'
import type { PromptProgram } from '../../composables/usePromptProgram'

/** `open`: one image's run record, its media (for the thumbnail a kept slot shows), and where
    the card hangs from. */
const props = defineProps<{ open: { run: any; anchor: DOMRect; media?: number | null } | null; program: PromptProgram }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const menuRef = ref<HTMLElement | null>(null)
const anchorRect = computed(() => props.open?.anchor ?? null)
const visible = computed(() => !!props.open)
const { menuStyle } = useAnchoredMenuPosition(menuRef, anchorRect, visible, { gap: 6 })

const rows = computed(() => props.open ? keepRows(props.open.run, {
  slots: props.program.slots.value,
  choices: props.program.choices.value,
  states: props.program.states.value,
  pools: props.program.pools.value,
}) : [])

function flip(r: KeepRow) {
  props.program.setStates(flipRow(r, props.program.states.value, props.open?.media))
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
    // Into the card, so Tab reaches its lines next; no line looks focused until then.
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
