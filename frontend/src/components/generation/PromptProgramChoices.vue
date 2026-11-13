<template>
  <!-- Under the prompt: one pill per slot and per {a|b} list. An untouched pill is its label;
       a chosen one is "Label value" with the value kept short (the whole of it in the
       tooltip), and its × puts it back. A person's chosen details are pills of their own,
       folding into the person's pill at three. On a touch screen each pill, its × and Reset
       are 44px targets that reach past the pill's edge; the row's gaps leave them room, so
       the pills look as they do elsewhere and no two targets overlap. -->
  <div
    v-if="program.status.value !== 'off' && pills.length"
    :class="['px-3 pt-1 pb-2 coarse:pt-2 coarse:pb-2.5 flex flex-wrap items-center gap-1.5 coarse:gap-x-2 coarse:gap-y-3.5 transition-opacity', program.status.value === 'ready' ? '' : 'opacity-50']"
    data-program-choices
  >
    <span
      v-for="p in pills"
      :key="p.id"
      :class="pillClass(p.changed, isOpen(p))"
      :title="p.title"
    >
      <button
        type="button"
        :class="['inline-flex items-center gap-1 min-w-0 py-1 coarse:py-1.5 coarse:min-h-11 coarse:min-w-11 coarse:-my-2 coarse:text-[13px] pl-2.5 rounded-full outline-none focus-visible:ring-1 focus-visible:ring-selection/60', p.changed ? 'pr-0.5 coarse:pr-0' : 'pr-2.5']"
        :data-choice="p.id"
        @click="open(p, $event.currentTarget as Element)"
      >
        <UserIcon v-if="p.folded" class="w-3 h-3 shrink-0 opacity-70" />
        <span :class="['shrink-0', p.value || p.swatches ? 'opacity-70' : '']">{{ p.label }}</span>
        <span v-if="p.swatches" class="shrink-0 flex -space-x-1" data-swatches>
          <span v-for="(c, i) in p.swatches" :key="i" class="w-3 h-3 rounded-full border border-surface" :style="{ background: c }" />
        </span>
        <span v-else-if="p.value" :class="['truncate', p.folded ? 'max-w-[9rem]' : 'max-w-[7.5rem]']">{{ p.value }}</span>
      </button>
      <button
        v-if="p.changed"
        type="button"
        class="group/x shrink-0 mr-1 coarse:w-11 coarse:h-11 coarse:-my-2 coarse:-mr-1.5 flex items-center justify-center rounded-full opacity-70 hover:opacity-100 outline-none focus-visible:ring-1 focus-visible:ring-selection/60"
        :aria-label="`Reset ${p.label}`"
        :data-reset="p.id"
        @click="program.reset(p.resets)"
      >
        <span class="p-0.5 rounded-full group-hover/x:bg-selection/20"><XMarkIcon class="w-3 h-3" /></span>
      </button>
    </span>

    <button
      v-if="changed > 1"
      type="button"
      class="ml-auto px-1.5 py-0.5 coarse:px-2.5 coarse:min-h-11 coarse:-my-2 coarse:-mr-2.5 rounded-md text-[11px] coarse:text-xs text-content-muted hover:text-content hover:bg-overlay-subtle"
      data-reset-all
      @click="program.resetAll()"
    >Reset</button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { UserIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import { changedCount, pillsOf, type ChoiceWorld, type Pill } from '../../utils/programChoices'
import type { PromptProgram } from '../../composables/usePromptProgram'

const props = defineProps<{ program: PromptProgram }>()

const world = computed<ChoiceWorld>(() => ({
  slots: props.program.slots.value,
  choices: props.program.choices.value,
  states: props.program.states.value,
  pools: props.program.pools.value,
}))
const pills = computed(() => pillsOf(world.value))
const changed = computed(() => changedCount(world.value))

function open(p: Pill, el: Element) {
  if ('slot' in p.open) props.program.openSlot(p.open.slot, el)
  else props.program.openChoice(p.open.choice, el)
}
function isOpen(p: Pill): boolean {
  const t = props.program.openCard.value?.target
  if (!t) return false
  if ('choice' in t) return 'choice' in p.open && p.open.choice === t.choice
  return 'slot' in p.open && props.program.slotFor(t.slot)?.id === p.open.slot
}

// Indigo once chosen.
function pillClass(changed: boolean, open: boolean) {
  return [
    'inline-flex items-center max-w-full rounded-full text-xs whitespace-nowrap border transition-colors',
    changed ? 'bg-selection/15 text-selection' : 'bg-surface-raised text-content hover:bg-surface-hover',
    open ? 'border-selection/40' : 'border-transparent',
  ]
}
</script>
