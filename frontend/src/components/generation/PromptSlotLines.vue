<template>
  <!-- Under the prompt: a line per slot the user has set, in the Keep from this card's own
       shape ("Lighting · window light"). Ticked means kept like this; untick to let it vary
       again (the line stays, unticked, so a second tick puts it back); × lets it vary and
       drops the line. Clicking the words opens the slot's picker. Slots that only vary have
       no line: the text shows them. -->
  <div v-if="program.status.value !== 'off' && rows.length" class="px-1.5 pt-0.5 pb-1.5 flex flex-col gap-px" data-slot-lines>
    <div
      v-for="r in rows"
      :key="r.id"
      :class="['group flex items-start coarse:items-center gap-2.5 coarse:gap-4 pl-2 pr-1 py-1 coarse:py-0 coarse:min-h-11 rounded-md hover:bg-overlay-subtle', openId === r.id ? 'bg-overlay-subtle' : '']"
      :data-line="r.id"
      :data-on="r.on ? '' : undefined"
    >
      <!-- The tick: a 14px box, a 44px target on a touch screen. -->
      <span
        role="checkbox"
        :aria-checked="r.on"
        tabindex="0"
        :aria-label="r.on ? `Let ${r.label} vary` : `Keep ${r.label}`"
        class="group/tick shrink-0 mt-[2px] coarse:mt-0 coarse:w-11 coarse:h-11 coarse:-m-[15px] flex items-center justify-center cursor-pointer outline-none rounded-md focus-visible:ring-1 focus-visible:ring-selection/60"
        data-line-tick
        @click="flip(r)"
        @keydown.space.prevent="flip(r)"
        @keydown.enter.prevent="flip(r)"
      >
        <span :class="['w-3.5 h-3.5 rounded-[4px] flex items-center justify-center border', r.on ? 'bg-selection border-selection text-white' : 'border-edge-strong']">
          <CheckIcon v-if="r.on" class="w-2.5 h-2.5" stroke-width="3" />
        </span>
      </span>
      <button
        type="button"
        class="flex-1 min-w-0 coarse:min-h-11 flex items-start coarse:items-center gap-2.5 text-left outline-none focus-visible:ring-1 focus-visible:ring-selection/60 rounded"
        data-line-open
        @click="program.openChoice(r.id, ($event.currentTarget as Element).closest('[data-line]'))"
      >
        <span class="w-20 shrink-0 truncate text-xs coarse:text-[13px] text-content">{{ r.label }}</span>
        <span :class="['flex-1 min-w-0 text-xs coarse:text-[13px] leading-snug line-clamp-2', r.on ? 'text-content-secondary' : 'text-content-muted line-through decoration-content-muted/50']" data-line-text>{{ r.text }}</span>
        <span v-if="r.thumb" class="shrink-0 mt-[1px] coarse:mt-0 w-3 h-[15px] rounded-[3px] ring-1 ring-selection/70 bg-selection/30 bg-cover bg-center" :style="{ backgroundImage: `url(&quot;${r.thumb}&quot;)` }" title="From an image" data-line-thumb />
      </button>
      <button
        type="button"
        class="group/x shrink-0 -my-0.5 coarse:my-0 p-0.5 coarse:p-3.5 coarse:-mr-1 rounded-full text-content-muted hover:text-content opacity-0 group-hover:opacity-100 focus-visible:opacity-100 coarse:opacity-100 outline-none focus-visible:ring-1 focus-visible:ring-selection/60"
        :aria-label="`Remove ${r.label}`"
        data-line-remove
        @click="program.removeLine(r.id)"
      >
        <span class="block p-0.5 rounded-full group-hover/x:bg-overlay-subtle"><XMarkIcon class="w-3 h-3" /></span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CheckIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import { isChanged, lineText } from '../../utils/programChoices'
import type { PromptProgram } from '../../composables/usePromptProgram'

const props = defineProps<{ program: PromptProgram }>()

interface Line { id: string; label: string; text: string; on: boolean; thumb: string | null }

const openId = computed(() => {
  const t = props.program.openCard.value?.target
  if (!t) return null
  return 'choice' in t ? t.choice : props.program.slotFor(t.slot)?.id ?? null
})

const rows = computed<Line[]>(() => {
  const p = props.program
  const states = p.states.value
  const released = p.released.value
  const order = [
    ...p.slots.value.map(s => ({ id: s.id, label: s.label })),
    ...p.choices.value.filter(c => !c.slot).map(c => ({ id: c.id, label: c.label })),
  ]
  const out: Line[] = []
  for (const { id, label } of order) {
    if (!p.byId.value[id]) continue
    const on = isChanged(states[id])
    const held = on ? states[id] : released[id]
    if (!held) continue
    out.push({ id, label, on, text: lineText(held, !p.byId.value[id].slot), thumb: held.values?.length === 1 && typeof held.from === 'number' ? p.thumbOf(held.from) : null })
  }
  return out
})

function flip(r: Line) {
  if (r.on) props.program.release(r.id)
  else props.program.restore(r.id)
}
</script>
