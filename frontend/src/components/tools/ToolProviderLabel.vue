<template>
  <!-- Trailing provider label for tool rows. Stimma keeps its branded accent;
       ComfyUI uses its compact mark; everything else keeps its short name. -->
  <span
    v-if="cloud"
    class="flex-shrink-0 text-[11.5px] font-medium stimma-cloud-text"
  >{{ STIMMA_TOOL_PROVIDER_DISPLAY_NAME }}</span>
  <span
    v-else-if="isComfy"
    class="flex-shrink-0 inline-flex items-center text-content-muted"
    role="img"
    aria-label="ComfyUI"
    title="ComfyUI"
  >
    <ComfyUIIcon class="h-[15px] w-[15px]" />
  </span>
  <span
    v-else
    class="flex-shrink-0 text-[11.5px] text-content-muted truncate"
  >{{ toolProviderDisplayName({ provider_name: providerName }) }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { STIMMA_TOOL_PROVIDER_DISPLAY_NAME, toolProviderDisplayName } from '../../utils/stimmaCloud'
import ComfyUIIcon from './ComfyUIIcon.vue'

const props = defineProps<{
  cloud: boolean
  providerName: string
}>()

const isComfy = computed(() => /comfyui/i.test(props.providerName || ''))
</script>
