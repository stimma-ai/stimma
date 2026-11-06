<template>
  <!-- The prepared program's choices: one pill per thing each image draws. Sits
       between the prompt text and the Enhance/Translate row. -->
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
        :title="row.choice.source === 'added' ? 'Added by Enhance' : undefined"
        :data-choice="row.choice.id"
        @click="program.open(row.choice.id, $event.currentTarget as Element)"
      >
        <span v-if="row.choice.parent" class="text-content-muted -mr-0.5">↳</span>
        <WandSparklesIcon v-if="row.choice.source === 'added'" class="w-3 h-3 shrink-0 text-content-tertiary" />
        <span :class="['truncate max-w-[10rem]', program.isPinned(row.choice) ? 'text-selection/80' : 'text-content-tertiary']">{{ row.choice.label }}</span>
        <span class="truncate max-w-[16rem]">{{ program.valueText(row.choice) }}</span>
      </button>
      <button
        v-else
        type="button"
        :class="pillClass(groupPinned(row.members), openId === `group:${row.group.id}`)"
        :data-choice="`group:${row.group.id}`"
        @click="program.open(`group:${row.group.id}`, $event.currentTarget as Element)"
      >
        <span :class="groupPinned(row.members) ? 'text-selection/80' : 'text-content-tertiary'">{{ row.group.label }}</span>
        <span>×{{ row.group.count }}<template v-if="groupPinned(row.members)"> · {{ groupPinned(row.members) }} pinned</template></span>
      </button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import WandSparklesIcon from '../icons/WandSparklesIcon.vue'
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

function groupPinned(members: ProgramChoice[]) {
  return members.filter(m => props.program.isPinned(m)).length
}
</script>
