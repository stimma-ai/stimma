<template>
  <div
    v-if="program.status.value !== 'off' && program.sections.value.length"
    :class="['px-3 pt-1 pb-2 space-y-3 transition-opacity', program.status.value === 'ready' ? '' : 'opacity-50']"
    data-program-choices
  >
    <section v-for="section in program.sections.value" :key="section.id" :aria-label="section.label || 'General'" :data-program-section="section.id">
      <h3 v-if="section.label" class="mb-1.5 text-ctl font-semibold text-content-secondary">{{ section.label }}</h3>
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="choice in section.choices"
          :key="choice.id"
          type="button"
          :class="pillClass(program.isPinned(choice), openId === choice.id)"
          :title="pillTitle(choice)"
          :data-choice="choice.id"
          @click="program.open(choice.id, $event.currentTarget as Element)"
        >
          <span v-if="choice.parent" class="text-content-muted -mr-0.5">↳</span>
          <WandSparklesIcon v-if="choice.source === 'added'" class="w-3 h-3 shrink-0 text-content-tertiary" />
          <span :class="['truncate max-w-[10rem]', program.isPinned(choice) ? 'text-selection/80' : '']">{{ programLabel(choice.label) }}<template v-if="program.showsValue(choice)">:</template></span>
          <span v-if="program.showsValue(choice)" class="truncate max-w-[16rem]">{{ program.valueText(choice) }}</span>
        </button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import WandSparklesIcon from '../icons/WandSparklesIcon.vue'
import { PROMPT_BRAND } from './promptBrand'
import { programLabel } from '../../utils/programChoiceLayout'
import type { PromptProgram, ProgramChoice } from '../../composables/usePromptProgram'

const props = defineProps<{ program: PromptProgram }>()

const openId = computed(() => props.program.openCard.value?.id || null)

function pillClass(pinned: boolean, open: boolean) {
  return [
    'inline-flex max-w-full items-center gap-1 px-2.5 py-1 rounded-full text-xs whitespace-nowrap shrink-0 border transition-colors outline-none focus-visible:ring-1 focus-visible:ring-selection/60 coarse:py-1.5 coarse:text-[13px]',
    pinned ? 'bg-selection/15 text-selection' : 'bg-surface-raised text-content hover:bg-surface-hover',
    open ? 'border-selection/40' : 'border-transparent',
  ]
}

function pillTitle(c: ProgramChoice) {
  if (c.said && !props.program.isPinned(c)) return `Every image uses “${c.said}”. Click to choose others.`
  const n = props.program.optionsOf(c).length
  const base = c.kind === 'param' ? 'Each image picks a value in this range. Click to see it.' : `Each image picks one of ${n}. Click to choose.`
  return c.source === 'added' ? `Added by ${PROMPT_BRAND}. ${base}` : base
}

</script>
