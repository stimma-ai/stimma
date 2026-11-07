<template>
  <!-- Riff's choices: one pill per thing that varies from image to image. Sits
       between the prompt text and the Riff/Translate row. At rest a pill is just
       its name; once limited it shows what's left. -->
  <div
    v-if="program.status.value !== 'off' && program.rows.value.length"
    class="flex flex-wrap gap-1.5 px-3 pt-1 pb-2 compact:flex-nowrap compact:overflow-x-auto compact:scrollbar-none"
    data-program-choices
  >
    <template v-for="row in program.rows.value" :key="row.kind === 'group' ? `g:${row.group.id}` : row.choice.id">
      <button
        v-if="row.kind === 'choice'"
        type="button"
        :class="pillClass(program.isPinned(row.choice), openId === row.choice.id)"
        :title="pillTitle(row.choice)"
        :data-choice="row.choice.id"
        @click="program.open(row.choice.id, $event.currentTarget as Element)"
      >
        <span v-if="row.choice.parent" class="text-content-muted -mr-0.5">↳</span>
        <WandSparklesIcon v-if="row.choice.source === 'added'" class="w-3 h-3 shrink-0 text-content-tertiary" />
        <span :class="['truncate max-w-[10rem]', program.isPinned(row.choice) ? 'text-selection/80' : '']">{{ row.choice.label }}<template v-if="program.isPinned(row.choice)">:</template></span>
        <span v-if="program.isPinned(row.choice)" class="truncate max-w-[16rem]">{{ program.valueText(row.choice) }}</span>
      </button>
      <button
        v-else
        type="button"
        :class="pillClass(groupPinned(row.members), openId === `group:${row.group.id}`)"
        :data-choice="`group:${row.group.id}`"
        @click="program.open(`group:${row.group.id}`, $event.currentTarget as Element)"
      >
        <span :class="groupPinned(row.members) ? 'text-selection/80' : ''">{{ row.group.label }}</span>
        <span :class="groupPinned(row.members) ? '' : 'text-content-tertiary'">×{{ row.group.count }}<template v-if="groupPinned(row.members)"> · {{ groupPinned(row.members) }} chosen</template></span>
      </button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import WandSparklesIcon from '../icons/WandSparklesIcon.vue'
import { PROMPT_BRAND } from './promptBrand'
import type { PromptProgram, ProgramChoice } from '../../composables/usePromptProgram'

const props = defineProps<{ program: PromptProgram }>()

const openId = computed(() => props.program.openCard.value?.id || null)

function pillClass(pinned: boolean, open: boolean) {
  return [
    'inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs whitespace-nowrap shrink-0 border transition-colors outline-none focus-visible:ring-1 focus-visible:ring-selection/60 coarse:py-1.5 coarse:text-[13px]',
    pinned ? 'bg-selection/15 text-selection' : 'bg-surface-raised text-content hover:bg-surface-hover',
    open ? 'border-selection/40' : 'border-transparent',
  ]
}

function pillTitle(c: ProgramChoice) {
  const n = props.program.optionsOf(c).length
  const base = c.kind === 'param' ? 'Each image picks a value in this range. Click to see it.' : `Each image picks one of ${n}. Click to choose.`
  return c.source === 'added' ? `Added by ${PROMPT_BRAND}. ${base}` : base
}

function groupPinned(members: ProgramChoice[]) {
  return members.filter(m => props.program.isPinned(m)).length
}
</script>
