<template>
  <!-- Trailing provider label for tool rows. The two most common providers are
       shown as compact glyphs instead of text (Stimma Cloud and ComfyUI are
       repetitive and wide when a whole list shares them); everything else keeps
       its short name. The cloud carries its own gradient def so it renders
       correctly in any host. -->
  <span
    v-if="cloud"
    class="flex-shrink-0 inline-flex items-center"
    role="img"
    aria-label="Stimma Cloud"
    title="Stimma Cloud"
  >
    <svg
      class="w-4 h-4"
      fill="none"
      viewBox="0 0 24 24"
      stroke-width="1.6"
      stroke-linecap="round"
      stroke-linejoin="round"
      :stroke="`url(#${gradId})`"
    >
      <defs>
        <linearGradient :id="gradId" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#0d9488" />
          <stop offset="50%" stop-color="#06b6d4" />
          <stop offset="100%" stop-color="#6366f1" />
        </linearGradient>
      </defs>
      <path d="M2.25 15a4.5 4.5 0 0 0 4.5 4.5H18a3.75 3.75 0 0 0 1.332-7.257 3 3 0 0 0-3.758-3.848 5.25 5.25 0 0 0-10.233 2.33A4.502 4.502 0 0 0 2.25 15Z" />
    </svg>
  </span>
  <span
    v-else-if="isComfy"
    class="flex-shrink-0 inline-flex items-center text-content-muted"
    role="img"
    aria-label="ComfyUI"
    title="ComfyUI"
  >
    <svg class="w-[15px] h-[15px]" viewBox="0 0 24 24" fill="currentColor" fill-rule="evenodd">
      <path d="M5.485 23.76c-.568 0-1.026-.207-1.325-.598-.307-.402-.387-.964-.22-1.54l.672-2.315a.605.605 0 00-.1-.536.622.622 0 00-.494-.243H2.085c-.568 0-1.026-.207-1.325-.598-.307-.403-.387-.964-.22-1.54l2.31-7.917.255-.87c.343-1.18 1.592-2.14 2.786-2.14h2.313c.276 0 .519-.18.595-.442l.764-2.633C9.906 1.208 11.155.249 12.35.249l4.945-.008h3.62c.568 0 1.027.206 1.325.597.307.402.387.964.22 1.54l-1.035 3.566c-.343 1.178-1.593 2.137-2.787 2.137l-4.956.01H11.37a.618.618 0 00-.594.441l-1.928 6.604a.605.605 0 00.1.537c.118.153.3.243.495.243l3.275-.006h3.61c.568 0 1.026.206 1.325.598.307.402.387.964.22 1.54l-1.036 3.565c-.342 1.179-1.592 2.138-2.786 2.138l-4.957.01h-3.61z" />
    </svg>
  </span>
  <span
    v-else
    class="flex-shrink-0 text-[11.5px] text-content-muted truncate"
  >{{ providerName }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

// Per-instance gradient id so the cloud renders correctly regardless of host.
let _seq = 0
const gradId = `stimma-cloud-lbl-${_seq++}`

const props = defineProps<{
  cloud: boolean
  providerName: string
}>()

const isComfy = computed(() => /comfyui/i.test(props.providerName || ''))
</script>
