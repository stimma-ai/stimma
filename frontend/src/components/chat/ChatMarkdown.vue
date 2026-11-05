<script setup lang="ts">
import { ref, shallowRef, watch } from 'vue'
import { DocumentDuplicateIcon } from '@heroicons/vue/24/outline'
import IconButton from '../ui/IconButton.vue'
import Tooltip from '../ui/Tooltip.vue'
import { copyToClipboard } from '../../utils/clipboard'
import { addToast } from '../../composables/useToasts'

// HTML is sanitized by the chat renderer before reaching this component.
const props = defineProps<{ html: string }>()
const content = ref<HTMLElement | null>(null)
const blocks = shallowRef<{ target: HTMLElement; text: string }[]>([])

watch(() => [props.html, content.value], () => {
  // Run after v-html updates, including while a response is streaming.
  blocks.value = Array.from(content.value?.querySelectorAll('pre') ?? []).map(pre => {
    const target = document.createElement('div')
    target.className = 'not-prose flex justify-end select-none'
    pre.before(target)
    return { target, text: pre.textContent ?? '' }
  })
}, { flush: 'post' })

async function copy(text: string) {
  if (await copyToClipboard(text)) {
    addToast('Copied', 'success', 1500)
  } else {
    addToast('Failed to copy to clipboard', 'error')
  }
}
</script>

<template>
  <!-- The typography plugin wraps inline code in literal backticks; chat code is
       a mono chip instead, so the pseudo-element content is cleared. -->
  <div class="[&>div>:first-child]:mt-0 [&>div>:last-child]:mb-0 [&_code]:before:content-none [&_code]:after:content-none [&_:not(pre)>code]:rounded-md [&_:not(pre)>code]:bg-overlay-subtle [&_:not(pre)>code]:px-1.5 [&_:not(pre)>code]:py-0.5 [&_:not(pre)>code]:font-mono [&_:not(pre)>code]:text-[0.875em] [&_:not(pre)>code]:font-normal [&_:not(pre)>code]:break-words">
    <div ref="content" v-html="html" />
    <Teleport v-for="(block, index) in blocks" :key="index" :to="block.target">
      <Tooltip text="Copy contents">
        <IconButton
          aria-label="Copy contents"
          class="[[data-pointer=coarse]_&]:min-h-11 [[data-pointer=coarse]_&]:min-w-11"
          @click.stop="copy(block.text)"
        >
          <DocumentDuplicateIcon class="w-4 h-4" :stroke-width="1.75" />
        </IconButton>
      </Tooltip>
    </Teleport>
  </div>
</template>
