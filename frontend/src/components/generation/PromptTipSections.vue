<template>
  <!-- One section per tip (promptTips.ts): its title, an example as it looks in the prompt,
       and a few lines in the user's words. `ruled`: a hairline above every section, the
       first too (it follows an intro); else only between sections. -->
  <section v-for="(tip, ti) in tips" :key="tip.title" :class="ruled || ti > 0 ? 'border-t border-edge-subtle pt-3 mt-3' : ''">
    <h4 class="text-[12.5px] font-semibold text-content mb-1.5">{{ tip.title }}</h4>
    <!-- A whole line, as it looks in the prompt -->
    <p v-if="tip.line" class="mb-1.5 rounded-md bg-overlay-subtle px-2 py-1.5 text-xs leading-relaxed text-content-secondary" :data-tip-example="tip.line.tone">
      <template v-for="(part, i) in tip.line.parts" :key="i"><span v-if="part.tone" :class="['px-0.5 rounded-[3px]', TONES[part.tone]]" :data-tone="part.tone" v-text="part.text"></span><template v-else>{{ part.text }}</template></template>
    </p>
    <code v-if="tip.code" :class="['inline-block mb-1.5 px-1.5 py-0.5 rounded text-[11px]', TONES[tip.code.tone]]" :data-tone="tip.code.tone" :data-tip-example="tip.code.tone" v-text="tip.code.text"></code>
    <p v-for="para in tip.text" :key="para" class="text-xs text-content-tertiary leading-relaxed mt-1 first:mt-0">{{ para }}</p>
    <ul v-if="tip.steps" class="mt-1.5 space-y-1">
      <li v-for="step in tip.steps" :key="step" class="flex gap-2 text-xs text-content-tertiary leading-relaxed">
        <span class="mt-[7px] w-1 h-1 shrink-0 rounded-full bg-content-muted" />{{ step }}
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { TONES, type Tip } from './promptTips'

defineProps<{ tips: Tip[]; ruled?: boolean }>()
</script>
