<template>
  <!--
    Collapsed-by-default "Details" disclosure for chat error rows.
    Shown below the friendly summary on every error variant (generic,
    quota, content-filtered, subscription, llm-not-configured). Surfaces
    the raw upstream provider message so users — including non-dev users
    pointed at LM Studio / Ollama / etc. — can troubleshoot. Hidden when
    `raw` is empty.

    Matches the OutputImage.vue tile-error disclosure pattern (native
    <details>/<summary>) so behavior is consistent across the app.
  -->
  <details v-if="raw" class="rounded-md border border-white/10 bg-white/[0.03] overflow-hidden group">
    <summary
      class="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-content-muted hover:text-content-secondary cursor-pointer select-none transition-colors"
    >
      <ChevronRightIcon class="w-3 h-3 transition-transform group-open:rotate-90" />
      <span>Details</span>
    </summary>
    <pre
      class="px-3 py-2 text-xs whitespace-pre-wrap break-words font-mono text-content-muted max-h-48 overflow-y-auto custom-scrollbar border-t border-white/10"
    >{{ raw }}</pre>
  </details>
</template>

<script setup>
import { ChevronRightIcon } from '@heroicons/vue/24/outline'

defineProps({
  // Raw error text to show inside the disclosure. Empty/falsy = render nothing.
  raw: { type: String, default: '' },
})
</script>
