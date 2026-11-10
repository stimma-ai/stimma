<template>
  <!-- One row per roll: the prompt with its drawn values inline. A reroll strikes the
       value it replaced beside the new one; the roll the image used reads brightest. The
       judge's score is a developer detail. -->
  <div class="space-y-2.5" data-program-rolls>
    <p
      v-for="(roll, i) in rolls"
      :key="i"
      :class="[
        'text-xs leading-relaxed break-words select-text transition-colors duration-150',
        roll.used ? 'text-content-secondary' : 'text-content-muted',
      ]"
      data-program-roll
      :data-used="roll.used ? '' : undefined"
    >
      <template v-for="(piece, j) in roll.pieces" :key="j">
        <template v-if="piece.id">
          <template v-if="piece.was != null">
            <Tooltip v-if="devModeRef && piece.score != null" :text="`Rerolled · ${piece.score.toFixed(2)}`">
              <s class="text-content-tertiary decoration-content-tertiary" data-roll-was>{{ piece.was }}</s>
            </Tooltip>
            <s v-else class="text-content-tertiary decoration-content-tertiary" data-roll-was>{{ piece.was }}</s>
            {{ ' ' }}
          </template>
          <span
            :class="roll.used ? 'text-selection' : 'text-selection/60'"
            :data-roll-changed="piece.was != null ? '' : undefined"
            data-roll-value
          >{{ piece.text }}</span>
        </template>
        <template v-else>{{ piece.text }}</template>
      </template>
    </p>
    <p v-if="unchecked" class="text-[11px] text-content-muted" data-program-unchecked>{{ unchecked }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Tooltip from '../ui/Tooltip.vue'
import { devModeRef } from '../../appConfig'
import { promptProgramRolls } from '../../utils/promptProgramRolls'
import { unjudgedNote } from '../../utils/fluentJudge'
import { PROMPT_BRAND } from './promptBrand'

const props = defineProps<{ run: any }>()
const rolls = computed(() => promptProgramRolls(props.run))
// One quiet line when the fit check couldn't be had for this image.
const unchecked = computed(() => unjudgedNote(props.run, PROMPT_BRAND))
</script>
